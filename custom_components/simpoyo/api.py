"""Async Simpoyo web client and isolated mailbox authentication."""

from __future__ import annotations

import asyncio
import imaplib
import re
import ssl
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import formatdate, parseaddr
from html.parser import HTMLParser
from http.cookies import SimpleCookie
from typing import Any

import aiohttp
from yarl import URL

BASE = "https://w.simpoyo.com"
AJAX = "/wp-admin/admin-ajax.php"
OTP_FROM = "support@voyeglobal.com"
OTP_SUBJECT = "Voye OTP (One Time Password)"


class SimpoyoError(Exception):
    """A service request or mailbox operation failed."""


class SimpoyoAuthError(SimpoyoError):
    """Simpoyo or Gmail rejected the credentials or verification code."""


class _SessionExpired(SimpoyoError):
    """WordPress returned the response that identifies an expired session."""


class LoginNonce(HTMLParser):
    def __init__(self):
        super().__init__()
        self.value = None

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "input" and fields.get("name") == "woocommerce-login-nonce":
            self.value = fields.get("value")


class AccountLoginState(HTMLParser):
    def __init__(self):
        super().__init__()
        self.logged_in = None

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.logged_in = "logged-in" in dict(attrs).get("class", "").split()


class CodeNodes(HTMLParser):
    def __init__(self):
        super().__init__()
        self.codes = []

    def handle_data(self, data):
        if re.fullmatch(r"\s*[0-9]{6}\s*", data):
            self.codes.append(data.strip())


class UsageCards(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.groups = []
        self.group = None
        self.card = None

    def handle_starttag(self, tag, attrs):
        if tag != "div":
            return
        self.depth += 1
        classes = dict(attrs).get("class", "").split()
        if "customer-plan" in classes:
            self.group = {"depth": self.depth, "header": [], "cards": []}
            self.groups.append(self.group)
        elif "plan-item" in classes and self.group is not None:
            self.card = {"depth": self.depth, "text": []}
            self.group["cards"].append(self.card)

    def handle_endtag(self, tag):
        if tag != "div":
            return
        if self.card is not None and self.card["depth"] == self.depth:
            self.card = None
        if self.group is not None and self.group["depth"] == self.depth:
            self.group = None
        self.depth -= 1

    def handle_data(self, data):
        value = data.strip()
        if value and self.card is not None:
            self.card["text"].append(value)
        elif value and self.group is not None:
            self.group["header"].append(value)

    def records(self):
        result = []
        for group in self.groups:
            header = " ".join(group["header"])
            iccid = re.search(r"\bICCID:\s*(\d+)", header)
            name = re.search(r"\bICCID Name:\s*(.*?)(?:\s+Save\b|$)", header)
            for card in group["cards"]:
                words = card["text"]
                if "Data Left" not in words:
                    continue
                fields = {
                    label: words[words.index(label) + 1]
                    for label in (
                        "Data Left",
                        "Data Used",
                        "Total Data",
                        "Plan Valid Until",
                    )
                    if label in words and words.index(label) + 1 < len(words)
                }
                result.append(
                    {
                        "iccid": iccid.group(1) if iccid else None,
                        "name": name.group(1).strip() if name else None,
                        "plan": words[0] if words else None,
                        "data_left": fields.get("Data Left"),
                        "data_used": fields.get("Data Used"),
                        "total_data": fields.get("Total Data"),
                        "valid_until": fields.get("Plan Valid Until"),
                    }
                )
        return result


def inbox_uids(mailbox):
    status, data = mailbox.uid("SEARCH", None, "ALL")
    if status != "OK":
        raise RuntimeError("Gmail search failed")
    return [int(uid) for uid in data[0].split()]


def latest_uid(mailbox):
    return max(inbox_uids(mailbox), default=0)


def authenticated_otp_sender(message):
    """Trust only Gmail's ingress result, not sender-supplied lower headers.

    Messages must be fetched from Gmail over verified TLS. Gmail is the
    receiving trust boundary and must strip its own forged authserv-id headers
    as required by RFC 8601 section 5. Imported or forwarded mail without this
    direct delivery evidence is deliberately rejected.
    """
    if (
        len(message.get_all("From", [])) != 1
        or len(message.get_all("Subject", [])) != 1
    ):
        return False
    results = []
    ingress = False
    for name, value in message.raw_items():
        if name.lower() == "received":
            if ingress:
                break
            ingress = bool(re.search(r"\bby\s+mx\.google\.com\s", value, re.I))
            if not ingress and re.match(r"\s*from\s", value, re.I):
                # Do not search a sender-supplied lower Received chain.
                return False
        elif ingress and name.lower() == "authentication-results":
            results.append(value)
    if len(results) != 1:
        return False
    sections = results[0].split(";")
    if sections[0].strip().lower() != "mx.google.com":
        return False
    # Only DMARC aligns authentication with the visible From domain. SPF or
    # DKIM success for an unrelated domain cannot authenticate this sender.
    for section in sections[1:]:
        section = re.sub(r"\([^()]*\)", " ", section)
        if re.fullmatch(
            r'\s*dmarc=pass\s+header\.from=(?:voyeglobal\.com|"voyeglobal\.com")\s*',
            section,
            re.I,
        ):
            return True
    return False


def extract_code(raw):
    message = BytesParser(policy=policy.default).parsebytes(raw)
    if not authenticated_otp_sender(message):
        return None
    if parseaddr(str(message.get("From", "")))[1].lower() != OTP_FROM:
        return None
    if str(message.get("Subject", "")) != OTP_SUBJECT:
        return None
    body = message.get_body(preferencelist=("html", "plain"))
    if body is None:
        return None
    content = body.get_content()
    if body.get_content_type() == "text/html":
        parser = CodeNodes()
        parser.feed(content)
        codes = parser.codes
    else:
        codes = re.findall(r"(?<![0-9])[0-9]{6}(?![0-9])", content)
    return codes[0] if len(codes) == 1 else None


def wait_for_code(mailbox, after_uid, timeout=120, checked=None):
    deadline = time.monotonic() + timeout
    checked = set() if checked is None else checked
    while True:
        status, _ = mailbox.noop()
        if status != "OK":
            raise RuntimeError("Gmail inbox refresh failed")
        for uid in reversed(
            [
                uid
                for uid in inbox_uids(mailbox)
                if uid > after_uid and uid not in checked
            ]
        ):
            checked.add(uid)
            status, parts = mailbox.uid("FETCH", str(uid), "(BODY.PEEK[])")
            if status != "OK":
                raise RuntimeError("Gmail message fetch failed")
            for part in parts:
                if isinstance(part, tuple) and isinstance(part[1], bytes):
                    code = extract_code(part[1])
                    if code:
                        return code
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"Timed out waiting for a Simpoyo code; checked {len(checked)} new Gmail messages"
            )
        time.sleep(min(5, remaining))


def data_gb(value):
    match = re.fullmatch(
        r"\s*([0-9]+(?:\.[0-9]+)?)\s*(KB|MB|GB|TB)\s*", value or "", re.I
    )
    if not match:
        raise ValueError("Simpoyo returned an unrecognized data amount")
    return (
        float(match.group(1))
        * {"KB": 1 / 1048576, "MB": 1 / 1024, "GB": 1, "TB": 1024}[
            match.group(2).upper()
        ]
    )


class SimpoyoClient:
    """Reuse an isolated HTTP session, authenticating only when it has expired."""

    def __init__(
        self,
        email: str,
        gmail_email: str,
        gmail_app_password: str,
        *,
        session: aiohttp.ClientSession | None = None,
        executor: Callable = asyncio.to_thread,
    ) -> None:
        self.email = email
        self.gmail_email = gmail_email or email
        self._password = gmail_app_password.replace(" ", "")
        self._session = session
        self._executor = executor
        self._cookies: list[dict[str, str]] = []
        self._lock = asyncio.Lock()
        self._cookie_deadlines: dict[tuple[str, str, str], float] = {}

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(),
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"User-Agent": "Mozilla/5.0"},
            )
            self.import_cookies(self._cookies)
        return self._session

    async def async_close(self) -> None:
        """Close this client's isolated session."""
        if self._session is not None:
            await self._session.close()

    def export_cookies(self) -> list[dict[str, str]]:
        """Convert session cookies to records for private storage."""
        if self._session is None:
            return self._cookies.copy()
        saved_cookies = []
        for cookie in self._session.cookie_jar:
            saved = {
                "name": cookie.key,
                "value": cookie.value,
                **{
                    key: cookie[key]
                    for key in (
                        "domain",
                        "path",
                        "expires",
                        "secure",
                        "httponly",
                        "samesite",
                    )
                },
            }
            if cookie["max-age"]:
                key = (cookie["domain"], cookie["path"], cookie.key)
                deadline = self._cookie_deadlines.get(key)
                if deadline is not None:
                    saved["expires"] = formatdate(deadline, usegmt=True)
                elif not cookie["expires"]:
                    # Skip cookies with unknown expiry to preserve their lifetime.
                    continue
            saved_cookies.append(saved)
        return saved_cookies

    def _remember_cookie_expiry(self, response: aiohttp.ClientResponse) -> None:
        """Save expiry dates so cookies keep their lifetime after a restart."""
        for cookie in response.cookies.values():
            if not cookie["max-age"]:
                continue
            try:
                lifetime = int(cookie["max-age"])
            except ValueError:
                continue
            domain = cookie["domain"].lstrip(".") or response.url.host
            path = cookie["path"] or "/"
            self._cookie_deadlines[(domain, path, cookie.key)] = time.time() + lifetime

    def import_cookies(self, cookies: list[dict[str, str]]) -> None:
        """Restore cookies from Home Assistant's private storage."""
        self._cookies = cookies.copy()
        if self._session is None:
            return
        for saved in cookies:
            domain = saved.get("domain", "").lstrip(".")
            if domain not in ("w.simpoyo.com", "simpoyo.com"):
                continue
            if saved.get("max-age") and not saved.get("expires"):
                continue
            cookie = SimpleCookie()
            cookie[saved["name"]] = saved["value"]
            for key in (
                "domain",
                "path",
                "expires",
                "secure",
                "httponly",
                "samesite",
            ):
                if saved.get(key):
                    cookie[saved["name"]][key] = saved[key]
            self._session.cookie_jar.update_cookies(cookie, response_url=URL(BASE))

    async def _post(self, action: str, fields: dict[str, str]) -> dict[str, Any]:
        async with self._get_session().post(
            BASE + AJAX,
            data={"action": action, **fields},
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Origin": BASE,
                "Referer": BASE + "/",
            },
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            self._remember_cookie_expiry(response)
            if action == "load_customer_plans" and response.status == 400:
                if await response.read() == b"0":
                    raise _SessionExpired("Simpoyo session has expired")
            response.raise_for_status()
            result = await response.json(content_type=None)
        if not isinstance(result, dict):
            raise SimpoyoError("Unexpected response from Simpoyo")
        return result

    async def _load_usage(self) -> list[dict[str, Any]]:
        result = await self._post("load_customer_plans", {})
        if result.get("ok") is not True or not isinstance(result.get("html"), str):
            raise SimpoyoError("Simpoyo did not return usage data")
        parser = UsageCards()
        parser.feed(result["html"])
        plans = parser.records()
        for plan in plans:
            try:
                for key in ("data_left", "data_used", "total_data"):
                    data_gb(plan.get(key))
                datetime.strptime(plan.get("valid_until") or "", "%d/%m/%Y")
            except (TypeError, ValueError) as error:
                raise SimpoyoError("Simpoyo returned malformed plan data") from error
        return plans

    async def _session_expired(self) -> bool:
        async with self._get_session().get(
            BASE + "/my-account/", timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            self._remember_cookie_expiry(response)
            response.raise_for_status()
            page = await response.text()
        parser = AccountLoginState()
        parser.feed(page)
        if parser.logged_in is None:
            raise SimpoyoError("Simpoyo returned an unknown account login state")
        return not parser.logged_in

    def _open_mailbox(self) -> tuple[imaplib.IMAP4_SSL, int]:
        mailbox = imaplib.IMAP4_SSL(
            "imap.gmail.com", 993, ssl_context=ssl.create_default_context(), timeout=20
        )
        try:
            mailbox.login(self.gmail_email, self._password)
            status, _ = mailbox.select("INBOX", readonly=True)
            if status != "OK":
                raise SimpoyoError("Gmail failed to open your inbox")
            return mailbox, latest_uid(mailbox)
        except BaseException:
            with suppress(Exception):
                mailbox.logout()
            raise

    async def _mailbox_call(self, function, *args):
        """Finish an executor operation before allowing mailbox cleanup."""
        task = asyncio.ensure_future(self._executor(function, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # Wait for the running IMAP command before logging out.
            try:
                result = await task
            except Exception:
                raise asyncio.CancelledError from None
            if function == self._open_mailbox:
                with suppress(Exception):
                    await self._executor(result[0].logout)
            raise

    async def _login(self) -> None:
        # Every blocking mailbox operation runs in an executor, including cleanup.
        try:
            mailbox, baseline = await self._mailbox_call(self._open_mailbox)
        except imaplib.IMAP4.error as error:
            raise SimpoyoAuthError("Gmail authentication failed") from error
        try:
            async with self._get_session().get(
                BASE + "/", timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                self._remember_cookie_expiry(response)
                response.raise_for_status()
                page = await response.text()
            nonce = LoginNonce()
            nonce.feed(page)
            if not nonce.value:
                raise SimpoyoError("Simpoyo returned a login form with a missing nonce")
            sent = await self._post(
                "ajax_login",
                {
                    "username": self.email,
                    "woocommerce-login-nonce": nonce.value,
                    "_wp_http_referer": "/",
                },
            )
            if not sent.get("success"):
                raise SimpoyoAuthError("Simpoyo did not send a login code")
            deadline = time.monotonic() + 120
            checked = set()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Timed out waiting for an accepted Simpoyo code")
                code = await self._mailbox_call(
                    wait_for_code, mailbox, baseline, remaining, checked
                )
                if not re.fullmatch(r"[0-9]{6}", code):
                    raise SimpoyoAuthError("The emailed code must contain six digits")
                verified = await self._post(
                    "ajax_login_otp",
                    {
                        **{f"digit-{i}": digit for i, digit in enumerate(code, 1)},
                        "email": sent.get("email", self.email),
                        "check_session_set": "",
                        "redirect": "",
                    },
                )
                if verified.get("success"):
                    break
        finally:
            with suppress(Exception):
                await self._executor(mailbox.logout)

    async def async_fetch_usage(self) -> list[dict[str, Any]]:
        """Fetch usage, renewing a confirmed expired session once."""
        async with self._lock:
            try:
                try:
                    return await self._load_usage()
                except _SessionExpired:
                    if not await self._session_expired():
                        raise
                await self._login()
                return await self._load_usage()
            except SimpoyoError:
                raise
            except (
                aiohttp.ClientError,
                TimeoutError,
                OSError,
                imaplib.IMAP4.error,
                ValueError,
                RuntimeError,
            ) as error:
                raise SimpoyoError("Unable to retrieve Simpoyo usage") from error
