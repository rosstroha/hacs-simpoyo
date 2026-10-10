"""Report update status and plan count."""

from homeassistant.core import HomeAssistant

from . import SimpoyoConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SimpoyoConfigEntry
) -> dict:
    """Return update status and plan count for account diagnostics."""
    coordinator = entry.runtime_data
    return {
        "last_update_success": coordinator.last_update_success,
        "plan_count": len((coordinator.data or {}).get("plans", [])),
    }
