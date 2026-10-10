"""SIM discovery, stable identities, filtering, and individual field values."""

from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.simpoyo.sensor import DESCRIPTIONS


def plan(iccid, **updates):
    return {
        "iccid": iccid,
        "name": "Travel",
        "plan": "US",
        "data_used": "512 MB",
        "data_left": "512 MB",
        "total_data": "1 GB",
        "valid_until": "29/09/2026",
        **updates,
    }


async def setup(hass, entry, client):
    if hass.config_entries.async_get_entry(entry.entry_id) is None:
        entry.add_to_hass(hass)
    with patch("custom_components.simpoyo.SimpoyoClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


def entities(hass, entry):
    return er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)


@pytest.mark.parametrize("include", [False, True])
async def test_sim_fields_filtering_and_expiry_boundary(
    hass, account_entry, api_client, include
):
    account_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        account_entry, options={"include_inactive_plans": include}
    )
    api_client.async_fetch_usage.return_value = [
        plan("active"),
        plan("empty", data_left="0 GB"),
        plan("expired", valid_until="28/09/2026"),
        plan("missing-date", valid_until=None),
        plan(None),
    ]
    with patch(
        "custom_components.simpoyo.sensor.dt_util.now",
        return_value=datetime(2026, 9, 29, tzinfo=timezone.utc),
    ):
        await setup(hass, account_entry, api_client)
        registered = entities(hass, account_entry)
        devices = dr.async_entries_for_config_entry(
            dr.async_get(hass), account_entry.entry_id
        )
        assert len(devices) == (4 if include else 1)
        assert all(
            device.entry_type is dr.DeviceEntryType.SERVICE for device in devices
        )
        assert len(registered) == len(devices) * len(DESCRIPTIONS)
        by_key = {
            entity.unique_id.removeprefix("user@example.com_active_"): hass.states.get(
                entity.entity_id
            )
            for entity in registered
            if entity.unique_id.startswith("user@example.com_active_")
        }
        assert by_key["iccid"].state == "active"
        assert by_key["name"].state == "Travel"
        assert by_key["plan"].state == "US"
        assert by_key["data_used"].state == "0.5"
        assert by_key["data_left"].state == "0.5"
        assert by_key["total_data"].state == "1.0"
        assert by_key["valid_until"].state == date(2026, 9, 29).isoformat()
        assert by_key["status"].state == "ok"
        assert by_key["active_plan_count"].state == "1"
        assert by_key["checked_at"].attributes["device_class"] == "timestamp"


async def test_poll_discovers_new_sims_and_preserves_ids_on_reorder(
    hass, account_entry, api_client
):
    api_client.async_fetch_usage.return_value = [
        plan("first", valid_until="01/01/2099")
    ]
    await setup(hass, account_entry, api_client)
    initial = {e.unique_id: e.entity_id for e in entities(hass, account_entry)}
    api_client.async_fetch_usage.return_value = [
        plan("second", valid_until="01/01/2099"),
        plan("first", name="Renamed", valid_until="01/01/2099"),
    ]
    await account_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    current = {e.unique_id: e.entity_id for e in entities(hass, account_entry)}
    assert len(current) == 2 * len(DESCRIPTIONS)
    assert all(current[key] == entity_id for key, entity_id in initial.items())
    assert hass.states.get(current["user@example.com_first_name"]).state == "Renamed"
    api_client.async_fetch_usage.return_value.reverse()
    await account_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert {e.unique_id: e.entity_id for e in entities(hass, account_entry)} == current

    api_client.async_fetch_usage.return_value = [
        plan("first", data_left="0 GB", valid_until="01/01/2099")
    ]
    await account_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert all(
        hass.states.get(eid).state == STATE_UNAVAILABLE for eid in current.values()
    )

    api_client.async_fetch_usage.return_value = [
        plan("first", valid_until="01/01/2099")
    ]
    await account_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert all(
        hass.states.get(eid).state != STATE_UNAVAILABLE for eid in initial.values()
    )


async def test_legacy_account_entities_are_removed(hass, account_entry, api_client):
    account_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=account_entry.entry_id,
        identifiers={("simpoyo", account_entry.unique_id)},
        name="Simpoyo",
    )
    legacy = registry.async_get_or_create(
        "sensor",
        "simpoyo",
        "user@example.com_data_used",
        config_entry=account_entry,
        device_id=device.id,
    )
    with patch("custom_components.simpoyo.SimpoyoClient", return_value=api_client):
        assert await hass.config_entries.async_setup(account_entry.entry_id)
        await hass.async_block_till_done()
    assert registry.async_get(legacy.entity_id) is None
    assert devices.async_get(device.id) is None


async def test_auto_add_disabled_keeps_existing_devices_across_reload(
    hass, account_entry, api_client
):
    account_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        account_entry, options={"auto_add_devices": False}
    )
    api_client.async_fetch_usage.return_value = [
        plan("first", valid_until="01/01/2099")
    ]
    await setup(hass, account_entry, api_client)
    original = {e.unique_id: e.entity_id for e in entities(hass, account_entry)}
    assert len(original) == len(DESCRIPTIONS)
    api_client.async_fetch_usage.return_value = [
        plan("first", data_left="256 MB", valid_until="01/01/2099"),
        plan("second", valid_until="01/01/2099"),
    ]
    await account_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(original["user@example.com_first_data_left"]).state == "0.25"
    with patch("custom_components.simpoyo.SimpoyoClient", return_value=api_client):
        assert await hass.config_entries.async_reload(account_entry.entry_id)
        await hass.async_block_till_done()
    assert {e.unique_id: e.entity_id for e in entities(hass, account_entry)} == original
    with patch("custom_components.simpoyo.SimpoyoClient", return_value=api_client):
        hass.config_entries.async_update_entry(
            account_entry, options={"auto_add_devices": True}
        )
        await hass.async_block_till_done()
    assert len(entities(hass, account_entry)) == 2 * len(DESCRIPTIONS)


async def test_no_initial_plans_does_not_enable_discovery_when_disabled(
    hass, account_entry, api_client
):
    account_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        account_entry, options={"auto_add_devices": False}
    )
    api_client.async_fetch_usage.return_value = []
    await setup(hass, account_entry, api_client)
    api_client.async_fetch_usage.return_value = [
        plan("later", valid_until="01/01/2099")
    ]
    await account_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    with patch("custom_components.simpoyo.SimpoyoClient", return_value=api_client):
        assert await hass.config_entries.async_reload(account_entry.entry_id)
        await hass.async_block_till_done()
    assert not entities(hass, account_entry)


async def test_device_becomes_unavailable_after_final_valid_day(
    hass, account_entry, api_client
):
    api_client.async_fetch_usage.return_value = [plan("final-day")]
    with patch(
        "custom_components.simpoyo.sensor.dt_util.now",
        return_value=datetime(2026, 9, 29, tzinfo=timezone.utc),
    ):
        await setup(hass, account_entry, api_client)
    ids = [e.entity_id for e in entities(hass, account_entry)]
    with patch(
        "custom_components.simpoyo.sensor.dt_util.now",
        return_value=datetime(2026, 9, 30, tzinfo=timezone.utc),
    ):
        await account_entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
    assert all(hass.states.get(eid).state == STATE_UNAVAILABLE for eid in ids)


async def test_existing_sim_device_becomes_service_without_changing_identity(
    hass, account_entry, api_client
):
    account_entry.add_to_hass(hass)
    devices = dr.async_get(hass)
    original = devices.async_get_or_create(
        config_entry_id=account_entry.entry_id,
        identifiers={("simpoyo", "user@example.com_1234567890")},
        name="Custom SIM",
    )
    devices.async_update_device(original.id, name_by_user="My travel SIM")
    registry = er.async_get(hass)
    entity = registry.async_get_or_create(
        "sensor",
        "simpoyo",
        "user@example.com_1234567890_data_left",
        config_entry=account_entry,
        device_id=original.id,
        suggested_object_id="my_travel_data",
    )
    await setup(hass, account_entry, api_client)
    updated = devices.async_get(original.id)
    assert updated.entry_type is dr.DeviceEntryType.SERVICE
    assert updated.name_by_user == "My travel SIM"
    assert len(dr.async_entries_for_config_entry(devices, account_entry.entry_id)) == 1
    assert registry.async_get(entity.entity_id).device_id == original.id
    assert hass.states.get(entity.entity_id).state == "2.5"
