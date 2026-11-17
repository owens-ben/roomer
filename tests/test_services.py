"""
Tests for Home Assistant services (TDD).

These tests verify Roomer services for manual control and data access.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestServiceRegistration:
    """Test service registration."""

    def test_services_module_exists(self):
        """Services module should exist."""
        from custom_components.roomer import services

        assert services is not None

    def test_service_constants_defined(self):
        """Service names should be defined as constants."""
        from custom_components.roomer.services import (
            SERVICE_CLEAR_HISTORY,
            SERVICE_CORRECT_ROOM,
            SERVICE_GET_HISTORY,
            SERVICE_GET_PATTERNS,
            SERVICE_REFRESH,
        )

        assert SERVICE_REFRESH == "refresh"
        assert SERVICE_CORRECT_ROOM == "correct_room"
        assert SERVICE_GET_HISTORY == "get_history"
        assert SERVICE_CLEAR_HISTORY == "clear_history"
        assert SERVICE_GET_PATTERNS == "get_patterns"


class TestRefreshService:
    """Test the refresh service."""

    @pytest.mark.asyncio
    async def test_refresh_triggers_update(self):
        """Refresh should trigger coordinator update."""
        from custom_components.roomer.services import async_handle_refresh

        mock_coordinator = MagicMock()
        mock_coordinator.async_request_refresh = AsyncMock()

        mock_hass = MagicMock()
        mock_hass.data = {"roomer": {"coordinator": mock_coordinator}}

        call = MagicMock()
        call.data = {}

        await async_handle_refresh(mock_hass, call)

        mock_coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_with_entity_filter(self):
        """Refresh should support entity filter."""
        from custom_components.roomer.services import async_handle_refresh

        mock_coordinator = MagicMock()
        mock_coordinator.async_request_refresh = AsyncMock()

        mock_hass = MagicMock()
        mock_hass.data = {"roomer": {"coordinator": mock_coordinator}}

        call = MagicMock()
        call.data = {"entity_id": "sensor.ben_room"}

        await async_handle_refresh(mock_hass, call)

        # Should still trigger refresh
        mock_coordinator.async_request_refresh.assert_called_once()


class TestCorrectRoomService:
    """Test the correct_room service (see test_correct_room.py for name resolution and validation)."""

    @pytest.mark.asyncio
    async def test_correct_room_updates_state(self):
        """Correct room should learn and update entity state (no coordinator: legacy name)."""
        from custom_components.roomer.services import async_handle_correct_room

        mock_hass = MagicMock()
        mock_hass.data = {}
        mock_hass.states.async_set = MagicMock()
        mock_hass.async_add_executor_job = AsyncMock()

        mock_predictor = MagicMock()
        mock_predictor.learn_from_event = MagicMock()

        with patch("custom_components.roomer.services.get_habit_predictor", return_value=mock_predictor):
            call = MagicMock()
            call.data = {
                "entity_id": "sensor.ben_room",
                "room": "office",
            }

            await async_handle_correct_room(mock_hass, call)

            mock_predictor.learn_from_event.assert_called_once()
            assert mock_predictor.learn_from_event.call_args.kwargs["entity_name"] == "Ben"

    @pytest.mark.asyncio
    async def test_correct_room_rejects_invalid_room(self):
        """An unknown room raises a clear ServiceValidationError."""
        from homeassistant.exceptions import ServiceValidationError

        from custom_components.roomer.services import async_handle_correct_room

        mock_hass = MagicMock()
        mock_hass.data = {}

        call = MagicMock()
        call.data = {
            "entity_id": "sensor.ben_room",
            "room": "invalid_room_xyz",
        }

        with pytest.raises(ServiceValidationError, match="invalid_room_xyz"):
            await async_handle_correct_room(mock_hass, call)


class TestGetHistoryService:
    """Test the get_history service."""

    @pytest.mark.asyncio
    async def test_get_history_returns_data(self):
        """Get history should return transition data."""
        from custom_components.roomer.services import async_handle_get_history

        mock_tracker = MagicMock()
        mock_tracker.get_recent_transitions.return_value = [
            {"from_room": "bedroom", "to_room": "kitchen", "timestamp": "2025-01-30T08:00:00"}
        ]

        mock_hass = MagicMock()

        with patch("custom_components.roomer.services.get_history_tracker", return_value=mock_tracker):
            call = MagicMock()
            call.data = {"entity_name": "Ben", "limit": 10}

            result = await async_handle_get_history(mock_hass, call)

            assert len(result) == 1
            assert result[0]["to_room"] == "kitchen"

    @pytest.mark.asyncio
    async def test_get_history_respects_limit(self):
        """Get history should respect limit parameter."""
        from custom_components.roomer.services import async_handle_get_history

        mock_tracker = MagicMock()
        mock_tracker.get_recent_transitions.return_value = []

        mock_hass = MagicMock()

        with patch("custom_components.roomer.services.get_history_tracker", return_value=mock_tracker):
            call = MagicMock()
            call.data = {"entity_name": "Ben", "limit": 5}

            await async_handle_get_history(mock_hass, call)

            mock_tracker.get_recent_transitions.assert_called_with("Ben", limit=5)


class TestClearHistoryService:
    """Test the clear_history service."""

    @pytest.mark.asyncio
    async def test_clear_history_for_entity(self):
        """Clear history should clear for specific entity."""
        from custom_components.roomer.services import async_handle_clear_history

        mock_tracker = MagicMock()
        mock_tracker.clear_history = MagicMock()

        mock_hass = MagicMock()

        with patch("custom_components.roomer.services.get_history_tracker", return_value=mock_tracker):
            call = MagicMock()
            call.data = {"entity_name": "Ben"}

            await async_handle_clear_history(mock_hass, call)

            mock_tracker.clear_history.assert_called_with("Ben")

    @pytest.mark.asyncio
    async def test_clear_history_all(self):
        """Clear history should clear all when no entity specified."""
        from custom_components.roomer.services import async_handle_clear_history

        mock_tracker = MagicMock()
        mock_tracker.clear_history = MagicMock()

        mock_hass = MagicMock()

        with patch("custom_components.roomer.services.get_history_tracker", return_value=mock_tracker):
            call = MagicMock()
            call.data = {}

            await async_handle_clear_history(mock_hass, call)

            mock_tracker.clear_history.assert_called_with(None)


class TestGetPatternsService:
    """Test the get_patterns service."""

    @pytest.mark.asyncio
    async def test_get_patterns_returns_data(self):
        """Get patterns should return detected patterns."""
        from custom_components.roomer.services import async_handle_get_patterns

        mock_tracker = MagicMock()
        mock_tracker.detect_patterns.return_value = [
            {"type": "morning_routine", "description": "Usually in kitchen in the morning"}
        ]

        mock_hass = MagicMock()

        with patch("custom_components.roomer.services.get_history_tracker", return_value=mock_tracker):
            call = MagicMock()
            call.data = {"entity_name": "Ben"}

            result = await async_handle_get_patterns(mock_hass, call)

            assert len(result) == 1
            assert result[0]["type"] == "morning_routine"


class TestServiceSchemas:
    """Test service schema validation."""

    def test_correct_room_schema(self):
        """Correct room schema should require entity_id and room."""
        import voluptuous as vol

        from custom_components.roomer.services import CORRECT_ROOM_SCHEMA

        # Valid data should pass
        valid_data = {"entity_id": "sensor.ben_room", "room": "office"}
        CORRECT_ROOM_SCHEMA(valid_data)

        # Missing room should fail
        with pytest.raises(vol.Invalid):
            CORRECT_ROOM_SCHEMA({"entity_id": "sensor.ben_room"})

    def test_get_history_schema(self):
        """Get history schema should require entity_name."""

        from custom_components.roomer.services import GET_HISTORY_SCHEMA

        # Valid data should pass
        valid_data = {"entity_name": "Ben"}
        GET_HISTORY_SCHEMA(valid_data)

        # With optional limit
        GET_HISTORY_SCHEMA({"entity_name": "Ben", "limit": 20})
