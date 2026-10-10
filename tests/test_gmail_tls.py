"""Both Gmail clients validate server certificates before sending credentials."""

import json
import ssl
from io import BytesIO
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import pytest

import simpoyo_usage
from custom_components.simpoyo.api import SimpoyoClient


def assert_verified_tls(connection):
    args, kwargs = connection.call_args
    assert args == ("imap.gmail.com", 993)
    context = kwargs["ssl_context"]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname


def test_integration_gmail_validates_server_identity():
    api = SimpoyoClient("user@example.com", "mailbox@example.com", "password")
    with patch(
        "custom_components.simpoyo.api.imaplib.IMAP4_SSL",
        side_effect=ssl.SSLCertVerificationError("untrusted server"),
    ) as connection:
        with pytest.raises(ssl.SSLCertVerificationError):
            api._open_mailbox()
    assert_verified_tls(connection)


def test_standalone_gmail_validates_server_identity():
    config_file = Mock()
    config_file.exists.return_value = True
    config_file.read_text.return_value = json.dumps(
        {"email": "user@example.com", "gmail_app_password": "password"}
    )
    config_file.with_name.return_value.exists.return_value = False
    expired = HTTPError("https://w.simpoyo.com", 400, "expired", {}, BytesIO(b"0"))
    with (
        patch.object(simpoyo_usage, "CONFIG_FILE", config_file),
        patch.object(simpoyo_usage.os, "chmod"),
        patch.object(simpoyo_usage, "MozillaCookieJar"),
        patch.object(simpoyo_usage, "build_opener"),
        patch.object(simpoyo_usage, "load_usage", side_effect=expired),
        patch.object(simpoyo_usage, "session_expired", return_value=True),
        patch.object(
            simpoyo_usage.imaplib,
            "IMAP4_SSL",
            side_effect=ssl.SSLCertVerificationError("untrusted server"),
        ) as connection,
    ):
        with pytest.raises(ssl.SSLCertVerificationError):
            simpoyo_usage.fetch_usage()
    assert_verified_tls(connection)
