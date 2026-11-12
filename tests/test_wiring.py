"""Tests that services, events, history and habit persistence are wired into the integration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from custom_components.roomer.const import DOMAIN, HABIT_SAVE_INTERVAL
from custom_components.roomer.coordinator import LLMPresenceCoordinator
from custom_components.roomer.habits import HabitPredictor
from custom_components.roomer.history import HistoryTracker
from custom_components.roomer.notifications import (
    EVENT_PERSON_ARRIVED,
    EVENT_PERSON_LEFT,
    EVENT_ROOM_CHANGED,
    NotificationManager,
)

SERVICES_YAML = Path(__file__).parent.parent / "custom_components" / "roomer" / "services.yaml"


def _make_entry():
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {"persons": [{"name": "Alice"}], "pets": []}
    entry.options = {}
    return entry


def _make_hass():
    hass = MagicMock()
    hass.data = {}
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    hass.services.has_service = MagicMock(return_value=False)
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.bus.async_fire = MagicMock()
    return hass


async def _setup_entry(hass, entry):
    """Run async_setup_entry with heavy components mocked; return registered services."""
    from custom_components.roomer import async_setup_entry

    registered = {}

    def capture_register(domain, service, handler, schema=None, supports_response=None):
        registered[service] = {"handler": handler, "supports_response": supports_response}

    hass.services.async_register = capture_register

    with (
        patch("custom_components.roomer.LLMPresenceCoordinator") as mock_coord_class,
        patch("custom_components.roomer.EventLogger") as mock_logger_class,
        patch("custom_components.roomer.VisionIdentifier"),
        patch("custom_components.roomer.CameraTrackingController"),
    ):
        mock_coordinator = MagicMock()
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()
        mock_coord_class.return_value = mock_coordinator
        mock_logger_class.return_value.cleanup = MagicMock(return_value={})
        await async_setup_entry(hass, entry)

    return registered


def _bare_coordinator(hass, tmp_path):
    """Build a coordinator without running DataUpdateCoordinator setup."""
    coordinator = LLMPresenceCoordinator.__new__(LLMPresenceCoordinator)
    coordinator.hass = hass
    coordinator._previous_rooms = {}
    coordinator._last_clue = {}
    coordinator._reason_state = {}
    coordinator.event_logger = MagicMock()
    coordinator.event_logger.async_log_room_transition = AsyncMock()
    coordinator.history_tracker = HistoryTracker(config_path=tmp_path)
    coordinator.notification_manager = NotificationManager(hass)
    coordinator.habit_predictor = HabitPredictor(config_path=tmp_path)
    coordinator._habits_dirty = False
    coordinator._last_habit_save = float("-inf")
    return coordinator


def _fired(hass, event_type):
    return [c.args[1] for c in hass.bus.async_fire.call_args_list if c.args[0] == event_type]


class TestServiceRegistration:
    """All services are registered from one place and match services.yaml."""

    @pytest.mark.asyncio
    async def test_setup_registers_all_services_in_services_yaml(self):
        registered = await _setup_entry(_make_hass(), _make_entry())

        documented = set(yaml.safe_load(SERVICES_YAML.read_text()))
        assert set(registered) == documented
        assert documented == {
            "refresh",
            "correct_room",
            "get_history",
            "clear_history",
            "get_patterns",
            "identify_person",
            "enable_tracking",
            "disable_tracking",
            "cleanup_storage",
        }

    @pytest.mark.asyncio
    async def test_data_services_support_responses(self):
        from homeassistant.core import SupportsResponse

        registered = await _setup_entry(_make_hass(), _make_entry())

        assert registered["get_history"]["supports_response"] == SupportsResponse.ONLY
        assert registered["get_patterns"]["supports_response"] == SupportsResponse.ONLY
        assert registered["identify_person"]["supports_response"] == SupportsResponse.OPTIONAL
        assert registered["cleanup_storage"]["supports_response"] == SupportsResponse.OPTIONAL
        assert registered["refresh"]["supports_response"] == SupportsResponse.NONE

    @pytest.mark.asyncio
    async def test_already_registered_services_are_skipped(self):
        hass = _make_hass()
        hass.services.has_service = MagicMock(return_value=True)

        registered = await _setup_entry(hass, _make_entry())

        assert registered == {}


class TestOptionsReload:
    """Options changes reload the entry."""

    @pytest.mark.asyncio
    async def test_update_listener_registered_and_cleaned_up(self):
        from custom_components.roomer import async_reload_entry

        entry = _make_entry()
        await _setup_entry(_make_hass(), entry)

        entry.add_update_listener.assert_called_once_with(async_reload_entry)
        unload_callbacks = [c.args[0] for c in entry.async_on_unload.call_args_list]
        assert entry.add_update_listener.return_value in unload_callbacks

    @pytest.mark.asyncio
    async def test_periodic_cleanup_cancelled_on_unload(self):
        entry = _make_entry()
        with patch("custom_components.roomer.async_track_time_interval") as mock_track:
            await _setup_entry(_make_hass(), entry)

        unload_callbacks = [c.args[0] for c in entry.async_on_unload.call_args_list]
        assert mock_track.return_value in unload_callbacks


class TestServicesUseCoordinatorComponents:
    """Service handlers reach the coordinator's instances via hass.data[DOMAIN][entry_id]."""

    @pytest.mark.asyncio
    async def test_get_history_and_patterns_read_coordinator_tracker(self, tmp_path):
        hass = _make_hass()
        entry = _make_entry()
        registered = await _setup_entry(hass, entry)

        tracker = HistoryTracker(config_path=tmp_path)
        tracker.record_transition("Alice", "bedroom", "kitchen", 0.9)
        coordinator = MagicMock()
        coordinator.history_tracker = tracker
        hass.data[DOMAIN][entry.entry_id] = coordinator

        call = MagicMock()
        call.data = {"entity_name": "Alice", "limit": 20}
        response = await registered["get_history"]["handler"](call)
        assert [t["to_room"] for t in response["transitions"]] == ["kitchen"]

        call.data = {"entity_name": "Alice"}
        response = await registered["get_patterns"]["handler"](call)
        assert "patterns" in response

    @pytest.mark.asyncio
    async def test_clear_history_clears_coordinator_tracker(self, tmp_path):
        hass = _make_hass()
        entry = _make_entry()
        registered = await _setup_entry(hass, entry)

        tracker = HistoryTracker(config_path=tmp_path)
        tracker.record_transition("Alice", "bedroom", "kitchen", 0.9)
        coordinator = MagicMock()
        coordinator.history_tracker = tracker
        hass.data[DOMAIN][entry.entry_id] = coordinator

        call = MagicMock()
        call.data = {}
        await registered["clear_history"]["handler"](call)

        assert tracker.get_recent_transitions("Alice") == []

    @pytest.mark.asyncio
    async def test_correct_room_learns_and_saves_habit(self, tmp_path):
        hass = _make_hass()
        hass.states.get = MagicMock(return_value=None)
        entry = _make_entry()
        registered = await _setup_entry(hass, entry)

        predictor = HabitPredictor(config_path=tmp_path)
        coordinator = MagicMock()
        coordinator.habit_predictor = predictor
        hass.data[DOMAIN][entry.entry_id] = coordinator

        call = MagicMock()
        call.data = {"entity_id": "sensor.alice_room", "room": "office", "confidence": 1.0}
        await registered["correct_room"]["handler"](call)

        assert "Alice" in predictor.habits
        saved = json.loads((tmp_path / "roomer_learned_habits.json").read_text())
        assert "Alice" in saved["patterns"]

    @pytest.mark.asyncio
    async def test_history_services_without_coordinator(self):
        from custom_components.roomer.services import (
            async_handle_clear_history,
            async_handle_get_history,
            async_handle_get_patterns,
        )

        hass = _make_hass()
        call = MagicMock()
        call.data = {"entity_name": "Alice"}

        assert await async_handle_get_history(hass, call) == []
        assert await async_handle_get_patterns(hass, call) == []
        await async_handle_clear_history(hass, call)


class TestCoordinatorOwnsComponents:
    """The coordinator creates the history tracker and notification manager."""

    def test_default_components_created(self):
        from custom_components.roomer import coordinator as coordinator_module

        hass = MagicMock()
        entry = _make_entry()
        with (
            patch.object(coordinator_module.DataUpdateCoordinator, "__init__", return_value=None),
            patch.object(coordinator_module, "get_provider"),
            patch.object(coordinator_module, "HistoryTracker") as mock_tracker,
            patch.object(coordinator_module, "HabitPredictor"),
            patch.object(coordinator_module, "EventLogger"),
        ):
            coordinator = LLMPresenceCoordinator(hass, entry)

        assert coordinator.history_tracker is mock_tracker.return_value
        assert isinstance(coordinator.notification_manager, NotificationManager)

    def test_notifications_can_be_disabled(self):
        from custom_components.roomer import coordinator as coordinator_module
        from custom_components.roomer.const import CONF_NOTIFICATIONS_ENABLED

        hass = MagicMock()
        entry = _make_entry()
        entry.options = {CONF_NOTIFICATIONS_ENABLED: False}
        with (
            patch.object(coordinator_module.DataUpdateCoordinator, "__init__", return_value=None),
            patch.object(coordinator_module, "get_provider"),
            patch.object(coordinator_module, "HistoryTracker"),
            patch.object(coordinator_module, "HabitPredictor"),
            patch.object(coordinator_module, "EventLogger"),
        ):
            coordinator = LLMPresenceCoordinator(hass, entry)

        assert coordinator.notification_manager._enabled is False


class TestRoomTransitionEvents:
    """_check_room_transition fires events and records history."""

    @pytest.mark.asyncio
    async def test_first_observation_fires_nothing(self, tmp_path):
        hass = _make_hass()
        coordinator = _bare_coordinator(hass, tmp_path)

        await coordinator._check_room_transition("Alice", "bedroom", 0.9)

        hass.bus.async_fire.assert_not_called()

    @pytest.mark.asyncio
    async def test_room_change_fires_event_and_records_history(self, tmp_path):
        hass = _make_hass()
        coordinator = _bare_coordinator(hass, tmp_path)

        await coordinator._check_room_transition("Alice", "bedroom", 0.9)
        await coordinator._check_room_transition("Alice", "kitchen", 0.8)

        events = _fired(hass, EVENT_ROOM_CHANGED)
        assert len(events) == 1
        assert events[0]["entity_name"] == "Alice"
        assert events[0]["from_room"] == "bedroom"
        assert events[0]["to_room"] == "kitchen"
        assert events[0]["confidence"] == 0.8

        history = coordinator.history_tracker.get_recent_transitions("Alice")
        assert [(t["from_room"], t["to_room"]) for t in history] == [("bedroom", "kitchen")]

    @pytest.mark.asyncio
    async def test_leave_and_arrive_fire_events(self, tmp_path):
        hass = _make_hass()
        coordinator = _bare_coordinator(hass, tmp_path)

        await coordinator._check_room_transition("Alice", "office", 0.9)
        await coordinator._check_room_transition("Alice", "away", 0.95)
        await coordinator._check_room_transition("Alice", "living_room", 0.85)

        left = _fired(hass, EVENT_PERSON_LEFT)
        arrived = _fired(hass, EVENT_PERSON_ARRIVED)
        assert left == [{"entity_name": "Alice", "last_room": "office", "timestamp": left[0]["timestamp"]}]
        assert len(arrived) == 1
        assert arrived[0]["room"] == "living_room"
        assert _fired(hass, EVENT_ROOM_CHANGED) == []

    @pytest.mark.asyncio
    async def test_unknown_room_is_ignored(self, tmp_path):
        """An inconclusive detection must not report the person as having left."""
        hass = _make_hass()
        coordinator = _bare_coordinator(hass, tmp_path)

        await coordinator._check_room_transition("Alice", "office", 0.9)
        await coordinator._check_room_transition("Alice", "unknown", 0.2)
        await coordinator._check_room_transition("Alice", "office", 0.9)

        hass.bus.async_fire.assert_not_called()
        assert coordinator.history_tracker.get_recent_transitions("Alice") == []
        assert coordinator._previous_rooms["Alice"] == "office"


class TestHabitPersistence:
    """Learned habits are written to disk during normal operation."""

    @pytest.mark.asyncio
    async def test_saves_when_dirty_and_interval_elapsed(self, tmp_path):
        coordinator = _bare_coordinator(_make_hass(), tmp_path)
        coordinator.habit_predictor.learn_from_event("Alice", "office", 0.9)
        coordinator._habits_dirty = True

        await coordinator._async_maybe_save_habits()

        saved = json.loads((tmp_path / "roomer_learned_habits.json").read_text())
        assert "Alice" in saved["patterns"]
        assert coordinator._habits_dirty is False

    @pytest.mark.asyncio
    async def test_skips_save_when_not_dirty(self, tmp_path):
        coordinator = _bare_coordinator(_make_hass(), tmp_path)

        await coordinator._async_maybe_save_habits()

        assert not (tmp_path / "roomer_learned_habits.json").exists()

    @pytest.mark.asyncio
    async def test_skips_save_before_interval(self, tmp_path):
        import time

        coordinator = _bare_coordinator(_make_hass(), tmp_path)
        coordinator._habits_dirty = True
        coordinator._last_habit_save = time.monotonic()

        await coordinator._async_maybe_save_habits()

        assert not (tmp_path / "roomer_learned_habits.json").exists()
        assert coordinator._habits_dirty is True
        assert HABIT_SAVE_INTERVAL.total_seconds() > 0

    def test_save_state_writes_habits_and_history(self, tmp_path):
        coordinator = _bare_coordinator(_make_hass(), tmp_path)
        coordinator.habit_predictor.learn_from_event("Alice", "office", 0.9)
        coordinator.history_tracker.record_transition("Alice", "bedroom", "office", 0.9)

        coordinator.save_state()

        assert (tmp_path / "roomer_learned_habits.json").exists()
        history = json.loads((tmp_path / "roomer_history.json").read_text())
        assert len(history["transitions"]) == 1

    @pytest.mark.asyncio
    async def test_saves_state_on_homeassistant_stop(self):
        from homeassistant.const import EVENT_HOMEASSISTANT_STOP

        hass = _make_hass()
        entry = _make_entry()
        await _setup_entry(hass, entry)

        hass.bus.async_listen_once.assert_called_once()
        event_type, listener = hass.bus.async_listen_once.call_args.args
        assert event_type == EVENT_HOMEASSISTANT_STOP
        unload_callbacks = [c.args[0] for c in entry.async_on_unload.call_args_list]
        assert hass.bus.async_listen_once.return_value in unload_callbacks

        coordinator = hass.data[DOMAIN][entry.entry_id]
        await listener(MagicMock())
        coordinator.save_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_unload_saves_state(self):
        from custom_components.roomer import async_unload_entry

        hass = _make_hass()
        entry = _make_entry()
        coordinator = MagicMock()
        coordinator.provider.async_close = AsyncMock()
        hass.data[DOMAIN] = {entry.entry_id: coordinator}

        assert await async_unload_entry(hass, entry) is True

        coordinator.save_state.assert_called_once()
        assert entry.entry_id not in hass.data[DOMAIN]
