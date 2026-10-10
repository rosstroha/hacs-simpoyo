"""Validate credentials, duplicate prevention, and credential updates."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.data_entry_flow import FlowResultType

from custom_components.simpoyo.api import SimpoyoAuthError, SimpoyoError

DATA = {
    "email": "user@example.com",
    "gmail_email": "mailbox@example.com",
    "gmail_app_password": "app-password",
}


async def test_user_flow_normalizes_and_creates_entry(hass, api_client):
    with (
        patch(
            "custom_components.simpoyo.config_flow.SimpoyoClient",
            return_value=api_client,
        ),
        patch(
            "custom_components.simpoyo.async_setup_entry",
            new=AsyncMock(return_value=True),
        ),
    ):
        form = await hass.config_entries.flow.async_init(
            "simpoyo", context={"source": "user"}
        )
        assert form["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"],
            {
                **DATA,
                "email": " User@Example.com ",
                "gmail_app_password": "app password",
            },
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["email"] == "user@example.com"
    assert result["data"]["gmail_app_password"] == "apppassword"
    assert result["data"]["auto_add_devices"] is True
    assert result["data"]["include_inactive_plans"] is False
    api_client.async_close.assert_awaited_once()


@pytest.mark.parametrize(
    "error, expected",
    [
        (SimpoyoAuthError("rejected"), "invalid_auth"),
        (SimpoyoError("offline"), "cannot_connect"),
    ],
)
async def test_validation_errors_close_session(hass, api_client, error, expected):
    api_client.async_fetch_usage.side_effect = error
    with patch(
        "custom_components.simpoyo.config_flow.SimpoyoClient", return_value=api_client
    ):
        result = await hass.config_entries.flow.async_init(
            "simpoyo", context={"source": "user"}, data=DATA
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}
    api_client.async_close.assert_awaited_once()


async def test_duplicate_account_does_not_authenticate(hass, account_entry, api_client):
    account_entry.add_to_hass(hass)
    with patch(
        "custom_components.simpoyo.config_flow.SimpoyoClient", return_value=api_client
    ):
        result = await hass.config_entries.flow.async_init(
            "simpoyo", context={"source": "user"}, data=DATA
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    api_client.async_fetch_usage.assert_not_awaited()


async def test_invalid_email_does_not_authenticate(hass, api_client):
    with patch(
        "custom_components.simpoyo.config_flow.SimpoyoClient", return_value=api_client
    ):
        result = await hass.config_entries.flow.async_init(
            "simpoyo", context={"source": "user"}, data={**DATA, "email": "invalid"}
        )
    assert result["errors"] == {"base": "invalid_input"}
    api_client.async_fetch_usage.assert_not_awaited()


async def test_reauthentication_updates_credentials(hass, account_entry, api_client):
    account_entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.simpoyo.config_flow.SimpoyoClient",
            return_value=api_client,
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_reload", return_value=True
        ),
    ):
        form = await hass.config_entries.flow.async_init(
            "simpoyo",
            context={"source": "reauth", "entry_id": account_entry.entry_id},
            data=account_entry.data,
        )
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], {**DATA, "gmail_app_password": "new-password"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert account_entry.data["gmail_app_password"] == "new-password"
    api_client.async_close.assert_awaited_once()


async def test_flow_session_handoff_survives_setup_and_reload(hass, api_client):
    cookies = [
        {
            "name": "wordpress_logged_in_test",
            "value": "session-secret",
            "domain": "w.simpoyo.com",
            "path": "/",
        }
    ]
    api_client.export_cookies.return_value = cookies
    with (
        patch(
            "custom_components.simpoyo.config_flow.SimpoyoClient",
            return_value=api_client,
        ),
        patch("custom_components.simpoyo.SimpoyoClient", return_value=api_client),
    ):
        result = await hass.config_entries.flow.async_init(
            "simpoyo", context={"source": "user"}, data=DATA
        )
        await hass.async_block_till_done()
        entry = result["result"]
        assert entry.runtime_data.last_update_success
        api_client.import_cookies.assert_called_once_with(cookies)
        assert not hass.data["simpoyo_flow_cookies"]
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert api_client.import_cookies.call_count == 2
        api_client.import_cookies.assert_called_with(cookies)
        assert await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()
    from homeassistant.helpers.storage import Store

    assert (
        await Store(hass, 1, f"simpoyo.{entry.entry_id}", private=True).async_load()
        is None
    )


async def test_setup_can_include_inactive_plans(hass, api_client):
    with (
        patch(
            "custom_components.simpoyo.config_flow.SimpoyoClient",
            return_value=api_client,
        ),
        patch(
            "custom_components.simpoyo.async_setup_entry",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            "simpoyo",
            context={"source": "user"},
            data={**DATA, "include_inactive_plans": True, "auto_add_devices": False},
        )
        await hass.async_block_till_done()
    assert result["data"]["include_inactive_plans"] is True
    assert result["data"]["auto_add_devices"] is False


async def test_options_change_reloads_entry(hass, account_entry):
    account_entry.add_to_hass(hass)
    from custom_components.simpoyo import async_reload_entry

    account_entry.async_on_unload(account_entry.add_update_listener(async_reload_entry))
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload", return_value=True
    ) as reload:
        form = await hass.config_entries.options.async_init(account_entry.entry_id)
        assert form["type"] is FlowResultType.FORM
        result = await hass.config_entries.options.async_configure(
            form["flow_id"], {"include_inactive_plans": True}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert account_entry.options["include_inactive_plans"] is True
    reload.assert_awaited_once_with(account_entry.entry_id)
