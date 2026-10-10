"""Configure a Simpoyo account through the UI."""

from typing import Any

import voluptuous as vol
from aiohttp import CookieJar
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_EMAIL
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.storage import Store

from .api import SimpoyoAuthError, SimpoyoClient, SimpoyoError
from .const import (
    CONF_AUTO_ADD_DEVICES,
    CONF_GMAIL_APP_PASSWORD,
    CONF_GMAIL_EMAIL,
    CONF_INCLUDE_INACTIVE_PLANS,
    DOMAIN,
)


class SimpoyoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Validate credentials and prevent duplicate account entries."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SimpoyoOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_credentials(user_input)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_credentials(user_input, reauth=True)

    async def _async_credentials(
        self, user_input: dict[str, Any] | None, *, reauth: bool = False
    ) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            data = {
                CONF_EMAIL: user_input[CONF_EMAIL].strip().lower(),
                CONF_GMAIL_EMAIL: user_input[CONF_GMAIL_EMAIL].strip().lower(),
                CONF_GMAIL_APP_PASSWORD: user_input[CONF_GMAIL_APP_PASSWORD].replace(
                    " ", ""
                ),
            }
            if not reauth:
                data[CONF_AUTO_ADD_DEVICES] = user_input.get(
                    CONF_AUTO_ADD_DEVICES, True
                )
                data[CONF_INCLUDE_INACTIVE_PLANS] = user_input.get(
                    CONF_INCLUDE_INACTIVE_PLANS, False
                )
            if not all(
                data[key]
                for key in (CONF_EMAIL, CONF_GMAIL_EMAIL, CONF_GMAIL_APP_PASSWORD)
            ) or any("@" not in data[key] for key in (CONF_EMAIL, CONF_GMAIL_EMAIL)):
                errors["base"] = "invalid_input"
            else:
                await self.async_set_unique_id(data[CONF_EMAIL])
                if reauth:
                    self._abort_if_unique_id_mismatch()
                else:
                    self._abort_if_unique_id_configured()
                client = SimpoyoClient(
                    data[CONF_EMAIL],
                    data[CONF_GMAIL_EMAIL],
                    data[CONF_GMAIL_APP_PASSWORD],
                    session=async_create_clientsession(
                        self.hass, cookie_jar=CookieJar()
                    ),
                    executor=self.hass.async_add_executor_job,
                )
                try:
                    await client.async_fetch_usage()
                except SimpoyoAuthError:
                    errors["base"] = "invalid_auth"
                except (SimpoyoError, TimeoutError):
                    errors["base"] = "cannot_connect"
                else:
                    if reauth:
                        entry = self._get_reauth_entry()
                    else:
                        result = self.async_create_entry(
                            title=data[CONF_EMAIL], data=data
                        )
                        # Home Assistant assigns the entry ID after processing this result.
                        self.hass.data.setdefault(f"{DOMAIN}_flow_cookies", {})[
                            data[CONF_EMAIL]
                        ] = client.export_cookies()
                        return result
                    await Store(
                        self.hass, 1, f"{DOMAIN}.{entry.entry_id}", private=True
                    ).async_save({"cookies": client.export_cookies()})
                    return self.async_update_reload_and_abort(entry, data_updates=data)
                finally:
                    await client.async_close()
        defaults = self._get_reauth_entry().data if reauth else {}
        schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL, default=defaults.get(CONF_EMAIL, "")): str,
                vol.Required(
                    CONF_GMAIL_EMAIL, default=defaults.get(CONF_GMAIL_EMAIL, "")
                ): str,
                vol.Required(CONF_GMAIL_APP_PASSWORD): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
            }
        )
        if not reauth:
            schema = schema.extend(
                {
                    vol.Optional(CONF_INCLUDE_INACTIVE_PLANS, default=False): bool,
                    vol.Optional(CONF_AUTO_ADD_DEVICES, default=True): bool,
                }
            )
        return self.async_show_form(
            step_id="reauth_confirm" if reauth else "user",
            data_schema=schema,
            errors=errors,
        )


class SimpoyoOptionsFlow(OptionsFlow):
    """Choose whether to discover expired and depleted SIM plans."""

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_INCLUDE_INACTIVE_PLANS,
                        default=self.config_entry.options.get(
                            CONF_INCLUDE_INACTIVE_PLANS,
                            self.config_entry.data.get(
                                CONF_INCLUDE_INACTIVE_PLANS, False
                            ),
                        ),
                    ): bool,
                    vol.Required(
                        CONF_AUTO_ADD_DEVICES,
                        default=self.config_entry.options.get(
                            CONF_AUTO_ADD_DEVICES,
                            self.config_entry.data.get(CONF_AUTO_ADD_DEVICES, True),
                        ),
                    ): bool,
                }
            ),
        )
