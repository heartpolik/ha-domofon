"""Sensors: last call and calls today (also feeds the Lovelace card)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import DomofonConfigEntry
from .const import SIGNAL_UPDATE
from .hub import DomofonHub


async def async_setup_entry(
    hass: HomeAssistant, entry: DomofonConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    hub = entry.runtime_data
    async_add_entities([CallsTodaySensor(hub), LastCallSensor(hub)])


class _Base(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: DomofonHub, key: str) -> None:
        self.hub = hub
        self._attr_translation_key = key
        self._attr_unique_id = f"{hub.entry.entry_id}_{key}"
        device = hub.device
        if device is not None:
            self._attr_device_info = DeviceInfo(identifiers=device.identifiers, connections=device.connections)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_UPDATE.format(self.hub.entry.entry_id), self._update)
        )

    @callback
    def _update(self) -> None:
        self.async_write_ha_state()


class CallsTodaySensor(_Base):
    """Number of calls today; attributes carry history + entity map for the card."""

    _attr_icon = "mdi:doorbell"

    def __init__(self, hub: DomofonHub) -> None:
        super().__init__(hub, "calls_today")

    @property
    def native_value(self) -> int:
        return self.hub.calls_today

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.hub.card_attributes()


class LastCallSensor(_Base):
    """Time of the last call, outcome in attributes."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:phone-incoming"

    def __init__(self, hub: DomofonHub) -> None:
        super().__init__(hub, "last_call")

    @property
    def native_value(self) -> datetime | None:
        rec = self.hub.last_call
        return dt_util.parse_datetime(rec.start) if rec else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rec = self.hub.last_call
        return rec.as_dict() if rec else {}
