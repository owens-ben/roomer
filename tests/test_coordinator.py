"""Tests for the Roomer coordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.roomer.const import (
    CONF_PERSON_DEVICES,
    CONF_ROOM_ENTITIES,
    ENTITY_HINT_MEDIA,
    ENTITY_HINT_MOTION,
)


class TestCoordinatorHelpers:
    """Test coordinator helper methods without full HA setup."""

    def test_is_entity_active_on(self):
        """Test entity active detection for 'on' state."""
        from custom_components.roomer.coordinator import LLMPresenceCoordinator

        with patch.object(LLMPresenceCoordinator, "__init__", lambda x, y, z: None):
            coordinator = LLMPresenceCoordinator.__new__(LLMPresenceCoordinator)

            assert coordinator._is_entity_active("light.test", "on", "light") is True
            assert coordinator._is_entity_active("light.test", "off", "light") is False

    def test_is_entity_active_motion(self):
        """Test entity active detection for motion sensors."""
        from custom_components.roomer.coordinator import LLMPresenceCoordinator

        with patch.object(LLMPresenceCoordinator, "__init__", lambda x, y, z: None):
            coordinator = LLMPresenceCoordinator.__new__(LLMPresenceCoordinator)

            assert coordinator._is_entity_active("binary_sensor.motion", "on", ENTITY_HINT_MOTION) is True
            assert coordinator._is_entity_active("binary_sensor.motion", "off", ENTITY_HINT_MOTION) is False

    def test_is_entity_active_media_playing(self):
        """Test entity active detection for media players."""
        from custom_components.roomer.coordinator import LLMPresenceCoordinator

        with patch.object(LLMPresenceCoordinator, "__init__", lambda x, y, z: None):
            coordinator = LLMPresenceCoordinator.__new__(LLMPresenceCoordinator)

            assert coordinator._is_entity_active("media_player.tv", "playing", ENTITY_HINT_MEDIA) is True
            assert coordinator._is_entity_active("media_player.tv", "paused", ENTITY_HINT_MEDIA) is True
            assert coordinator._is_entity_active("media_player.tv", "off", ENTITY_HINT_MEDIA) is False
            assert coordinator._is_entity_active("media_player.tv", "idle", ENTITY_HINT_MEDIA) is False

    def test_is_entity_active_device_tracker(self):
        """Test entity active detection for device trackers."""
        from custom_components.roomer.coordinator import LLMPresenceCoordinator

        with patch.object(LLMPresenceCoordinator, "__init__", lambda x, y, z: None):
            coordinator = LLMPresenceCoordinator.__new__(LLMPresenceCoordinator)

            assert coordinator._is_entity_active("device_tracker.phone", "home", "presence") is True
            assert coordinator._is_entity_active("device_tracker.phone", "not_home", "presence") is False


class TestCoordinatorRoomEntityMapping:
    """Test room-entity mapping functionality."""

    def test_find_entity_room(self, mock_hass, mock_config_entry):
        """Test finding which room an entity belongs to."""
        from custom_components.roomer.coordinator import LLMPresenceCoordinator

        with patch.object(LLMPresenceCoordinator, "__init__", lambda x, y, z: None):
            coordinator = LLMPresenceCoordinator.__new__(LLMPresenceCoordinator)
            coordinator.room_entities = mock_config_entry.data[CONF_ROOM_ENTITIES]

            assert coordinator._find_entity_room("switch.office_pc") == "office"
            assert coordinator._find_entity_room("media_player.living_room_tv") == "living_room"
            assert coordinator._find_entity_room("unknown.entity") is None

    def test_get_active_indicators(self, mock_hass, mock_config_entry):
        """Test getting active indicators from room entities."""
        from custom_components.roomer.coordinator import LLMPresenceCoordinator

        with patch.object(LLMPresenceCoordinator, "__init__", lambda x, y, z: None):
            coordinator = LLMPresenceCoordinator.__new__(LLMPresenceCoordinator)
            coordinator.room_entities = mock_config_entry.data[CONF_ROOM_ENTITIES]
            coordinator.hass = mock_hass

            # Mock _get_entity_state and _is_entity_active
            def mock_get_state(entity_id, context):
                states = {
                    "switch.office_pc": "on",
                    "binary_sensor.office_motion": "off",
                    "media_player.living_room_tv": "playing",
                }
                return states.get(entity_id, "unknown")

            coordinator._get_entity_state = mock_get_state

            context = {}
            active = coordinator._get_active_indicators(context)

            # Should have PC (on) and TV (playing), not motion (off)
            entity_ids = [i["entity_id"] for i in active]
            assert "switch.office_pc" in entity_ids
            assert "media_player.living_room_tv" in entity_ids
            assert "binary_sensor.office_motion" not in entity_ids


class TestCoordinatorPersonDevices:
    """Test person-device ownership mapping."""

    def test_get_person_indicators_with_owned_device(self, mock_hass, mock_config_entry):
        """Test that person's owned devices are included in indicators."""
        from custom_components.roomer.coordinator import LLMPresenceCoordinator

        with patch.object(LLMPresenceCoordinator, "__init__", lambda x, y, z: None):
            coordinator = LLMPresenceCoordinator.__new__(LLMPresenceCoordinator)
            coordinator.room_entities = mock_config_entry.data[CONF_ROOM_ENTITIES]
            coordinator.person_devices = mock_config_entry.data[CONF_PERSON_DEVICES]
            coordinator.hass = mock_hass

            # Mock methods
            def mock_get_state(entity_id, context):
                return "on" if entity_id == "switch.alice_pc" else "off"

            def mock_find_rooms(entity_id):
                return [("office", 1.0)] if "pc" in entity_id else []

            coordinator._get_entity_state = mock_get_state
            coordinator._find_entity_rooms = mock_find_rooms

            all_indicators = []
            context = {}

            indicators = coordinator._get_person_indicators("Alice", all_indicators, context)

            # Alice's PC should be in indicators with owned_by field
            alice_pc_indicator = next((i for i in indicators if i.get("entity_id") == "switch.alice_pc"), None)
            assert alice_pc_indicator is not None
            assert alice_pc_indicator.get("owned_by") == "Alice"
            assert alice_pc_indicator.get("room") == "office"

    def test_get_person_indicators_without_owned_device(self, mock_hass, mock_config_entry):
        """Test indicators for person without device ownership configured."""
        from custom_components.roomer.coordinator import LLMPresenceCoordinator

        with patch.object(LLMPresenceCoordinator, "__init__", lambda x, y, z: None):
            coordinator = LLMPresenceCoordinator.__new__(LLMPresenceCoordinator)
            coordinator.room_entities = mock_config_entry.data[CONF_ROOM_ENTITIES]
            coordinator.person_devices = mock_config_entry.data[CONF_PERSON_DEVICES]
            coordinator.hass = mock_hass

            coordinator._get_entity_state = lambda e, c: "off"
            coordinator._find_entity_room = lambda e: None

            all_indicators = [
                {"entity_id": "binary_sensor.motion", "hint_type": "motion", "room": "office", "state": "on"}
            ]
            context = {}

            # Bob doesn't have device ownership configured
            indicators = coordinator._get_person_indicators("Bob", all_indicators, context)

            # Should still get general indicators
            assert len(indicators) >= 1
            assert indicators[0]["entity_id"] == "binary_sensor.motion"


class TestCoordinatorRoomTransition:
    """Test room transition detection."""

    @pytest.mark.asyncio
    async def test_check_room_transition_logs_movement(self, mock_hass, mock_config_entry):
        """Test that room transitions are detected."""
        from custom_components.roomer.coordinator import LLMPresenceCoordinator

        with patch.object(LLMPresenceCoordinator, "__init__", lambda x, y, z: None):
            coordinator = LLMPresenceCoordinator.__new__(LLMPresenceCoordinator)
            coordinator._previous_rooms = {"Alice": "bedroom"}
            coordinator.event_logger = MagicMock()
            coordinator.event_logger.async_log_room_transition = AsyncMock()
            coordinator.history_tracker = MagicMock()
            coordinator.notification_manager = MagicMock()

            # Move Alice to office
            await coordinator._check_room_transition("Alice", "office", 0.9)

            # Should have logged the transition
            coordinator.event_logger.async_log_room_transition.assert_called_once_with(
                entity_name="Alice",
                from_room="bedroom",
                to_room="office",
                confidence=0.9,
            )

            # Previous room should be updated
            assert coordinator._previous_rooms["Alice"] == "office"

    @pytest.mark.asyncio
    async def test_check_room_transition_same_room_no_log(self, mock_hass, mock_config_entry):
        """Test that staying in same room doesn't log transition."""
        from custom_components.roomer.coordinator import LLMPresenceCoordinator

        with patch.object(LLMPresenceCoordinator, "__init__", lambda x, y, z: None):
            coordinator = LLMPresenceCoordinator.__new__(LLMPresenceCoordinator)
            coordinator._previous_rooms = {"Alice": "office"}
            coordinator.event_logger = MagicMock()
            coordinator.event_logger.async_log_room_transition = AsyncMock()
            coordinator.history_tracker = MagicMock()
            coordinator.notification_manager = MagicMock()

            # Alice stays in office
            await coordinator._check_room_transition("Alice", "office", 0.9)

            # Should NOT have logged a transition
            coordinator.event_logger.async_log_room_transition.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_room_transition_to_unknown_no_log(self, mock_hass, mock_config_entry):
        """Test that transition to 'unknown' doesn't log."""
        from custom_components.roomer.coordinator import LLMPresenceCoordinator

        with patch.object(LLMPresenceCoordinator, "__init__", lambda x, y, z: None):
            coordinator = LLMPresenceCoordinator.__new__(LLMPresenceCoordinator)
            coordinator._previous_rooms = {"Alice": "office"}
            coordinator.event_logger = MagicMock()
            coordinator.event_logger.async_log_room_transition = AsyncMock()
            coordinator.history_tracker = MagicMock()
            coordinator.notification_manager = MagicMock()

            # Unknown room result
            await coordinator._check_room_transition("Alice", "unknown", 0.3)

            # Should NOT log transition to unknown
            coordinator.event_logger.async_log_room_transition.assert_not_called()
