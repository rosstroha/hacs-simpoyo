"""Exercise setup, polling, availability, and cleanup through Home Assistant."""

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE

from custom_components.simpoyo.api import SimpoyoAuthError, SimpoyoError


async def test_setup_poll_failure_recovery_and_unload(hass, account_entry, api_client):
    account_entry.add_to_hass(hass)
    with patch("custom_components.simpoyo.SimpoyoClient", return_value=api_client):
        assert await hass.config_entries.async_setup(account_entry.entry_id)
        await hass.async_block_till_done()

    states = hass.states.async_all("sensor")
    assert states
    assert all(state.state != STATE_UNAVAILABLE for state in states)
    entity_ids = [state.entity_id for state in states]
    assert any(state.state == "1.5" for state in states)
    assert any(state.state == "2.5" for state in states)

    api_client.async_fetch_usage.side_effect = SimpoyoError("offline")
    await account_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert all(
        hass.states.get(entity_id).state == STATE_UNAVAILABLE
        for entity_id in entity_ids
    )

    api_client.async_fetch_usage.side_effect = None
    await account_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert all(
        hass.states.get(entity_id).state != STATE_UNAVAILABLE
        for entity_id in entity_ids
    )

    assert await hass.config_entries.async_unload(account_entry.entry_id)
    await hass.async_block_till_done()
    api_client.async_close.assert_awaited_once()


async def test_initial_network_failure_closes_session(hass, account_entry, api_client):
    account_entry.add_to_hass(hass)
    api_client.async_fetch_usage.side_effect = SimpoyoError("offline")
    with patch("custom_components.simpoyo.SimpoyoClient", return_value=api_client):
        assert not await hass.config_entries.async_setup(account_entry.entry_id)
        await hass.async_block_till_done()
    api_client.async_close.assert_awaited_once()
    assert not hass.states.async_all("sensor")


async def test_initial_auth_failure_requests_reauthentication(
    hass, account_entry, api_client
):
    account_entry.add_to_hass(hass)
    api_client.async_fetch_usage.side_effect = SimpoyoAuthError("credentials rejected")
    with patch("custom_components.simpoyo.SimpoyoClient", return_value=api_client):
        assert not await hass.config_entries.async_setup(account_entry.entry_id)
        await hass.async_block_till_done()
    assert account_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"].get("source") == "reauth" for flow in flows)
    api_client.async_close.assert_awaited_once()
