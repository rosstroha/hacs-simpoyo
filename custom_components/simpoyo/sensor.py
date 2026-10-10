"""Sensors for individual SIMs, identified by ICCID."""

from datetime import date, datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfInformation
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import SimpoyoConfigEntry
from .api import data_gb
from .const import CONF_AUTO_ADD_DEVICES, CONF_INCLUDE_INACTIVE_PLANS, DOMAIN
from .coordinator import SimpoyoCoordinator

PARALLEL_UPDATES = 0
DATA_KEYS = ("data_used", "data_left", "total_data")
DESCRIPTIONS = tuple(
    SensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
    )
    for key in DATA_KEYS
) + (
    SensorEntityDescription(key="iccid", translation_key="iccid"),
    SensorEntityDescription(key="name", translation_key="name"),
    SensorEntityDescription(key="plan", translation_key="plan"),
    SensorEntityDescription(
        key="valid_until",
        translation_key="valid_until",
        device_class=SensorDeviceClass.DATE,
    ),
    SensorEntityDescription(key="status", translation_key="status"),
    SensorEntityDescription(
        key="checked_at",
        translation_key="checked_at",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SensorEntityDescription(
        key="active_plan_count", translation_key="active_plan_count"
    ),
)


def expiry(plan: dict) -> date | None:
    """Parse the provider's inclusive expiry date."""
    try:
        return datetime.strptime(plan.get("valid_until") or "", "%d/%m/%Y").date()
    except ValueError:
        return None


def is_active(plan: dict) -> bool:
    """Require remaining data and validity in the Home Assistant time zone."""
    valid_until = expiry(plan)
    try:
        return (
            valid_until is not None
            and valid_until >= dt_util.now().date()
            and data_gb(plan.get("data_left")) > 0
        )
    except ValueError:
        return False


def selected_plans(entry: SimpoyoConfigEntry) -> dict[str, dict]:
    """Never use provider ordering or names as SIM identifiers."""
    include_inactive = entry.options.get(
        CONF_INCLUDE_INACTIVE_PLANS,
        entry.data.get(CONF_INCLUDE_INACTIVE_PLANS, False),
    )
    return {
        str(plan["iccid"]): plan
        for plan in entry.runtime_data.data["plans"]
        if plan.get("iccid") and (include_inactive or is_active(plan))
    }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SimpoyoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Discover SIMs at setup and on every successful poll."""
    registry = er.async_get(hass)
    legacy_ids = {
        f"{entry.unique_id}_{key}" for key in (*DATA_KEYS, "active_plan_count")
    }
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.unique_id in legacy_ids:
            registry.async_remove(entity.entity_id)
    devices = dr.async_get(hass)
    legacy_device = devices.async_get_device(identifiers={(DOMAIN, entry.unique_id)})
    if legacy_device and entry.entry_id in legacy_device.config_entries:
        devices.async_update_device(
            legacy_device.id, remove_config_entry_id=entry.entry_id
        )

    prefix = f"{entry.unique_id}_"
    enrolled = {
        entity.unique_id[len(prefix) : -len("_iccid")]
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
        if entity.unique_id.startswith(prefix) and entity.unique_id.endswith("_iccid")
    }
    first_setup = not entry.data.get("devices_initialized", False)
    if first_setup:
        enrolled.update(selected_plans(entry))
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, "devices_initialized": True}
        )
    auto_add = entry.options.get(
        CONF_AUTO_ADD_DEVICES, entry.data.get(CONF_AUTO_ADD_DEVICES, True)
    )
    known: set[str] = set()

    @callback
    def discover() -> None:
        if not entry.runtime_data.last_update_success:
            return
        plans = selected_plans(entry)
        new = plans.keys() - known
        if not auto_add:
            new &= enrolled
        known.update(new)
        async_add_entities(
            SimpoyoSensor(entry, iccid, plans[iccid], description)
            for iccid in sorted(new)
            for description in DESCRIPTIONS
        )

    discover()
    entry.async_on_unload(entry.runtime_data.async_add_listener(discover))


class SimpoyoSensor(CoordinatorEntity[SimpoyoCoordinator], SensorEntity):
    """One field of a SIM's current plan."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: SimpoyoConfigEntry,
        iccid: str,
        plan: dict,
        description: SensorEntityDescription,
    ):
        super().__init__(entry.runtime_data)
        self.entry = entry
        self.iccid = iccid
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id}_{iccid}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.unique_id}_{iccid}")},
            name=plan.get("name") or f"Simpoyo {iccid}",
            manufacturer="Simpoyo",
            model="eSIM",
            serial_number=iccid,
        )

    @property
    def available(self) -> bool:
        return super().available and self.iccid in selected_plans(self.entry)

    @property
    def native_value(self) -> str | float | int | date | datetime | None:
        plan = selected_plans(self.entry).get(self.iccid)
        if plan is None:
            return None
        key = self.entity_description.key
        if key in DATA_KEYS:
            try:
                return round(data_gb(plan.get(key)), 2)
            except ValueError:
                return None
        if key == "valid_until":
            return expiry(plan)
        if key == "checked_at":
            return dt_util.parse_datetime(self.coordinator.data["checked_at"])
        if key == "status":
            return "ok"
        if key == "active_plan_count":
            return int(is_active(plan))
        value = plan.get(key)
        return str(value) if value is not None else None
