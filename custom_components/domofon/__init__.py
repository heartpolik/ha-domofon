"""Smart Domofon — Home Assistant integration on top of the ESPHome intercom firmware."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_ENTRY_ID,
    ATTR_MODE,
    CONF_DEVICE_ID,
    DOMAIN,
    MODES,
    SERVICE_OPEN,
    SERVICE_REJECT,
    SERVICE_RELEASE,
    SERVICE_SET_MODE,
)
from .hub import DomofonHub, missing_roles, resolve_entities

PLATFORMS: list[Platform] = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type DomofonConfigEntry = ConfigEntry[DomofonHub]

BASE_SCHEMA = vol.Schema({vol.Optional(ATTR_ENTRY_ID): cv.string})
MODE_SCHEMA = BASE_SCHEMA.extend({vol.Required(ATTR_MODE): vol.In(MODES)})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services once for all intercoms."""

    def _hub(call: ServiceCall) -> DomofonHub:
        entries = [e for e in hass.config_entries.async_loaded_entries(DOMAIN)]
        entry_id = call.data.get(ATTR_ENTRY_ID)
        if entry_id:
            entries = [e for e in entries if e.entry_id == entry_id]
        if len(entries) != 1:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="entry_required"
            )
        return entries[0].runtime_data

    async def _open(call: ServiceCall) -> None:
        await _hub(call).async_open()

    async def _reject(call: ServiceCall) -> None:
        await _hub(call).async_reject()

    async def _release(call: ServiceCall) -> None:
        await _hub(call).async_release()

    async def _set_mode(call: ServiceCall) -> None:
        await _hub(call).async_set_mode(call.data[ATTR_MODE])

    hass.services.async_register(DOMAIN, SERVICE_OPEN, _open, BASE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REJECT, _reject, BASE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_RELEASE, _release, BASE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SET_MODE, _set_mode, MODE_SCHEMA)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DomofonConfigEntry) -> bool:
    entities = resolve_entities(hass, entry.data[CONF_DEVICE_ID])
    if missing := missing_roles(entities):
        raise ConfigEntryNotReady(f"Intercom entities not found yet: {', '.join(missing)}")
    hub = DomofonHub(hass, entry, entities)
    await hub.async_start()
    entry.runtime_data = hub
    entry.async_on_unload(entry.add_update_listener(_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DomofonConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.async_stop()
    return ok


async def _reload(hass: HomeAssistant, entry: DomofonConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
