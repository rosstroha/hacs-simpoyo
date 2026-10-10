"""Fixtures for the native Home Assistant integration."""

from unittest.mock import AsyncMock, Mock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def account_entry():
    return MockConfigEntry(
        domain="simpoyo",
        unique_id="user@example.com",
        title="user@example.com",
        data={
            "email": "user@example.com",
            "gmail_email": "mailbox@example.com",
            "gmail_app_password": "app-password",
        },
    )


@pytest.fixture
def api_client():
    api = Mock()
    api.async_close = AsyncMock()
    api.export_cookies.return_value = []
    api.async_fetch_usage = AsyncMock(
        return_value=[
            {
                "iccid": "1234567890",
                "name": "Travel",
                "plan": "US",
                "data_left": "2.5 GB",
                "data_used": "1.5 GB",
                "total_data": "4 GB",
                "valid_until": "30/09/2099",
            }
        ]
    )
    return api
