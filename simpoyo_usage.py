"""Fetch Simpoyo data usage, prompting for an emailed code when login expires."""

import fcntl
import getpass
import imaplib
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from html.parser import HTMLParser
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener
from zoneinfo import ZoneInfo


BASE = "https://w.simpoyo.com"
AJAX = "/wp-admin/admin-ajax.php"
COOKIE_FILE = Path.home() / ".simpoyo-usage-cookies"
CONFIG_FILE = Path(os.environ.get("SIMPOYO_CONFIG", Path.home() / ".simpoyo-usage.json"))
OTP_FROM = "support@voyeglobal.com"
OTP_SUBJECT = "Voye OTP (One Time Password)"


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
                fields = {label: words[words.index(label) + 1]
                          for label in ("Data Left", "Data Used", "Total Data", "Plan Valid Until")
                          if label in words and words.index(label) + 1 < len(words)}
                result.append({
                    "iccid": iccid.group(1) if iccid else None,
                    "name": name.group(1).strip() if name else None,
                    "plan": words[0] if words else None,
                    "data_left": fields.get("Data Left"),
                    "data_used": fields.get("Data Used"),
                    "total_data": fields.get("Total Data"),
                    "valid_until": fields.get("Plan Valid Until"),
                })
        return result


def post(opener, action, fields, base):
    body = urlencode({"action": action, **fields}).encode()
    request = Request(base + AJAX, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": base,
        "Referer": base + "/",
    })
    with opener.open(request, timeout=30) as response:
        return json.load(response)


def login(opener, email, get_code, base=BASE):
    with opener.open(base + "/", timeout=30) as response:
        nonce = LoginNonce()
        nonce.feed(response.read().decode("utf-8"))
    if not nonce.value:
        raise RuntimeError("Simpoyo returned a login form with a missing nonce")
    sent = post(opener, "ajax_login", {
        "username": email,
        "woocommerce-login-nonce": nonce.value,
        "_wp_http_referer": "/",
    }, base)
    if not sent.get("success"):
        raise RuntimeError("Simpoyo did not send a login code")
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        code = get_code()
        if not re.fullmatch(r"[0-9]{6}", code):
            raise ValueError("The emailed code must contain six digits")
        verified = post(opener, "ajax_login_otp", {
            **{f"digit-{i}": digit for i, digit in enumerate(code, 1)},
            "email": sent.get("email", email),
            "check_session_set": "",
            "redirect": "",
        }, base)
        if verified.get("success"):
            return
    raise TimeoutError("Timed out waiting for an accepted Simpoyo code")


def load_usage(opener, base=BASE):
    response = post(opener, "load_customer_plans", {}, base)
    if response.get("ok") is not True or not isinstance(response.get("html"), str):
        raise RuntimeError("Simpoyo did not return usage data")
    cards = UsageCards()
    cards.feed(response["html"])
    return cards.records()


def session_expired(opener, base=BASE):
    with opener.open(base + "/my-account/", timeout=30) as response:
        page = AccountLoginState()
        page.feed(response.read().decode("utf-8"))
    if page.logged_in is None:
        raise RuntimeError("Simpoyo returned an unknown account login state")
    return not page.logged_in


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
    if len(message.get_all("From", [])) != 1 or len(message.get_all("Subject", [])) != 1:
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
        for uid in reversed([uid for uid in inbox_uids(mailbox) if uid > after_uid and uid not in checked]):
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
            raise TimeoutError(f"Timed out waiting for a Simpoyo code; checked {len(checked)} new Gmail messages")
        time.sleep(min(5, remaining))


def fetch_usage():
    config = None
    if CONFIG_FILE.exists():
        os.chmod(CONFIG_FILE, 0o600)
        config = json.loads(CONFIG_FILE.read_text())
    cookie_file = CONFIG_FILE.with_name("cookies.txt") if config else COOKIE_FILE
    cookies = MozillaCookieJar(str(cookie_file))
    if cookie_file.exists():
        os.chmod(cookie_file, 0o600)
        cookies.load(ignore_discard=True)
    opener = build_opener(HTTPCookieProcessor(cookies))
    opener.addheaders = [("User-Agent", "Mozilla/5.0")]
    try:
        usage = load_usage(opener, BASE)
    except HTTPError as error:
        if error.code != 400 or error.read() != b"0" or not session_expired(opener, BASE):
            raise
        if config:
            email = config["email"]
            password = config["gmail_app_password"].replace(" ", "")
            mailbox = imaplib.IMAP4_SSL(
                "imap.gmail.com", 993, ssl_context=ssl.create_default_context(), timeout=20
            )
            try:
                mailbox.login(config.get("gmail_email", email), password)
                status, _ = mailbox.select("INBOX", readonly=True)
                if status != "OK":
                    raise RuntimeError("Gmail failed to open your inbox")
                baseline = latest_uid(mailbox)
                deadline = time.monotonic() + 120
                checked = set()

                def get_code():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Timed out waiting for an accepted Simpoyo code")
                    return wait_for_code(mailbox, baseline, remaining, checked)

                login(opener, email, get_code, BASE)
            finally:
                mailbox.logout()
        else:
            if not sys.stdin.isatty():
                raise RuntimeError("Login expired; run interactively to enter the emailed code") from error
            email = input("Simpoyo email: ").strip()
            if not email:
                raise ValueError("Email is required")
            login(opener, email, lambda: getpass.getpass("Emailed six-digit code: "), BASE)
        usage = load_usage(opener, BASE)
        fd = os.open(cookie_file, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
        os.chmod(cookie_file, 0o600)
        cookies.save(ignore_discard=True)
    return usage


def cache_file():
    return CONFIG_FILE.with_name("usage-cache.json")


def cached_result():
    try:
        return json.loads(cache_file().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"status": "pending", "error": None, "checked_at": None, "plans": []}


def data_gb(value):
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(KB|MB|GB|TB)\s*", value or "", re.I)
    if not match:
        raise ValueError("Simpoyo returned an unrecognized data amount")
    return float(match.group(1)) * {"KB": 1 / 1048576, "MB": 1 / 1024, "GB": 1, "TB": 1024}[match.group(2).upper()]


def sensor_payload(result, today):
    active = []
    for plan in result.get("plans", []):
        try:
            valid_until = datetime.strptime(plan.get("valid_until") or "", "%d/%m/%Y").date()
        except ValueError:
            continue
        if valid_until >= today:
            active.append(plan)
    attributes = {
        "status": result.get("status"), "error": result.get("error"),
        "checked_at": result.get("checked_at"), "active_plan_count": len(active),
    }
    for index, plan in enumerate(active, 1):
        for key in ("iccid", "name", "plan", "data_left", "data_used", "total_data", "valid_until"):
            attributes[f"plan_{index}_{key}"] = plan.get(key)
    return {
        **result,
        "data_used_gb": round(sum(data_gb(plan["data_used"]) for plan in active), 2),
        "flat_attributes": attributes,
    }


def save_result(payload):
    fd, temporary = tempfile.mkstemp(prefix=".simpoyo-usage-", dir=cache_file().parent)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(payload, output)
        os.replace(temporary, cache_file())
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run_worker():
    lock_path = CONFIG_FILE.with_name("worker.lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "r+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        try:
            usage = fetch_usage()
        except Exception as error:
            result = cached_result()
            result.update(status="error", error=type(error).__name__)
            save_result(result)
            raise
        save_result({
            "status": "ok", "error": None,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "plans": usage,
        })


def poll_cache():
    log_path = CONFIG_FILE.with_name("last-error.log")
    fd = os.open(log_path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
    os.chmod(log_path, 0o600)
    try:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--ha-worker"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=fd,
            start_new_session=True,
        )
    finally:
        os.close(fd)
    today = datetime.now(ZoneInfo(os.environ.get("SIMPOYO_TIME_ZONE", "UTC"))).date()
    return sensor_payload(cached_result(), today)


def main():
    if "--ha-poll" in sys.argv[1:]:
        print(json.dumps(poll_cache()))
        return
    if "--ha-worker" in sys.argv[1:]:
        run_worker()
        return
    usage = fetch_usage()
    if "--ha" in sys.argv[1:]:
        print(json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "plans": usage}))
    else:
        print(json.dumps(usage, indent=2))


if __name__ == "__main__":
    main()
