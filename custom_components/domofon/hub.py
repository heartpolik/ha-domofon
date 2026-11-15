"""Domofon hub: wraps the ESPHome intercom entities, keeps a call log, sends phone notifications."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util, slugify

from .const import (
    ACTION_OPEN,
    ACTION_REJECT,
    ACTION_WINDOW_S,
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
    EVENT_CALL,
    HISTORY_SIZE,
    MODES,
    REQUIRED_ROLES,
    ROLES,
    SIGNAL_UPDATE,
    TG_OPEN,
)

_LOGGER = logging.getLogger(__name__)
STORAGE_VERSION = 1

TEXTS = {
    "uk": {
        "title": "🔔 Домофон",
        "ring": "Дзвонять у двері",
        "ring_auto_open": "Дзвінок — відчиняю автоматично",
        "ring_auto_reject": "Дзвінок — скидаю автоматично",
        "opened": "🔓 Двері відчинено",
        "rejected": "⛔ Виклик скинуто",
        "missed": "📵 Пропущений дзвінок",
        "btn_open": "🔓 Відчинити",
        "btn_reject": "⛔ Скинути",
        "tg_ring": "🔔 Дзвонять у двері · {time}",
        "tg_auto_open": "🔔 Дзвінок · {time} — відчиняю автоматично",
        "tg_auto_reject": "🔔 Дзвінок · {time} — скидаю автоматично",
        "tg_opened": "🔓 Відчинено · {time}{via}",
        "tg_rejected": "⛔ Скинуто · {time}",
        "tg_missed": "📵 Пропущений дзвінок · {time}",
        "tg_opening": "Відчиняю…",
        "tg_expired": "Дзвінок уже завершився",
        "via_telegram": " (з Telegram, {who})",
    },
    "en": {
        "title": "🔔 Intercom",
        "ring": "Someone is at the door",
        "ring_auto_open": "Call — opening automatically",
        "ring_auto_reject": "Call — rejecting automatically",
        "opened": "🔓 Door opened",
        "rejected": "⛔ Call rejected",
        "missed": "📵 Missed call",
        "btn_open": "🔓 Open",
        "btn_reject": "⛔ Reject",
        "tg_ring": "🔔 Someone is at the door · {time}",
        "tg_auto_open": "🔔 Call · {time} — opening automatically",
        "tg_auto_reject": "🔔 Call · {time} — rejecting automatically",
        "tg_opened": "🔓 Opened · {time}{via}",
        "tg_rejected": "⛔ Rejected · {time}",
        "tg_missed": "📵 Missed call · {time}",
        "tg_opening": "Opening…",
        "tg_expired": "The call has already ended",
        "via_telegram": " (Telegram, {who})",
    },
}


@dataclass
class CallRecord:
    """One intercom call."""

    start: str
    mode: str
    outcome: str = "ringing"  # ringing | opened | rejected | missed
    end: str | None = None
    via: str | None = None  # auto | phone | telegram | manual

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_entities(hass: HomeAssistant, device_id: str) -> dict[str, str]:
    """Map roles to entity_ids of the ESPHome device."""
    ent_reg = er.async_get(hass)
    found: dict[str, str] = {}
    for entry in er.async_entries_for_device(ent_reg, device_id, include_disabled_entities=False):
        uid = entry.unique_id or ""
        for role, (domain, name) in ROLES.items():
            if role in found or entry.domain != domain:
                continue
            if (
                uid.endswith(f"/{domain}/{name}")
                or uid.endswith(f"-{domain}-{slugify(name)}")
                or uid.endswith(f"-{'text_sensor' if domain == 'sensor' else domain}-{slugify(name)}")
                or entry.original_name == name
            ):
                found[role] = entry.entity_id
    # ESPHome text sensors use "text_sensor" in the unique_id
    if "last_event" not in found:
        for entry in er.async_entries_for_device(ent_reg, device_id):
            if (entry.unique_id or "").endswith("/text_sensor/Last event"):
                found["last_event"] = entry.entity_id
    return found


def missing_roles(found: dict[str, str]) -> list[str]:
    return [r for r in REQUIRED_ROLES if r not in found]


@dataclass
class DomofonHub:
    """Runtime object stored in entry.runtime_data."""

    hass: HomeAssistant
    entry: ConfigEntry
    entities: dict[str, str]
    history: list[CallRecord] = field(default_factory=list)
    _unsubs: list[CALLBACK_TYPE] = field(default_factory=list)
    _last_event_ts: str | None = None
    _notified_ring: bool = False
    _tg_messages: list[dict[str, Any]] = field(default_factory=list)
    _tg_who: str | None = None

    def __post_init__(self) -> None:
        self._store: Store[dict[str, Any]] = Store(self.hass, STORAGE_VERSION, f"{DOMAIN}.{self.entry.entry_id}")

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def async_start(self) -> None:
        data = await self._store.async_load() or {}
        self.history = [CallRecord(**r) for r in data.get("history", [])][-HISTORY_SIZE:]
        self._unsubs.append(
            async_track_state_change_event(self.hass, [self.entities["event"]], self._on_event_entity)
        )
        self._unsubs.append(
            async_track_state_change_event(self.hass, [self.entities["incoming_call"]], self._on_incoming)
        )
        self._unsubs.append(self.hass.bus.async_listen("mobile_app_notification_action", self._on_action))
        self._unsubs.append(self.hass.bus.async_listen("telegram_callback", self._on_telegram_callback))
        self._unsubs.append(async_track_time_change(self.hass, self._midnight, hour=0, minute=0, second=1))

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    # ── helpers ──────────────────────────────────────────────────────────────
    @property
    def options(self) -> dict[str, Any]:
        return {**DEFAULT_OPTIONS, **self.entry.options}

    @property
    def device_id(self) -> str:
        return self.entry.data[CONF_DEVICE_ID]

    @property
    def device(self) -> dr.DeviceEntry | None:
        return dr.async_get(self.hass).async_get(self.device_id)

    @property
    def mode(self) -> str | None:
        """Current mode key (normal/open_once/...), matched by option index."""
        state = self.hass.states.get(self.entities["mode"])
        if state is None:
            return None
        options = state.attributes.get("options") or []
        try:
            return MODES[options.index(state.state)]
        except (ValueError, IndexError):
            return None

    @property
    def ringing(self) -> bool:
        state = self.hass.states.get(self.entities["incoming_call"])
        return state is not None and state.state == STATE_ON

    @property
    def calls_today(self) -> int:
        today = dt_util.now().date()
        return sum(1 for r in self.history if dt_util.as_local(dt_util.parse_datetime(r.start)).date() == today)

    @property
    def last_call(self) -> CallRecord | None:
        return self.history[-1] if self.history else None

    def _texts(self) -> dict[str, str]:
        return TEXTS["uk"] if (self.hass.config.language or "").startswith("uk") else TEXTS["en"]

    @property
    def _tag(self) -> str:
        return f"domofon_{self.entry.entry_id}"

    def _changed(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_UPDATE.format(self.entry.entry_id))
        self._store.async_delay_save(lambda: {"history": [r.as_dict() for r in self.history]}, 5)

    # ── commands ─────────────────────────────────────────────────────────────
    async def _press(self, role: str) -> None:
        entity_id = self.entities.get(role)
        if not entity_id:
            raise HomeAssistantError(f"Domofon: entity for '{role}' not found on the device")
        await self.hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)

    async def async_open(self, via: str = "manual") -> None:
        await self._press("open")
        self._mark_via(via)

    async def async_reject(self, via: str = "manual") -> None:
        await self._press("reject")
        self._mark_via(via)

    async def async_release(self) -> None:
        await self._press("release")

    async def async_set_mode(self, mode: str) -> None:
        state = self.hass.states.get(self.entities["mode"])
        options = (state.attributes.get("options") if state else None) or []
        idx = MODES.index(mode)
        if idx >= len(options):
            raise HomeAssistantError(f"Domofon: firmware has no mode #{idx}")
        await self.hass.services.async_call(
            "select", "select_option", {"entity_id": self.entities["mode"], "option": options[idx]}, blocking=True
        )

    def _mark_via(self, via: str) -> None:
        rec = self.last_call
        if rec and rec.outcome == "ringing":
            rec.via = via

    # ── listeners ────────────────────────────────────────────────────────────
    @callback
    def _on_event_entity(self, event: Event[EventStateChangedData]) -> None:
        new = event.data["new_state"]
        old = event.data["old_state"]
        if new is None or new.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        if new.state == self._last_event_ts:
            return
        ts = dt_util.parse_datetime(new.state)
        # ignore restored states after reconnects
        if old is not None and old.state == STATE_UNAVAILABLE and ts and dt_util.utcnow() - ts > timedelta(seconds=30):
            self._last_event_ts = new.state
            return
        self._last_event_ts = new.state
        etype = new.attributes.get("event_type")
        now = dt_util.utcnow().isoformat()
        rec = self.last_call
        fresh = rec is not None and rec.outcome == "ringing" and (
            dt_util.utcnow() - dt_util.parse_datetime(rec.start) < timedelta(minutes=5)
        )

        if etype == "ring":
            mode = self.mode or "normal"
            self.history.append(CallRecord(start=now, mode=mode, via="auto" if mode != "normal" else None))
            self.history = self.history[-HISTORY_SIZE:]
            self.hass.async_create_task(self._notify_ring(mode))
        elif etype in ("opened", "rejected", "missed"):
            if not fresh:
                if etype == "missed":
                    return
                # manual open/reject without a detected call
                self.history.append(CallRecord(start=now, mode=self.mode or "normal", via="manual"))
                self.history = self.history[-HISTORY_SIZE:]
                rec = self.history[-1]
            assert rec is not None
            rec.outcome = etype
            rec.end = now
            if rec.via is None and etype != "missed":
                rec.via = "auto" if rec.mode != "normal" else "manual"
            self.hass.async_create_task(self._notify_outcome(etype))
            self.hass.async_create_task(self._telegram_outcome(etype, rec))
        else:
            return
        self.hass.bus.async_fire(
            EVENT_CALL, {"config_entry_id": self.entry.entry_id, "type": etype, **(self.last_call.as_dict() if self.last_call else {})}
        )
        self._changed()

    @callback
    def _on_incoming(self, event: Event[EventStateChangedData]) -> None:
        self._changed()

    @callback
    def _midnight(self, now: datetime) -> None:
        self._changed()

    async def _on_action(self, event: Event) -> None:
        action = event.data.get("action", "")
        if action not in (f"{ACTION_OPEN}_{self.entry.entry_id}", f"{ACTION_REJECT}_{self.entry.entry_id}"):
            return
        rec = self.last_call
        if rec is None or dt_util.utcnow() - dt_util.parse_datetime(rec.start) > timedelta(seconds=ACTION_WINDOW_S):
            _LOGGER.warning("Domofon: notification action %s ignored — the call is too old", action)
            return
        if action.startswith(ACTION_OPEN):
            await self.async_open(via="phone")
        else:
            await self.async_reject(via="phone")

    def _call_is_actionable(self) -> bool:
        rec = self.last_call
        return (
            rec is not None
            and rec.outcome == "ringing"
            and dt_util.utcnow() - dt_util.parse_datetime(rec.start) <= timedelta(seconds=ACTION_WINDOW_S)
        )

    async def _on_telegram_callback(self, event: Event) -> None:
        data = event.data
        if data.get("data") != f"{TG_OPEN}_{self.entry.entry_id}":
            return
        msg = next(
            (
                m
                for m in self._tg_messages
                if m["chat_id"] == data.get("chat_id")
                and m["message_id"] == (data.get("message") or {}).get("message_id")
            ),
            None,
        )
        t = self._texts()
        if msg is None or not self._call_is_actionable():
            await self._tg_answer(data, msg, t["tg_expired"])
            if msg is not None:
                await self._tg_call("edit_replymarkup", msg, {"inline_keyboard": []})
            return
        self._tg_who = " ".join(filter(None, (data.get("from_first"), data.get("from_last")))) or "?"
        await self._tg_answer(data, msg, t["tg_opening"])
        await self.async_open(via="telegram")

    # ── notifications ────────────────────────────────────────────────────────
    async def _send(self, message: str, data: dict[str, Any]) -> None:
        t = self._texts()
        for service in self.options[CONF_NOTIFY]:
            domain, _, name = service.partition(".")
            if not name:
                domain, name = "notify", service
            try:
                await self.hass.services.async_call(
                    domain, name, {"title": t["title"], "message": message, "data": data}, blocking=False
                )
            except Exception:  # noqa: BLE001 — a broken phone must not break the intercom
                _LOGGER.exception("Domofon: notify %s failed", service)

    async def _notify_ring(self, mode: str) -> None:
        self._tg_messages = []
        self._tg_who = None
        if mode != "normal" and not self.options[CONF_NOTIFY_AUTO]:
            return
        await self._telegram_ring(mode)
        if not self.options[CONF_NOTIFY]:
            return
        t = self._texts()
        data: dict[str, Any] = {
            "tag": self._tag,
            "group": "domofon",
            "push": {"interruption-level": "time-sensitive"},
            "ttl": 0,
            "priority": "high",
        }
        if mode == "normal":
            message = t["ring"]
            if self.options[CONF_ACTIONABLE]:
                data["actions"] = [
                    {
                        "action": f"{ACTION_OPEN}_{self.entry.entry_id}",
                        "title": t["btn_open"],
                        "authenticationRequired": self.options[CONF_REQUIRE_AUTH],
                    }
                ]
                if self.options[CONF_REJECT_BUTTON]:
                    data["actions"].append(
                        {
                            "action": f"{ACTION_REJECT}_{self.entry.entry_id}",
                            "title": t["btn_reject"],
                            "destructive": True,
                        }
                    )
        elif mode == "always_reject":
            message = t["ring_auto_reject"]
        else:
            message = t["ring_auto_open"]
        self._notified_ring = True
        await self._send(message, data)

    async def _notify_outcome(self, outcome: str) -> None:
        if not self.options[CONF_NOTIFY]:
            return
        notified, self._notified_ring = self._notified_ring, False
        if self.options[CONF_NOTIFY_OUTCOME]:
            if outcome == "missed" and not notified:
                return
            await self._send(self._texts()[outcome], {"tag": self._tag, "group": "domofon"})
        elif notified and outcome != "missed":
            # handled (opened / rejected): remove the stale "someone is at the door" push with its button
            await self._send("clear_notification", {"tag": self._tag})

    # ── telegram ─────────────────────────────────────────────────────────────
    def _tg_entry_id(self, entity_id: str) -> str | None:
        ent = er.async_get(self.hass).async_get(entity_id)
        return ent.config_entry_id if ent else None

    async def _tg_call(self, service: str, msg: dict[str, Any], data: dict[str, Any]) -> None:
        payload = {"chat_id": msg["chat_id"], "message_id": msg["message_id"], **data}
        if msg.get("config_entry_id"):
            payload["config_entry_id"] = msg["config_entry_id"]
        try:
            await self.hass.services.async_call("telegram_bot", service, payload, blocking=True)
        except Exception:  # noqa: BLE001 — telegram problems must not break the intercom
            _LOGGER.warning("Domofon: telegram_bot.%s failed", service, exc_info=True)

    async def _tg_answer(self, data: dict[str, Any], msg: dict[str, Any] | None, text: str) -> None:
        payload: dict[str, Any] = {"callback_query_id": data.get("id"), "message": text}
        if msg and msg.get("config_entry_id"):
            payload["config_entry_id"] = msg["config_entry_id"]
        try:
            await self.hass.services.async_call("telegram_bot", "answer_callback_query", payload, blocking=True)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Domofon: answer_callback_query failed", exc_info=True)

    async def _telegram_ring(self, mode: str) -> None:
        targets = self.options[CONF_TELEGRAM]
        if not targets or not self.hass.services.has_service("telegram_bot", "send_message"):
            return
        t = self._texts()
        now = dt_util.now().strftime("%H:%M")
        key = {"normal": "tg_ring", "always_reject": "tg_auto_reject"}.get(mode, "tg_auto_open")
        data: dict[str, Any] = {"entity_id": targets, "message": t[key].format(time=now), "parse_mode": "plain_text"}
        if mode == "normal":
            data["inline_keyboard"] = [f"{t['btn_open']}:{TG_OPEN}_{self.entry.entry_id}"]
        try:
            resp = await self.hass.services.async_call(
                "telegram_bot", "send_message", data, blocking=True, return_response=True
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Domofon: telegram send failed", exc_info=True)
            return
        self._tg_messages = [
            {
                "chat_id": c["chat_id"],
                "message_id": c["message_id"],
                "config_entry_id": self._tg_entry_id(c["entity_id"]) if c.get("entity_id") else None,
            }
            for c in (resp or {}).get("chats", [])
        ]

    async def _telegram_outcome(self, outcome: str, rec: CallRecord) -> None:
        msgs, self._tg_messages = self._tg_messages, []
        if not msgs:
            return
        t = self._texts()
        start = dt_util.as_local(dt_util.parse_datetime(rec.start)).strftime("%H:%M")
        via = t["via_telegram"].format(who=self._tg_who) if rec.via == "telegram" and self._tg_who else ""
        text = t[f"tg_{outcome}"].format(time=start, via=via)
        for msg in msgs:
            # editing does not notify — the chat keeps one message per call
            await self._tg_call("edit_message", msg, {"message": text, "parse_mode": "plain_text"})

    # ── for sensors / card ───────────────────────────────────────────────────
    def card_attributes(self) -> dict[str, Any]:
        return {
            "domofon_entities": dict(self.entities),
            "history": [r.as_dict() for r in reversed(self.history[-20:])],
            "mode_key": self.mode,
            "config_entry_id": self.entry.entry_id,
        }
