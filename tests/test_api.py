"""Verify session renewal, mailbox login, and network failure handling."""

from http.cookies import SimpleCookie
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest
from yarl import URL

from custom_components.simpoyo.api import SimpoyoClient, SimpoyoError, _SessionExpired


def client():
    return SimpoyoClient(
        "user@example.com",
        "mailbox@example.com",
        "app-password",
        session=Mock(),
    )


def http_error(status):
    return aiohttp.ClientResponseError(
        Mock(real_url="https://example.invalid"), (), status=status
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [http_error(500), aiohttp.ClientConnectionError("offline")]
)
async def test_network_failure_does_not_send_otp(error):
    api = client()
    api._load_usage = AsyncMock(side_effect=error)
    api._session_expired = AsyncMock()
    api._login = AsyncMock()

    with pytest.raises(SimpoyoError):
        await api.async_fetch_usage()

    api._session_expired.assert_not_awaited()
    api._login.assert_not_awaited()


@pytest.mark.asyncio
async def test_unrelated_http_400_does_not_send_otp():
    api = client()
    api._load_usage = AsyncMock(side_effect=http_error(400))
    api._session_expired = AsyncMock(return_value=False)
    api._login = AsyncMock()

    with pytest.raises(SimpoyoError):
        await api.async_fetch_usage()

    api._session_expired.assert_not_awaited()
    api._login.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmed_expired_session_renews_once():
    api = client()
    plans = [{"iccid": "1234567890", "data_left": "2.5 GB"}]
    api._load_usage = AsyncMock(side_effect=[_SessionExpired(), plans])
    api._session_expired = AsyncMock(return_value=True)
    api._login = AsyncMock()

    assert await api.async_fetch_usage() == plans
    api._login.assert_awaited_once()
    assert api._load_usage.await_count == 2


@pytest.mark.asyncio
async def test_failed_retry_does_not_send_second_otp():
    api = client()
    api._load_usage = AsyncMock(side_effect=_SessionExpired())
    api._session_expired = AsyncMock(return_value=True)
    api._login = AsyncMock()

    with pytest.raises(SimpoyoError):
        await api.async_fetch_usage()

    api._login.assert_awaited_once()
    assert api._load_usage.await_count == 2


@pytest.mark.parametrize(
    "action,status,body,expected",
    [
        ("load_customer_plans", 400, b"0", _SessionExpired),
        ("load_customer_plans", 400, b'{"success":false}', aiohttp.ClientResponseError),
        ("load_customer_plans", 500, b"0", aiohttp.ClientResponseError),
        ("ajax_login", 400, b"0", aiohttp.ClientResponseError),
    ],
)
async def test_only_exact_usage_expiry_signature_renews(action, status, body, expected):
    response = Mock(status=status, cookies={})
    response.read = AsyncMock(return_value=body)
    response.raise_for_status.side_effect = http_error(status)
    context = AsyncMock()
    context.__aenter__.return_value = response
    session = Mock()
    session.post.return_value = context
    api = SimpoyoClient(
        "user@example.com", "mailbox@example.com", "password", session=session
    )
    with pytest.raises(expected):
        await api._post(action, {})


async def test_cookie_round_trip_preserves_authentication_and_filters_other_domains():
    api = SimpoyoClient("user@example.com", "mailbox@example.com", "password")
    api._get_session()
    try:
        api.import_cookies(
            [
                {
                    "name": "wordpress_logged_in_test",
                    "value": "session-secret",
                    "domain": "w.simpoyo.com",
                    "path": "/",
                    "secure": True,
                    "expires": "Wed, 30 Sep 2099 12:00:00 GMT",
                },
                {
                    "name": "other",
                    "value": "unrelated",
                    "domain": "example.com",
                    "path": "/",
                },
                {
                    "name": "expired",
                    "value": "stale",
                    "domain": "w.simpoyo.com",
                    "path": "/",
                    "expires": "Sat, 01 Jan 2000 12:00:00 GMT",
                },
            ]
        )
        exported = api.export_cookies()
        assert len(exported) == 1
        assert exported[0]["name"] == "wordpress_logged_in_test"
        assert exported[0]["value"] == "session-secret"
    finally:
        await api.async_close()


async def test_cookie_max_age_becomes_absolute_deadline_across_restart():
    api = SimpoyoClient("user@example.com", "mailbox@example.com", "password")
    restarted = SimpoyoClient("user@example.com", "mailbox@example.com", "password")
    session = api._get_session()
    restarted._get_session()
    cookies = SimpleCookie()
    cookies.load(
        "wordpress_logged_in_test=secret; Domain=w.simpoyo.com; Path=/; Max-Age=120; Secure"
    )
    response = Mock(cookies=cookies, url=URL("https://w.simpoyo.com/"))
    try:
        api._remember_cookie_expiry(response)
        session.cookie_jar.update_cookies(cookies, response_url=response.url)
        saved = api.export_cookies()
        assert len(saved) == 1
        assert saved[0]["expires"]
        assert "max-age" not in saved[0]
        restarted.import_cookies(saved)
        assert restarted.export_cookies() == saved
    finally:
        await api.async_close()
        await restarted.async_close()


async def test_async_login_mailbox_and_usage_round_trip():
    import asyncio
    import threading
    from email.message import EmailMessage
    from unittest.mock import patch

    from custom_components.simpoyo.api import BASE, wait_for_code
    from test_simpoyo_usage import HTML

    main_thread = threading.get_ident()
    state = {"sent": False, "verified": False, "baseline": False}
    message = EmailMessage()
    message["Received"] = "from mail.example by mx.google.com with ESMTPS"
    message["Authentication-Results"] = (
        "mx.google.com; dmarc=pass header.from=voyeglobal.com"
    )
    message["From"] = "support@voyeglobal.com"
    message["Subject"] = "Voye OTP (One Time Password)"
    message.set_content("Your verification code is 123456")

    class Mailbox:
        def login(self, email, password):
            assert threading.get_ident() != main_thread
            assert (email, password) == ("mailbox@example.com", "app-password")

        def select(self, folder, readonly=False):
            assert (folder, readonly) == ("INBOX", True)
            return "OK", [b"1"]

        def noop(self):
            assert threading.get_ident() != main_thread
            return "OK", [b""]

        def uid(self, action, *args):
            assert threading.get_ident() != main_thread
            if action == "SEARCH":
                assert args == (None, "ALL")
                if not state["sent"]:
                    state["baseline"] = True
                return "OK", [b"5 6" if state["sent"] else b"5"]
            assert (action, args) == ("FETCH", ("6", "(BODY.PEEK[])"))
            return "OK", [(b"BODY[]", message.as_bytes())]

        def logout(self):
            assert threading.get_ident() != main_thread

    def response_context(*, status=200, body=b"", text="", payload=None):
        response = Mock(status=status, cookies={})
        response.read = AsyncMock(return_value=body)
        response.text = AsyncMock(return_value=text)
        response.json = AsyncMock(return_value=payload)
        if status >= 400:
            response.raise_for_status.side_effect = http_error(status)
        context = AsyncMock()
        context.__aenter__.return_value = response
        return context

    def post(url, *, data, **kwargs):
        assert url == BASE + "/wp-admin/admin-ajax.php"
        if data["action"] == "load_customer_plans":
            if not state["verified"]:
                return response_context(status=400, body=b"0")
            return response_context(payload={"ok": True, "html": HTML})
        if data["action"] == "ajax_login":
            assert state["baseline"]
            assert data["woocommerce-login-nonce"] == "fresh-nonce"
            state["sent"] = True
            return response_context(
                payload={"success": True, "email": "user@example.com"}
            )
        assert data["action"] == "ajax_login_otp"
        assert "".join(data[f"digit-{index}"] for index in range(1, 7)) == "123456"
        state["verified"] = True
        return response_context(payload={"success": True})

    session = Mock()
    session.post.side_effect = post
    session.get.side_effect = [
        response_context(text='<body class="woocommerce-account"></body>'),
        response_context(
            text='<input name="woocommerce-login-nonce" value="fresh-nonce">'
        ),
    ]
    executor = AsyncMock(side_effect=asyncio.to_thread)
    api = SimpoyoClient(
        "user@example.com",
        "mailbox@example.com",
        "app-password",
        session=session,
        executor=executor,
    )
    mailbox = Mailbox()
    with patch("custom_components.simpoyo.api.imaplib.IMAP4_SSL", return_value=mailbox):
        plans = await api.async_fetch_usage()
    assert plans == [
        {
            "iccid": "1234567890",
            "name": "Travel",
            "plan": "US",
            "data_left": "2.5 GB",
            "data_used": "1.5 GB",
            "total_data": "4 GB",
            "valid_until": "30/09/2026",
        }
    ]
    assert [call.args[0] for call in executor.await_args_list] == [
        api._open_mailbox,
        wait_for_code,
        mailbox.logout,
    ]


async def test_malformed_usage_amount_is_a_fetch_failure():
    from test_simpoyo_usage import HTML

    api = client()
    api._post = AsyncMock(
        return_value={"ok": True, "html": HTML.replace("2.5 GB", "unknown")}
    )
    with pytest.raises(SimpoyoError, match="malformed plan"):
        await api.async_fetch_usage()
