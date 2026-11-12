"""Tests for Roomer integration setup."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.roomer.const import (
    CONF_MAX_FILE_SIZE_MB,
    CONF_RETENTION_DAYS,
    CONF_URL,
    CONF_VISION_MODEL,
    DEFAULT_MAX_FILE_SIZE_MB,
    DEFAULT_RETENTION_DAYS,
    DEFAULT_VISION_MODEL,
    DOMAIN,
)


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.data = {}
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    hass.services = MagicMock()
    hass.services.has_service = MagicMock(return_value=False)
    hass.services.async_register = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.helpers = MagicMock()
    hass.helpers.event = MagicMock()
    hass.helpers.event.async_track_time_interval = MagicMock()
    return hass


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {
        CONF_URL: "http://localhost:11434",
        CONF_VISION_MODEL: DEFAULT_VISION_MODEL,
        CONF_RETENTION_DAYS: DEFAULT_RETENTION_DAYS,
        CONF_MAX_FILE_SIZE_MB: DEFAULT_MAX_FILE_SIZE_MB,
        "persons": [{"name": "Alice"}, {"name": "Bob"}],
        "pets": [{"name": "Whiskers"}],
    }
    entry.options = {}
    return entry


def _make_mock_event_logger(cleanup_return=None):
    """Create a mock EventLogger with standard defaults."""
    mock = MagicMock()
    mock.cleanup = MagicMock(
        return_value=cleanup_return
        or {
            "total_deleted": 0,
            "total_kept": 100,
            "final_size_mb": 5.0,
        }
    )
    return mock


class TestAsyncSetup:
    """Test async_setup function."""

    @pytest.mark.asyncio
    async def test_async_setup_creates_domain_data(self, mock_hass):
        """Test that async_setup initializes domain data."""
        from custom_components.roomer import async_setup

        result = await async_setup(mock_hass, {})

        assert result is True
        assert DOMAIN in mock_hass.data


class TestAsyncSetupEntry:
    """Test async_setup_entry function."""

    @pytest.mark.asyncio
    async def test_setup_entry_creates_coordinator(self, mock_hass, mock_config_entry):
        """Test that setup creates coordinator."""
        from custom_components.roomer import async_setup_entry

        with patch("custom_components.roomer.LLMPresenceCoordinator") as mock_coord_class:
            mock_coordinator = MagicMock()
            mock_coordinator.async_config_entry_first_refresh = AsyncMock()
            mock_coord_class.return_value = mock_coordinator

            with patch("custom_components.roomer.EventLogger") as mock_logger_class:
                mock_logger_class.return_value = _make_mock_event_logger()

                with patch("custom_components.roomer.VisionIdentifier"):
                    with patch("custom_components.roomer.CameraTrackingController"):
                        result = await async_setup_entry(mock_hass, mock_config_entry)

        assert result is True
        assert mock_config_entry.entry_id in mock_hass.data[DOMAIN]

    @pytest.mark.asyncio
    async def test_setup_entry_registers_services(self, mock_hass, mock_config_entry):
        """Test that setup registers services."""
        from custom_components.roomer import async_setup_entry

        with patch("custom_components.roomer.LLMPresenceCoordinator") as mock_coord_class:
            mock_coordinator = MagicMock()
            mock_coordinator.async_config_entry_first_refresh = AsyncMock()
            mock_coord_class.return_value = mock_coordinator

            with patch("custom_components.roomer.EventLogger") as mock_logger_class:
                mock_logger_class.return_value = _make_mock_event_logger()

                with patch("custom_components.roomer.VisionIdentifier"):
                    with patch("custom_components.roomer.CameraTrackingController"):
                        await async_setup_entry(mock_hass, mock_config_entry)

        # Should have called async_register multiple times for services
        assert mock_hass.services.async_register.called

    @pytest.mark.asyncio
    async def test_setup_entry_schedules_cleanup(self, mock_hass, mock_config_entry):
        """Test that setup schedules periodic cleanup."""
        from custom_components.roomer import async_setup_entry

        with patch("custom_components.roomer.LLMPresenceCoordinator") as mock_coord_class:
            mock_coordinator = MagicMock()
            mock_coordinator.async_config_entry_first_refresh = AsyncMock()
            mock_coord_class.return_value = mock_coordinator

            with patch("custom_components.roomer.EventLogger") as mock_logger_class:
                mock_logger_class.return_value = _make_mock_event_logger()

                with patch("custom_components.roomer.VisionIdentifier"):
                    with patch("custom_components.roomer.CameraTrackingController"):
                        with patch("custom_components.roomer.async_track_time_interval") as mock_track:
                            await async_setup_entry(mock_hass, mock_config_entry)

                            # Should schedule daily cleanup
                            mock_track.assert_called_once()

    @pytest.mark.asyncio
    async def test_setup_entry_initializes_vision(self, mock_hass, mock_config_entry):
        """Test that setup initializes vision components."""
        from custom_components.roomer import async_setup_entry

        with patch("custom_components.roomer.LLMPresenceCoordinator") as mock_coord_class:
            mock_coordinator = MagicMock()
            mock_coordinator.async_config_entry_first_refresh = AsyncMock()
            mock_coord_class.return_value = mock_coordinator

            with patch("custom_components.roomer.EventLogger") as mock_logger_class:
                mock_logger_class.return_value = _make_mock_event_logger()

                with patch("custom_components.roomer.VisionIdentifier") as mock_vision:
                    with patch("custom_components.roomer.CameraTrackingController"):
                        await async_setup_entry(mock_hass, mock_config_entry)

                        # Vision identifier should be created with known persons/pets
                        mock_vision.assert_called_once()
                        call_kwargs = mock_vision.call_args[1]
                        assert call_kwargs["known_persons"] == ["Alice", "Bob"]
                        assert call_kwargs["known_pets"] == ["Whiskers"]


class TestAsyncUnloadEntry:
    """Test async_unload_entry function."""

    @pytest.mark.asyncio
    async def test_unload_entry_success(self, mock_hass, mock_config_entry):
        """Test successful unload."""
        from custom_components.roomer import async_unload_entry

        # Setup data first - coordinator mock needs provider.async_close as AsyncMock
        mock_coordinator = MagicMock()
        mock_coordinator.provider = MagicMock()
        mock_coordinator.provider.async_close = AsyncMock()
        mock_hass.data[DOMAIN] = {mock_config_entry.entry_id: mock_coordinator}

        result = await async_unload_entry(mock_hass, mock_config_entry)

        assert result is True
        assert mock_config_entry.entry_id not in mock_hass.data[DOMAIN]

    @pytest.mark.asyncio
    async def test_unload_entry_platforms(self, mock_hass, mock_config_entry):
        """Test that platforms are unloaded."""
        from custom_components.roomer import PLATFORMS, async_unload_entry

        mock_coordinator = MagicMock()
        mock_coordinator.provider = MagicMock()
        mock_coordinator.provider.async_close = AsyncMock()
        mock_hass.data[DOMAIN] = {mock_config_entry.entry_id: mock_coordinator}

        await async_unload_entry(mock_hass, mock_config_entry)

        mock_hass.config_entries.async_unload_platforms.assert_called_once_with(mock_config_entry, PLATFORMS)


class TestAsyncReloadEntry:
    """Test async_reload_entry function."""

    @pytest.mark.asyncio
    async def test_reload_entry(self, mock_hass, mock_config_entry):
        """Test that reload goes through the config entries manager.

        A manual unload + setup would skip the entry's async_on_unload callbacks
        and stack a new update listener on every options change.
        """
        from custom_components.roomer import async_reload_entry

        mock_hass.config_entries.async_reload = AsyncMock(return_value=True)

        await async_reload_entry(mock_hass, mock_config_entry)

        mock_hass.config_entries.async_reload.assert_called_once_with(mock_config_entry.entry_id)


class TestServiceHandlers:
    """Test service handlers."""

    @pytest.mark.asyncio
    async def test_identify_person_service(self, mock_hass, mock_config_entry):
        """Test identify_person service handler."""
        from custom_components.roomer import async_setup_entry

        captured_handlers = {}

        def capture_register(domain, service, handler, schema=None, supports_response=None):
            captured_handlers[service] = handler

        mock_hass.services.async_register = capture_register

        with patch("custom_components.roomer.LLMPresenceCoordinator") as mock_coord_class:
            mock_coordinator = MagicMock()
            mock_coordinator.async_config_entry_first_refresh = AsyncMock()
            mock_coord_class.return_value = mock_coordinator

            with patch("custom_components.roomer.EventLogger") as mock_logger_class:
                mock_logger_class.return_value = _make_mock_event_logger()

                with patch("custom_components.roomer.VisionIdentifier") as mock_vision_class:
                    mock_vision = MagicMock()
                    mock_vision.identify_from_camera = AsyncMock(
                        return_value={
                            "success": True,
                            "identified": "Alice",
                            "confidence": "high",
                        }
                    )
                    mock_vision_class.return_value = mock_vision

                    with patch("custom_components.roomer.CameraTrackingController"):
                        await async_setup_entry(mock_hass, mock_config_entry)

        # Verify identify_person service was registered
        assert "identify_person" in captured_handlers

    @pytest.mark.asyncio
    async def test_cleanup_storage_service(self, mock_hass, mock_config_entry):
        """Test cleanup_storage service handler."""
        from custom_components.roomer import async_setup_entry

        captured_handlers = {}

        def capture_register(domain, service, handler, schema=None, supports_response=None):
            captured_handlers[service] = handler

        mock_hass.services.async_register = capture_register
        mock_hass.bus = MagicMock()
        mock_hass.bus.async_fire = MagicMock()

        mock_event_logger = _make_mock_event_logger(
            {
                "deleted_by_time": 5,
                "deleted_by_size": 0,
                "total_deleted": 5,
                "total_kept": 95,
                "final_size_mb": 4.5,
            }
        )

        with patch("custom_components.roomer.LLMPresenceCoordinator") as mock_coord_class:
            mock_coordinator = MagicMock()
            mock_coordinator.async_config_entry_first_refresh = AsyncMock()
            mock_coord_class.return_value = mock_coordinator

            with patch("custom_components.roomer.EventLogger") as mock_logger_class:
                mock_logger_class.return_value = mock_event_logger

                with patch("custom_components.roomer.VisionIdentifier"):
                    with patch("custom_components.roomer.CameraTrackingController"):
                        await async_setup_entry(mock_hass, mock_config_entry)

        # Verify cleanup_storage service was registered
        assert "cleanup_storage" in captured_handlers

        # Call the handler
        mock_call = MagicMock()
        mock_call.data = {}

        result = await captured_handlers["cleanup_storage"](mock_call)

        assert result["success"] is True
        assert result["total_deleted"] == 5


class TestServiceSchemas:
    """Test service schemas."""

    def test_identify_person_schema(self):
        """Test identify_person schema validation."""

        from custom_components.roomer import IDENTIFY_PERSON_SCHEMA

        # Valid input
        valid_data = {
            "camera_entity_id": "camera.living_room",
            "detection_type": "person",
        }

        result = IDENTIFY_PERSON_SCHEMA(valid_data)
        assert result["camera_entity_id"] == "camera.living_room"
        assert result["detection_type"] == "person"

        # Default detection_type
        minimal_data = {"camera_entity_id": "camera.living_room"}
        result = IDENTIFY_PERSON_SCHEMA(minimal_data)
        assert result["detection_type"] == "person"

    def test_tracking_schema(self):
        """Test tracking schema validation."""
        from custom_components.roomer import TRACKING_SCHEMA

        valid_data = {"camera_name": "living_room_camera"}

        result = TRACKING_SCHEMA(valid_data)
        assert result["camera_name"] == "living_room_camera"

    def test_cleanup_storage_schema(self):
        """Test cleanup_storage schema validation."""
        from custom_components.roomer import CLEANUP_STORAGE_SCHEMA

        # Optional parameters
        valid_data = {
            "retention_days": 14,
            "max_file_size_mb": 50.0,
        }

        result = CLEANUP_STORAGE_SCHEMA(valid_data)
        assert result["retention_days"] == 14
        assert result["max_file_size_mb"] == 50.0

        # Empty is valid (all optional)
        result = CLEANUP_STORAGE_SCHEMA({})
        assert result == {}


class TestPlatforms:
    """Test platform configuration."""

    def test_platforms_list(self):
        """Test that correct platforms are defined."""
        from homeassistant.const import Platform

        from custom_components.roomer import PLATFORMS

        assert Platform.SENSOR in PLATFORMS
        assert Platform.BINARY_SENSOR in PLATFORMS
        assert len(PLATFORMS) == 2
