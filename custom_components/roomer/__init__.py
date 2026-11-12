"""Roomer integration for Home Assistant.

Uses local LLMs (Ollama) to intelligently deduce room presence
based on sensor data (lights, motion, media, device trackers).
Optionally uses vision models to identify specific people/pets.
"""

from __future__ import annotations

import asyncio
import logging
from functools import partial
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_CONFIDENCE_WEIGHTS,
    CONF_MAX_FILE_SIZE_MB,
    CONF_RETENTION_DAYS,
    CONF_ROOM_ENTITIES,
    CONF_URL,
    CONF_VISION_MODEL,
    DEFAULT_CONFIDENCE_WEIGHTS,
    DEFAULT_MAX_FILE_SIZE_MB,
    DEFAULT_RETENTION_DAYS,
    DEFAULT_VISION_MODEL,
    DOMAIN,
)
from .coordinator import LLMPresenceCoordinator
from .entity_hints import normalize_room_entities
from .event_logger import EventLogger
from .habits import ConfidenceCombiner, HabitPredictor
from .history import HistoryTracker
from .services import (  # noqa: F401 - schemas re-exported for backwards compatibility
    CLEANUP_STORAGE_SCHEMA,
    IDENTIFY_PERSON_SCHEMA,
    TRACKING_SCHEMA,
    async_setup_services,
)
from .vision import CameraTrackingController, VisionIdentifier

if TYPE_CHECKING:
    from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)

# Keep in step with LLMPresenceConfigFlow.VERSION
CONFIG_ENTRY_VERSION = 3

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up Roomer from YAML configuration."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Roomer from a config entry."""
    _LOGGER.info("Setting up Roomer integration")

    # Instantiate shared components (no global singletons)
    retention_days = entry.options.get(CONF_RETENTION_DAYS, entry.data.get(CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS))
    max_file_size_mb = entry.options.get(
        CONF_MAX_FILE_SIZE_MB, entry.data.get(CONF_MAX_FILE_SIZE_MB, DEFAULT_MAX_FILE_SIZE_MB)
    )
    # These read and create files in __init__, so build them off the event loop
    event_logger = await hass.async_add_executor_job(
        partial(EventLogger, retention_days=retention_days, max_file_size_mb=max_file_size_mb)
    )
    habit_predictor = await hass.async_add_executor_job(HabitPredictor)
    history_tracker = await hass.async_add_executor_job(HistoryTracker)
    confidence_weights = entry.options.get(
        CONF_CONFIDENCE_WEIGHTS, entry.data.get(CONF_CONFIDENCE_WEIGHTS, DEFAULT_CONFIDENCE_WEIGHTS)
    )
    confidence_combiner = ConfidenceCombiner(confidence_weights)

    coordinator = LLMPresenceCoordinator(
        hass,
        entry,
        event_logger=event_logger,
        habit_predictor=habit_predictor,
        confidence_combiner=confidence_combiner,
        history_tracker=history_tracker,
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator
    hass.data[DOMAIN]["event_logger"] = event_logger

    # Perform initial cleanup on startup
    _LOGGER.info("Performing initial storage cleanup on startup...")
    cleanup_result = await hass.async_add_executor_job(event_logger.cleanup)
    _LOGGER.info(
        "Startup cleanup complete: deleted %d events, kept %d, final size: %.1f MB",
        cleanup_result.get("total_deleted", 0),
        cleanup_result.get("total_kept", 0),
        cleanup_result.get("final_size_mb", 0.0),
    )

    # Schedule periodic cleanup (daily)
    from datetime import timedelta

    async def periodic_cleanup(now) -> None:
        """Perform periodic cleanup."""
        _LOGGER.info("Running periodic storage cleanup...")
        logger = hass.data[DOMAIN].get("event_logger")
        if logger:
            result = await hass.async_add_executor_job(logger.cleanup)
            _LOGGER.info(
                "Periodic cleanup complete: deleted %d events, kept %d, final size: %.1f MB",
                result.get("total_deleted", 0),
                result.get("total_kept", 0),
                result.get("final_size_mb", 0.0),
            )

    # Schedule daily cleanup (runs every 24 hours), cancelled when the entry unloads
    entry.async_on_unload(
        async_track_time_interval(
            hass,
            periodic_cleanup,
            timedelta(hours=24),
        )
    )
    _LOGGER.info("Scheduled daily periodic cleanup")

    # Initialize vision components
    ollama_url = entry.data.get(CONF_URL, "http://localhost:11434")
    vision_model = entry.data.get(CONF_VISION_MODEL, DEFAULT_VISION_MODEL)

    # Get known persons/pets from config
    persons = [p.get("name") for p in entry.data.get("persons", [])]
    pets = [p.get("name") for p in entry.data.get("pets", [])]

    vision_identifier = VisionIdentifier(
        ollama_url=ollama_url,
        vision_model=vision_model,
        known_persons=persons if persons else None,
        known_pets=pets if pets else None,
    )
    tracking_controller = CameraTrackingController(hass)

    # Store vision components
    hass.data[DOMAIN]["vision_identifier"] = vision_identifier
    hass.data[DOMAIN]["tracking_controller"] = tracking_controller

    # Register services
    await async_setup_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload when options change so they take effect without a restart
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    # Home Assistant does not unload entries on shutdown, so save state on stop too
    async def _async_save_on_stop(event: Event) -> None:
        await asyncio.to_thread(coordinator.save_state)

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_save_on_stop))

    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate an older config entry.

    Version 3 normalises ``room_entities``: every mapped entity gets a
    ``weight`` (its share of the evidence for that room) and a ``detects``
    (person, animal or any). Single-room mappings keep working unchanged.
    """
    if entry.version > CONFIG_ENTRY_VERSION:
        # Created by a newer Roomer than this one
        return False

    if entry.version < CONFIG_ENTRY_VERSION:
        data = dict(entry.data)
        options = dict(entry.options)
        if CONF_ROOM_ENTITIES in data:
            data[CONF_ROOM_ENTITIES] = normalize_room_entities(data[CONF_ROOM_ENTITIES])
        if CONF_ROOM_ENTITIES in options:
            options[CONF_ROOM_ENTITIES] = normalize_room_entities(options[CONF_ROOM_ENTITIES])
        hass.config_entries.async_update_entry(entry, data=data, options=options, version=CONFIG_ENTRY_VERSION)
        _LOGGER.info("Migrated Roomer config entry to version %s", CONFIG_ENTRY_VERSION)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading Roomer integration")

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator = hass.data[DOMAIN].get(entry.entry_id)
        if coordinator:
            # Persist learned habits and movement history before dropping them
            await asyncio.to_thread(coordinator.save_state)
            await coordinator.provider.async_close()
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry.

    Goes through the config entries manager so the entry's async_on_unload
    callbacks (update listener, periodic cleanup) run before setup again.
    """
    await hass.config_entries.async_reload(entry.entry_id)
