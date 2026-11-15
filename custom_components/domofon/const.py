"""Constants for the Smart Domofon integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "domofon"

CONF_DEVICE_ID: Final = "device_id"
CONF_NOTIFY: Final = "notify_services"
CONF_ACTIONABLE: Final = "actionable"
CONF_REQUIRE_AUTH: Final = "require_auth"
CONF_NOTIFY_OUTCOME: Final = "notify_outcome"
CONF_REJECT_BUTTON: Final = "reject_button"
CONF_NOTIFY_AUTO: Final = "notify_auto"
CONF_TELEGRAM: Final = "telegram_targets"

DEFAULT_OPTIONS: Final = {
    CONF_NOTIFY: [],
    CONF_ACTIONABLE: True,
    CONF_REQUIRE_AUTH: True,
    CONF_NOTIFY_OUTCOME: False,
    CONF_REJECT_BUTTON: False,
    CONF_NOTIFY_AUTO: True,
    CONF_TELEGRAM: [],
}

# role -> (entity domain, ESPHome entity name). The firmware in esphome/ uses these names.
ROLES: Final = {
    "mode": ("select", "Mode"),
    "open": ("button", "Open"),
    "reject": ("button", "Reject"),
    "release": ("button", "Release line"),
    "incoming_call": ("binary_sensor", "Incoming call"),
    "event": ("event", "Event"),
    "last_event": ("sensor", "Last event"),
}
REQUIRED_ROLES: Final = ("mode", "open", "reject", "incoming_call", "event")

# Firmware mode options are matched by position, so translated option names keep working.
MODES: Final = ("normal", "open_once", "always_open", "always_reject")

ACTION_OPEN: Final = "DOMOFON_OPEN"
ACTION_REJECT: Final = "DOMOFON_REJECT"
# Telegram inline button callback data (+ "_<entry_id>", ≤ 64 bytes)
TG_OPEN: Final = "/domofon_open"

# A notification action is accepted only this long after the ring (seconds).
ACTION_WINDOW_S: Final = 90
HISTORY_SIZE: Final = 50

SIGNAL_UPDATE: Final = "domofon_update_{}"
EVENT_CALL: Final = "domofon_call"

SERVICE_OPEN: Final = "open"
SERVICE_REJECT: Final = "reject"
SERVICE_RELEASE: Final = "release"
SERVICE_SET_MODE: Final = "set_mode"
ATTR_ENTRY_ID: Final = "config_entry_id"
ATTR_MODE: Final = "mode"
