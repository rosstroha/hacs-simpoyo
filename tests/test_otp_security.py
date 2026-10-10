"""OTP sender authentication and retry regressions for both clients."""

from email.message import EmailMessage
from unittest.mock import AsyncMock, Mock, patch

import pytest

import simpoyo_usage as standalone
from custom_components.simpoyo import api


@pytest.fixture(params=[api, standalone], ids=["integration", "standalone"])
def implementation(request):
    return request.param


def email_bytes(
    result="dmarc=pass (p=NONE sp=NONE dis=NONE) header.from=voyeglobal.com",
    *,
    code="123456",
    forged=False,
    duplicate=False,
    ingress=True,
):
    message = EmailMessage()
    if ingress:
        message["Received"] = "from outbound.example by mx.google.com with ESMTPS"
    message["Authentication-Results"] = "mx.google.com; " + result
    if forged:
        message["Received"] = "from attacker.example by outbound.example with SMTP"
        message["Authentication-Results"] = (
            "mx.google.com; dmarc=pass header.from=voyeglobal.com"
        )
    if duplicate:
        message["Authentication-Results"] = (
            "mx.google.com; dmarc=pass header.from=voyeglobal.com"
        )
    message["From"] = "support@voyeglobal.com"
    message["Subject"] = "Voye OTP (One Time Password)"
    message.set_content("Your code is " + code)
    return message.as_bytes()


def test_authenticated_direct_gmail_delivery_is_accepted(implementation):
    assert implementation.extract_code(email_bytes()) == "123456"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ingress": False},
        {"result": "dmarc=fail header.from=voyeglobal.com", "forged": True},
        {
            "result": "dkim=pass header.i=@attacker.example; spf=pass smtp.mailfrom=attacker.example"
        },
        {"result": "dmarc=pass header.from=attacker.example"},
        {"duplicate": True},
    ],
)
def test_spoofed_or_unaligned_authentication_is_rejected(implementation, kwargs):
    assert implementation.extract_code(email_bytes(**kwargs)) is None


def test_lower_forged_received_chain_is_rejected(implementation):
    raw = (
        b"Received: from attacker.example by external.example with SMTP\n"
        + email_bytes()
    )
    assert implementation.extract_code(raw) is None


def test_duplicate_sender_is_rejected(implementation):
    assert (
        implementation.extract_code(b"From: attacker@example.com\n" + email_bytes())
        is None
    )


def test_wait_skips_spoofed_email_and_preserves_checked_uids(implementation):
    messages = {
        1: email_bytes(code="123456"),
        2: email_bytes(
            "dmarc=fail header.from=voyeglobal.com", code="999999", forged=True
        ),
    }
    mailbox = Mock()
    mailbox.noop.return_value = ("OK", [])

    def uid(action, *args):
        if action == "SEARCH":
            return "OK", [b" ".join(str(uid).encode() for uid in messages)]
        return "OK", [(b"BODY[]", messages[int(args[0])])]

    mailbox.uid.side_effect = uid
    checked = set()
    assert implementation.wait_for_code(mailbox, 0, 1, checked) == "123456"
    messages[3] = email_bytes(code="654321")
    assert implementation.wait_for_code(mailbox, 0, 1, checked) == "654321"
    assert checked == {1, 2, 3}


async def test_integration_retries_rejected_candidate_without_resending_code():
    mailbox = Mock()
    response = Mock(cookies={})
    response.text = AsyncMock(
        return_value='<input name="woocommerce-login-nonce" value="nonce">'
    )
    context = AsyncMock()
    context.__aenter__.return_value = response
    session = Mock()
    session.get.return_value = context
    client = api.SimpoyoClient(
        "user@example.com", "mail@example.com", "password", session=session
    )
    client._mailbox_call = AsyncMock(side_effect=[(mailbox, 0), "123456", "654321"])
    client._executor = AsyncMock()
    client._post = AsyncMock(
        side_effect=[{"success": True}, {"success": False}, {"success": True}]
    )
    await client._login()
    assert [call.args[0] for call in client._post.await_args_list] == [
        "ajax_login",
        "ajax_login_otp",
        "ajax_login_otp",
    ]
    waits = client._mailbox_call.await_args_list[1:]
    assert waits[0].args[4] is waits[1].args[4]
    assert 0 < waits[1].args[3] <= waits[0].args[3] <= 120


def test_standalone_retries_rejected_candidate_without_resending_code():
    opener = Mock()
    opener.open.return_value.__enter__ = Mock(
        return_value=Mock(
            read=Mock(
                return_value=b'<input name="woocommerce-login-nonce" value="nonce">'
            )
        )
    )
    opener.open.return_value.__exit__ = Mock(return_value=False)
    get_code = Mock(side_effect=["123456", "654321"])
    with patch.object(
        standalone,
        "post",
        side_effect=[{"success": True}, {"success": False}, {"success": True}],
    ) as post:
        standalone.login(opener, "user@example.com", get_code)
    assert [call.args[1] for call in post.call_args_list] == [
        "ajax_login",
        "ajax_login_otp",
        "ajax_login_otp",
    ]


async def test_integration_rejected_candidate_cannot_extend_deadline():
    response = Mock(cookies={})
    response.text = AsyncMock(
        return_value='<input name="woocommerce-login-nonce" value="nonce">'
    )
    context = AsyncMock()
    context.__aenter__.return_value = response
    session = Mock()
    session.get.return_value = context
    client = api.SimpoyoClient(
        "user@example.com", "mail@example.com", "password", session=session
    )
    client._mailbox_call = AsyncMock(side_effect=[(Mock(), 0), "123456"])
    client._executor = AsyncMock()
    client._post = AsyncMock(side_effect=[{"success": True}, {"success": False}])
    with patch.object(api.time, "monotonic", side_effect=[0, 1, 121]):
        with pytest.raises(TimeoutError, match="accepted Simpoyo code"):
            await client._login()
    assert client._mailbox_call.await_count == 2


def test_standalone_rejected_candidate_cannot_extend_deadline():
    opener = Mock()
    opener.open.return_value.__enter__ = Mock(
        return_value=Mock(
            read=Mock(
                return_value=b'<input name="woocommerce-login-nonce" value="nonce">'
            )
        )
    )
    opener.open.return_value.__exit__ = Mock(return_value=False)
    get_code = Mock(return_value="123456")
    with (
        patch.object(standalone.time, "monotonic", side_effect=[0, 1, 121]),
        patch.object(
            standalone, "post", side_effect=[{"success": True}, {"success": False}]
        ),
    ):
        with pytest.raises(TimeoutError, match="accepted Simpoyo code"):
            standalone.login(opener, "user@example.com", get_code)
    get_code.assert_called_once()
