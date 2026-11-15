"""Config and options flow for Smart Domofon."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr, selector

from .const import (
    CONF_ACTIONABLE,
    CONF_DEVICE_ID,
    CONF_NOTIFY,
    CONF_NOTIFY_AUTO,
    CONF_NOTIFY_OUTCOME,
    CONF_REJECT_BUTTON,
    CONF_REQUIRE_AUTH,
    CONF_TELEGRAM,
    DEFAULT_OPTIONS,
    DOMAIN,
)
from .hub import missing_roles, resolve_entities


class DomofonConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pick the ESPHome intercom device."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID]
            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured()
            found = resolve_entities(self.hass, device_id)
            if missing := missing_roles(found):
                errors["base"] = "missing_entities"
                placeholders["missing"] = ", ".join(missing)
            else:
                device = dr.async_get(self.hass).async_get(device_id)
                title = (device.name_by_user or device.name) if device else "Domofon"
                return self.async_create_entry(
                    title=title or "Domofon", data={CONF_DEVICE_ID: device_id}, options=dict(DEFAULT_OPTIONS)
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): selector.DeviceSelector(
                    selector.DeviceSelectorConfig(integration="esphome")
                )
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors, description_placeholders=placeholders or {"missing": ""}
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DomofonOptionsFlow()


class DomofonOptionsFlow(OptionsFlow):
    """Notification settings."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = {**DEFAULT_OPTIONS, **self.config_entry.options}
        services = sorted(
            f"notify.{name}"
            for name in self.hass.services.async_services_for_domain("notify")
            if name not in ("notify", "send_message", "persistent_notification")
        )
        schema = vol.Schema(
            {
                vol.Optional(CONF_NOTIFY, default=opts[CONF_NOTIFY]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=services, multiple=True, custom_value=True, mode=selector.SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Optional(CONF_ACTIONABLE, default=opts[CONF_ACTIONABLE]): selector.BooleanSelector(),
                vol.Optional(CONF_REQUIRE_AUTH, default=opts[CONF_REQUIRE_AUTH]): selector.BooleanSelector(),
                vol.Optional(CONF_REJECT_BUTTON, default=opts[CONF_REJECT_BUTTON]): selector.BooleanSelector(),
                vol.Optional(CONF_NOTIFY_AUTO, default=opts[CONF_NOTIFY_AUTO]): selector.BooleanSelector(),
                vol.Optional(CONF_NOTIFY_OUTCOME, default=opts[CONF_NOTIFY_OUTCOME]): selector.BooleanSelector(),
                vol.Optional(CONF_TELEGRAM, default=opts[CONF_TELEGRAM]): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="notify", integration="telegram_bot", multiple=True)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
