"""Plan aggregation includes depletion and the final valid day."""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

from custom_components.simpoyo.sensor import DESCRIPTIONS, SimpoyoSensor


def test_expiry_boundary_depleted_plans_and_mixed_units(account_entry):
    coordinator = Mock()
    coordinator.last_update_success = True
    coordinator.data = {
        "checked_at": "2026-09-29T12:00:00Z",
        "plans": [
            {
                "name": "Depleted",
                "data_used": "8 GB",
                "data_left": "0 GB",
                "total_data": "8 GB",
                "valid_until": "29/09/2026",
            },
            {
                "name": "Small",
                "data_used": "512 MB",
                "data_left": "512 MB",
                "total_data": "1 GB",
                "valid_until": "30/09/2026",
            },
            {
                "name": "Expired",
                "data_used": "7 GB",
                "data_left": "1 GB",
                "total_data": "8 GB",
                "valid_until": "28/09/2026",
            },
        ],
    }
    account_entry.runtime_data = coordinator
    sensors = {
        description.key: SimpoyoSensor(account_entry, description)
        for description in DESCRIPTIONS
    }

    with patch(
        "custom_components.simpoyo.sensor.dt_util.now",
        return_value=datetime(2026, 9, 29, tzinfo=timezone.utc),
    ):
        assert sensors["active_plan_count"].native_value == 2
        assert sensors["data_used"].native_value == 8.5
        assert sensors["data_left"].native_value == 0.5
        assert sensors["total_data"].native_value == 9
        attributes = sensors["data_used"].extra_state_attributes
        assert attributes["plan_1_name"] == "Depleted"
        assert attributes["plan_1_data_left"] == "0 GB"
        assert "plan_3_name" not in attributes

    with patch(
        "custom_components.simpoyo.sensor.dt_util.now",
        return_value=datetime(2026, 9, 30, tzinfo=timezone.utc),
    ):
        assert sensors["active_plan_count"].native_value == 1
        assert sensors["data_used"].native_value == 0.5

    with patch(
        "custom_components.simpoyo.sensor.dt_util.now",
        return_value=datetime(2026, 10, 1, tzinfo=timezone.utc),
    ):
        assert sensors["active_plan_count"].native_value == 0
        assert sensors["data_used"].native_value == 0
