"""Usage sensors shared by all plans on an account."""

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import SimpoyoConfigEntry
from .api import data_gb
from .const import DOMAIN
from .coordinator import SimpoyoCoordinator

PARALLEL_UPDATES = 0
DESCRIPTIONS = (
    SensorEntityDescription(
        key="data_used",
        translation_key="data_used",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="data_left",
        translation_key="data_left",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="total_data",
        translation_key="total_data",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="active_plan_count",
        translation_key="active_plan_count",
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SimpoyoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Keep the same account sensors when plan counts change."""
    async_add_entities(
        SimpoyoSensor(entry, description) for description in DESCRIPTIONS
    )


class SimpoyoSensor(CoordinatorEntity[SimpoyoCoordinator], SensorEntity):
    """A measurement of current, unexpired plans."""

    _attr_has_entity_name = True

    def __init__(self, entry: SimpoyoConfigEntry, description: SensorEntityDescription):
        super().__init__(entry.runtime_data)
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},
            name="Simpoyo",
            manufacturer="Simpoyo",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def active_plans(self) -> list[dict]:
        today = dt_util.now().date()
        plans = []
        for plan in self.coordinator.data["plans"]:
            try:
                valid_until = datetime.strptime(
                    plan.get("valid_until") or "", "%d/%m/%Y"
                ).date()
            except ValueError:
                continue
            if valid_until >= today:
                plans.append(plan)
        return plans

    @property
    def native_value(self) -> float | int:
        plans = self.active_plans
        if self.entity_description.key == "active_plan_count":
            return len(plans)
        return round(
            sum(data_gb(plan[self.entity_description.key]) for plan in plans), 2
        )

    @property
    def extra_state_attributes(self) -> dict | None:
        if self.entity_description.key != "data_used":
            return None
        plans = self.active_plans
        attributes = {
            "status": "ok" if self.coordinator.last_update_success else "error",
            "checked_at": self.coordinator.data["checked_at"],
            "active_plan_count": len(plans),
        }
        for index, plan in enumerate(plans, 1):
            for key in (
                "iccid",
                "name",
                "plan",
                "data_left",
                "data_used",
                "total_data",
                "valid_until",
            ):
                attributes[f"plan_{index}_{key}"] = plan.get(key)
        return attributes
