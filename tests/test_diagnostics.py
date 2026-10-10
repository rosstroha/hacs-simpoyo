"""Verify diagnostic fields and account privacy."""

from unittest.mock import Mock

from custom_components.simpoyo.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_exclude_account_and_plan_details(hass, account_entry):
    account_entry.runtime_data = Mock(
        last_update_success=True,
        data={"plans": [{"iccid": "private-sim", "name": "Private name"}]},
    )
    assert await async_get_config_entry_diagnostics(hass, account_entry) == {
        "last_update_success": True,
        "plan_count": 1,
    }
