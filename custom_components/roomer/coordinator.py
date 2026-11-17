"""Data update coordinator for Roomer."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Collection
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CONFIDENCE_WEIGHTS,
    CONF_LEARNING_ENABLED,
    CONF_MODEL,
    CONF_NOTIFICATIONS_ENABLED,
    CONF_PERSON_DEVICES,
    CONF_PERSONS,
    CONF_PETS,
    CONF_POLL_INTERVAL,
    CONF_PROVIDER,
    CONF_ROOM_AREAS,
    CONF_ROOM_ENTITIES,
    CONF_ROOMS,
    CONF_TIMEOUT,
    CONF_URL,
    DEFAULT_CONFIDENCE_WEIGHTS,
    DEFAULT_LEARNING_ENABLED,
    DEFAULT_MODEL,
    DEFAULT_NOTIFICATIONS_ENABLED,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PROVIDER,
    DEFAULT_TIMEOUT,
    DEFAULT_URL,
    DETECTS_ANIMAL,
    DETECTS_PERSON,
    DEVICE_TRACKER_AWAY_CONFIDENCE,
    DEVICE_TRACKER_HOME,
    DEVICE_TRACKER_NOT_HOME,
    DEVICE_TRACKER_UNAVAILABLE,
    DOMAIN,
    ENTITY_HINT_COMPUTER,
    ENTITY_HINT_MEDIA,
    HABIT_SAVE_INTERVAL,
    PRIOR_INDICATOR,
    PRIOR_MAX_CONFIDENCE,
    ROOM_AWAY,
    ROOM_UNKNOWN,
    SOURCE_MANUAL,
    SOURCE_PRIOR,
    SOURCE_SENSOR,
    SOURCE_STICKY,
    STICKY_BASE_MIN,
    STICKY_HALF_LIFE,
    STICKY_MAX_AGE,
    STICKY_MAX_CONFIDENCE,
    STICKY_MIN_CONFIDENCE,
    STRONG_CLUE_MIN_CONFIDENCE,
    VALID_ROOMS,
)
from .device_presence import DeviceRoomLocator, seen_since_away
from .entity_hints import guess_detects, normalize_room_entities
from .event_logger import EventLogger
from .habits import ConfidenceCombiner, HabitPredictor
from .history import HistoryTracker
from .notifications import NotificationManager
from .providers import get_provider
from .providers.base import PresenceGuess

_LOGGER = logging.getLogger(__name__)


def _norm(text: str) -> str:
    """Lowercase and drop everything but letters and digits, to compare room and area names."""
    return "".join(c for c in text.lower() if c.isalnum())


class DeviceTrackerHelper:
    """Helper class for device tracker integration."""

    def is_person_home(self, hass: HomeAssistant, device_tracker_id: str) -> bool | None:
        """Check if a single device tracker indicates person is home.

        Returns:
            True if home, False if away, None if unavailable/unknown
        """
        state = hass.states.get(device_tracker_id)
        if not state:
            return None

        state_value = state.state.lower()

        if state_value in (DEVICE_TRACKER_UNAVAILABLE, "unknown"):
            return None

        # "home" or zone names indicate presence
        if state_value == DEVICE_TRACKER_HOME:
            return True

        # "not_home" indicates away
        if state_value == DEVICE_TRACKER_NOT_HOME:
            return False

        # Any other zone name (e.g., "work", "school") means not at home
        # but we return True only for "home"
        return False

    def is_person_home_any(self, hass: HomeAssistant, device_tracker_ids: list[str]) -> bool | None:
        """Check if any device tracker indicates person is home.

        Returns True if ANY tracker shows home.
        Returns False if ALL trackers show away.
        Returns None if all trackers are unavailable.
        """
        if not device_tracker_ids:
            return None

        has_valid_state = False

        for tracker_id in device_tracker_ids:
            result = self.is_person_home(hass, tracker_id)
            if result is True:
                return True
            if result is False:
                has_valid_state = True

        # If we had at least one valid "not_home", return False
        if has_valid_state:
            return False

        # All trackers unavailable
        return None

    def get_away_confidence(self) -> float:
        """Get confidence level for device tracker based away detection."""
        return DEVICE_TRACKER_AWAY_CONFIDENCE

    def check_person_device_trackers(
        self,
        hass: HomeAssistant,
        person_name: str,
        person_devices: dict[str, list[str]],
        exclude: Collection[str] = (),
    ) -> tuple[bool | None, list[str]]:
        """Check all device trackers for a person.

        Trackers in ``exclude`` are skipped, e.g. room-level trackers whose
        state is a room name rather than home/not_home.

        Returns:
            (is_home, list_of_tracker_ids_checked)
        """
        # Get device trackers from person_devices config
        devices = person_devices.get(person_name, [])

        # Filter to only device_tracker entities
        trackers = [d for d in devices if d.startswith("device_tracker.") and d not in exclude]

        if not trackers:
            return None, []

        is_home = self.is_person_home_any(hass, trackers)
        return is_home, trackers


class LLMPresenceCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to manage LLM presence detection."""

    @staticmethod
    def _get_config(entry: ConfigEntry, key: str, default: Any = None) -> Any:
        """Get config value from options first, then data, then default."""
        return entry.options.get(key, entry.data.get(key, default))

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        event_logger: EventLogger | None = None,
        habit_predictor: HabitPredictor | None = None,
        confidence_combiner: ConfidenceCombiner | None = None,
        history_tracker: HistoryTracker | None = None,
        notification_manager: NotificationManager | None = None,
    ) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.provider_type = self._get_config(entry, CONF_PROVIDER, DEFAULT_PROVIDER)
        self.provider_url = self._get_config(entry, CONF_URL, DEFAULT_URL)
        self.model = self._get_config(entry, CONF_MODEL, DEFAULT_MODEL)
        self.persons = self._get_config(entry, CONF_PERSONS, [])
        self.pets = self._get_config(entry, CONF_PETS, [])
        self.rooms = self._get_config(entry, CONF_ROOMS, VALID_ROOMS)
        self.room_entities: dict[str, list[dict]] = normalize_room_entities(
            self._get_config(entry, CONF_ROOM_ENTITIES, {})
        )
        self.room_areas: dict[str, str] = self._get_config(entry, CONF_ROOM_AREAS, {}) or {}
        self.person_devices: dict[str, list[str]] = self._get_config(entry, CONF_PERSON_DEVICES, {})
        self.confidence_weights = self._get_config(entry, CONF_CONFIDENCE_WEIGHTS, DEFAULT_CONFIDENCE_WEIGHTS)
        self.learning_enabled = self._get_config(entry, CONF_LEARNING_ENABLED, DEFAULT_LEARNING_ENABLED)
        poll_interval = self._get_config(entry, CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)

        # Initialize the LLM provider
        self.timeout = self._get_config(entry, CONF_TIMEOUT, DEFAULT_TIMEOUT)
        self.provider = get_provider(
            provider_type=self.provider_type,
            url=self.provider_url,
            model=self.model,
            timeout=self.timeout,
        )

        # Accept injected instances or create defaults
        self.event_logger = event_logger or EventLogger()
        self.habit_predictor = habit_predictor or HabitPredictor()
        self.confidence_combiner = confidence_combiner or ConfidenceCombiner(self.confidence_weights)
        self.history_tracker = history_tracker or HistoryTracker()
        self.notification_manager = notification_manager or NotificationManager(
            hass,
            enabled=self._get_config(entry, CONF_NOTIFICATIONS_ENABLED, DEFAULT_NOTIFICATIONS_ENABLED),
        )

        # Learned habits are written to disk periodically, not on every update
        self._habits_dirty = False
        self._last_habit_save = time.monotonic()

        # Device tracker helper for away detection
        self.device_tracker_helper = DeviceTrackerHelper()

        # Room-level device presence (phones, watches and tags located to a room)
        self.device_room_locator = DeviceRoomLocator(self.rooms)

        # Track previous rooms for transition detection
        self._previous_rooms: dict[str, str] = {}

        # Last strong clue per person/pet: (room, confidence, time.monotonic()).
        # Drives "stay where last seen" when nothing is active.
        self._last_clue: dict[str, tuple[str, float, float]] = {}
        # Room last reported per person/pet and why it changed to it
        self._reason_state: dict[str, tuple[str, str]] = {}

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=poll_interval),
        )

        _LOGGER.info(
            "Roomer coordinator initialized: provider=%s, rooms=%d, room_entities=%d configured",
            self.provider_type,
            len(self.rooms),
            len(self.room_entities),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from LLM provider."""

        start_time = time.time()

        try:
            # Gather sensor context from Home Assistant
            context = await self._gather_sensor_context()

            # Get active indicators from configured room entities
            active_indicators = self._get_active_indicators(context)

            # Query LLM for each person/pet
            results: dict[str, Any] = {
                "persons": {},
                "pets": {},
                "last_context": context,
            }

            for person in self.persons:
                person_name = person.get("name", "unknown")
                guess = await self._process_entity(
                    person_name,
                    "person",
                    context,
                    active_indicators,
                )
                self._annotate_change_reason(person_name, guess)
                results["persons"][person_name] = guess

            for pet in self.pets:
                pet_name = pet.get("name", "unknown")
                guess = await self._process_entity(
                    pet_name,
                    "pet",
                    context,
                    active_indicators,
                    is_pet=True,
                )
                self._annotate_change_reason(pet_name, guess)
                results["pets"][pet_name] = guess

            await self._async_maybe_save_habits()

            elapsed = time.time() - start_time
            _LOGGER.debug("Finished fetching roomer data in %.3f seconds (success: True)", elapsed)

            return results

        except Exception as err:
            _LOGGER.error("Error fetching LLM presence data: %s", err)
            raise UpdateFailed(f"Error communicating with LLM: {err}") from err

    async def _process_entity(
        self,
        name: str,
        entity_type: str,
        context: dict[str, Any],
        active_indicators: list[dict],
        is_pet: bool = False,
    ) -> PresenceGuess:
        """Process a single person or pet through the presence detection pipeline."""

        # Devices of this person/pet that report the room they are in
        device_readings = self.device_room_locator.locate(self.hass, self.person_devices.get(name, []))

        # Device tracker check (persons only). Trackers reporting a room aren't away.
        if not is_pet:
            is_home, trackers_checked = self.device_tracker_helper.check_person_device_trackers(
                self.hass, name, self.person_devices, exclude={r.entity_id for r in device_readings}
            )
            if is_home is False and not seen_since_away(self.hass, device_readings, trackers_checked):
                guess = PresenceGuess(
                    room=ROOM_AWAY,
                    confidence=self.device_tracker_helper.get_away_confidence(),
                    raw_response="Device tracker indicates not home",
                    indicators=[f"device_tracker: {t}" for t in trackers_checked],
                    source="device_tracker",
                )
                _LOGGER.debug("%s is away (device tracker: %s)", name, trackers_checked)
                self._last_clue.pop(name, None)
                await self._log_presence_event(name, entity_type, guess, context)
                await self._check_room_transition(name, guess.room, guess.confidence)
                return guess

        # A device of theirs reports its room: that answers it for this person/pet alone
        if device_readings:
            guess = self.device_room_locator.guess(device_readings)
            _LOGGER.debug("%s located in %s by device (%s)", name, guess.room, guess.raw_response)
            self._remember_clue(name, guess.room, guess.confidence)
            if self.learning_enabled and guess.confidence >= 0.7:
                self.habit_predictor.learn_from_event(
                    entity_name=name,
                    room=guess.room,
                    confidence=guess.confidence,
                )
                self._habits_dirty = True
            await self._log_presence_event(name, entity_type, guess, context)
            await self._check_room_transition(name, guess.room, guess.confidence)
            return guess

        # Get habit hint (learned patterns)
        habit_hint = self.habit_predictor.get_habit_hint(name, entity_type)
        habit_context = self.habit_predictor.get_habit_context_for_prompt(name, entity_type)

        # Get indicators
        if is_pet:
            entity_indicators = [i for i in active_indicators if i.get("hint_type") != ENTITY_HINT_COMPUTER]
        else:
            entity_indicators = self._get_person_indicators(name, active_indicators, context)
        # A person detection counts only for people, an animal detection only for pets
        entity_indicators = self._filter_by_detects(entity_indicators, is_pet)

        # Nothing active: stay where they were last seen, if that was recent
        if not entity_indicators:
            sticky = self._sticky_guess(name)
            if sticky is not None:
                _LOGGER.debug("%s stays in %s (last seen, no active clues)", name, sticky.room)
                await self._log_presence_event(name, entity_type, sticky, context)
                await self._check_room_transition(name, sticky.room, sticky.confidence)
                return sticky

        # Build context for LLM
        context_for_llm = {
            **context,
            "habit_hint": habit_context,
            "active_indicators": [f"{i['hint_type']}: {i['entity_id']} in {i['room']}" for i in entity_indicators],
        }

        # Query LLM
        guess = await self.provider.deduce_presence(
            hass=self.hass,
            context=context_for_llm,
            entity_name=name,
            entity_type=entity_type,
            rooms=self.rooms,
        )

        # Combine confidence from multiple sources
        final_room, final_confidence, explanation, alternates = self.confidence_combiner.combine_with_alternates(
            llm_room=guess.room,
            llm_confidence=guess.confidence,
            habit_room=habit_hint.get("predicted_room"),
            habit_confidence=habit_hint.get("confidence", 0),
            sensor_indicators=entity_indicators,
            entity_name=name,
            room_entities=self.room_entities,
            prefer_room=self._previous_rooms.get(name),
        )

        # Update guess with combined result
        if guess.room != final_room:
            _LOGGER.debug(
                "Confidence combiner changed %s from %s to %s (reason: %s)",
                name,
                guess.room,
                final_room,
                explanation,
            )
        guess.room = final_room
        guess.confidence = final_confidence
        guess.alternate_rooms = alternates
        if entity_indicators:
            indicator_list = [f"{i['hint_type']}: {i['entity_id'].split('.')[-1]}" for i in entity_indicators[:5]]
            if explanation:
                indicator_list.append(explanation)
            guess.indicators = indicator_list
            guess.source = SOURCE_SENSOR
            self._remember_clue(name, final_room, final_confidence)
        else:
            # No mapped clue is active: this is only a prior (LLM and habits), not evidence
            guess.indicators = [PRIOR_INDICATOR]
            guess.confidence = min(final_confidence, PRIOR_MAX_CONFIDENCE)
            guess.source = SOURCE_PRIOR

        # Learn from this event if confident
        if self.learning_enabled and final_confidence >= 0.7:
            self.habit_predictor.learn_from_event(
                entity_name=name,
                room=final_room,
                confidence=final_confidence,
            )
            self._habits_dirty = True

        # Log the event and check for room transitions
        await self._log_presence_event(name, entity_type, guess, context)
        await self._check_room_transition(name, guess.room, guess.confidence)

        return guess

    # ------------------------------------------------------------------
    # Clues, "stay where last seen" and change reasons
    # ------------------------------------------------------------------

    def _remember_clue(self, name: str, room: str, confidence: float) -> None:
        """Remember a strong clue so the person can stay in that room while it is quiet."""
        if room in (ROOM_UNKNOWN, ROOM_AWAY) or confidence < STRONG_CLUE_MIN_CONFIDENCE:
            return
        self._last_clue[name] = (room, confidence, time.monotonic())

    def register_correction(self, name: str, room: str, confidence: float = 1.0) -> None:
        """Record a manual correction: they stay in that room until a clue says otherwise."""
        if room in (ROOM_UNKNOWN, ROOM_AWAY):
            self._last_clue.pop(name, None)
        else:
            self._last_clue[name] = (room, confidence, time.monotonic())
        self._reason_state[name] = (room, SOURCE_MANUAL)

    def _sticky_guess(self, name: str) -> PresenceGuess | None:
        """Return "still where last seen" for a recent strong clue, or None."""
        clue = self._last_clue.get(name)
        if clue is None:
            return None
        room, confidence, seen_at = clue
        age = time.monotonic() - seen_at
        if age > STICKY_MAX_AGE:
            return None
        decayed = min(max(confidence, STICKY_BASE_MIN), STICKY_MAX_CONFIDENCE) * 0.5 ** (age / STICKY_HALF_LIFE)
        if decayed < STICKY_MIN_CONFIDENCE:
            return None
        return PresenceGuess(
            room=room,
            confidence=round(decayed, 3),
            raw_response="No active clues; staying where last seen",
            indicators=[f"Last seen in {room.replace('_', ' ')} {self._format_age(age)} ago; no active clues"],
            source=SOURCE_STICKY,
        )

    @staticmethod
    def _format_age(seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}s"
        if seconds < 3600:
            return f"{int(seconds / 60)}m"
        return f"{int(seconds / 3600)}h"

    def _annotate_change_reason(self, name: str, guess: PresenceGuess) -> None:
        """Set ``last_changed_reason``: why this person's room last changed."""
        previous = self._reason_state.get(name)
        if guess.room == ROOM_UNKNOWN and previous:
            # Inconclusive, not a change: keep the last reported room and reason
            guess.last_changed_reason = previous[1]
            return
        if previous is None or previous[0] != guess.room:
            reason = guess.indicators[0] if guess.indicators else guess.source
            self._reason_state[name] = (guess.room, reason)
            previous = self._reason_state[name]
        guess.last_changed_reason = previous[1]

    def area_id_for_room(self, room: str | None) -> str | None:
        """Return the Home Assistant area id a room maps to, if known.

        A mapping set in the options wins; otherwise a room whose name matches
        an area's name (ignoring case, spaces and punctuation) maps to it.
        """
        if not room or room in (ROOM_AWAY, ROOM_UNKNOWN):
            return None
        configured = self.room_areas.get(room)
        if configured:
            return configured
        try:
            from homeassistant.helpers import area_registry as ar

            wanted = _norm(room)
            for area in ar.async_get(self.hass).async_list_areas():
                if _norm(area.name) == wanted or _norm(area.id) == wanted:
                    return area.id
        except Exception:  # noqa: BLE001 - registry unavailable (e.g. during tests)
            return None
        return None

    @staticmethod
    def _filter_by_detects(indicators: list[dict], is_pet: bool) -> list[dict]:
        """Drop detections that don't apply: people ignore animals, pets ignore people."""
        skip = DETECTS_PERSON if is_pet else DETECTS_ANIMAL
        return [i for i in indicators if (i.get("detects") or "any") != skip]

    def _get_active_indicators(self, context: dict[str, Any]) -> list[dict]:
        """Get list of active indicators based on configured room entities.

        Returns list of dicts with: entity_id, hint_type, room, state
        """
        active = []

        for room, entities in self.room_entities.items():
            for entity_config in entities:
                entity_id = entity_config.get("entity_id")
                hint_type = entity_config.get("hint_type", "appliance")

                # Get current state from context or HA directly
                state = self._get_entity_state(entity_id, context)

                if self._is_entity_active(entity_id, state, hint_type):
                    active.append(
                        {
                            "entity_id": entity_id,
                            "hint_type": hint_type,
                            "room": room,
                            "state": state,
                            "weight": entity_config.get("weight", 1.0),
                            "detects": entity_config.get("detects") or guess_detects(entity_id),
                            "shared": len(self._find_entity_rooms(entity_id)) > 1,
                        }
                    )

        return active

    def _get_entity_state(self, entity_id: str, context: dict[str, Any]) -> str:
        """Get entity state from context or Home Assistant."""
        # Check context first
        for category in ["lights", "motion", "media", "computers", "doors", "ai_detection"]:
            if entity_id in context.get(category, {}):
                return context[category][entity_id].get("state", "unknown")

        # Fall back to HA state
        state = self.hass.states.get(entity_id)
        return state.state if state else "unknown"

    def _is_entity_active(self, entity_id: str, state: str, hint_type: str) -> bool:
        """Determine if an entity is in an 'active' state."""
        state_lower = state.lower() if state else ""

        # Media players are special - playing is active, paused is semi-active
        if hint_type == ENTITY_HINT_MEDIA:
            return state_lower in ["playing", "paused", "on"]

        # Most entities: "on", "home", "detected" are active
        active_states = ["on", "home", "detected", "playing", "open", "occupied"]
        return state_lower in active_states

    def _get_person_indicators(
        self,
        person_name: str,
        all_indicators: list[dict],
        context: dict[str, Any],
    ) -> list[dict]:
        """Get indicators relevant to a specific person.

        Includes:
        - All general indicators (motion, media, etc.)
        - Person's owned devices (if active, strongly suggests their location)
        """
        indicators = list(all_indicators)  # Copy all indicators

        # Check person's owned devices
        owned_devices = self.person_devices.get(person_name, [])
        for device_id in owned_devices:
            state = self._get_entity_state(device_id, context)
            if self._is_entity_active(device_id, state, ENTITY_HINT_COMPUTER):
                # Find which room(s) this device is mapped to
                for room, weight in self._find_entity_rooms(device_id):
                    indicators.append(
                        {
                            "entity_id": device_id,
                            "hint_type": ENTITY_HINT_COMPUTER,
                            "room": room,
                            "state": state,
                            "owned_by": person_name,
                            "weight": weight,
                        }
                    )

        return indicators

    def _find_entity_rooms(self, entity_id: str) -> list[tuple[str, float]]:
        """Return every (room, weight) an entity is mapped to."""
        found = []
        for room, entities in self.room_entities.items():
            for entity_config in entities:
                if entity_config.get("entity_id") == entity_id:
                    found.append((room, entity_config.get("weight", 1.0)))
        return found

    def _find_entity_room(self, entity_id: str) -> str | None:
        """Find which room an entity belongs to based on config."""
        for room, entities in self.room_entities.items():
            for entity_config in entities:
                if entity_config.get("entity_id") == entity_id:
                    return room
        return None

    async def _gather_sensor_context(self) -> dict[str, Any]:
        """Gather current state of only configured entities.

        Only reads entities from room_entities config and person_devices,
        instead of scanning all HA entities.
        """
        now = dt_util.now()

        context: dict[str, Any] = {
            "lights": {},
            "motion": {},
            "media": {},
            "device_trackers": {},
            "doors": {},
            "climate": {},
            "computers": {},
            "ai_detection": {},
            "time_context": {
                "current_time": now.strftime("%H:%M"),
                "day_of_week": now.strftime("%A"),
                "is_night": now.hour >= 22 or now.hour < 6,
                "is_morning": 6 <= now.hour < 10,
                "is_evening": 18 <= now.hour < 22,
            },
            "configured_rooms": self.rooms,
        }

        # Collect all entity IDs we need to read
        entity_ids: set[str] = set()

        # From room_entities config
        for _room, entities in self.room_entities.items():
            for entity_config in entities:
                entity_id = entity_config.get("entity_id")
                if entity_id:
                    entity_ids.add(entity_id)

        # From person_devices config
        for _person, devices in self.person_devices.items():
            for device_id in devices:
                entity_ids.add(device_id)

        # Read and categorize each configured entity
        for entity_id in entity_ids:
            state = self.hass.states.get(entity_id)
            if not state:
                continue

            time_since_change = self._format_time_since(now, state.last_changed)

            # Find hint_type from room_entities config
            hint_type = self._get_entity_hint_type(entity_id)

            # Categorize by hint_type first, then by domain as fallback
            self._categorize_entity(
                context,
                entity_id,
                state,
                hint_type,
                time_since_change,
            )

        return context

    def _format_time_since(self, now, last_changed) -> str | None:
        """Format time since last state change as human-readable string."""
        if not last_changed:
            return None
        delta = now - last_changed
        seconds = delta.total_seconds()
        if seconds < 60:
            return f"{int(seconds)}s ago"
        if seconds < 3600:
            return f"{int(seconds / 60)}m ago"
        return f"{int(seconds / 3600)}h ago"

    def _get_entity_hint_type(self, entity_id: str) -> str | None:
        """Look up the configured hint_type for an entity."""
        for _room, entities in self.room_entities.items():
            for entity_config in entities:
                if entity_config.get("entity_id") == entity_id:
                    return entity_config.get("hint_type", "appliance")
        return None

    def _categorize_entity(
        self,
        context: dict[str, Any],
        entity_id: str,
        state,
        hint_type: str | None,
        time_since_change: str | None,
    ) -> None:
        """Categorize an entity into the appropriate context bucket."""
        # Use hint_type if configured, otherwise infer from domain/name
        if hint_type == ENTITY_HINT_COMPUTER:
            room = self._find_entity_room(entity_id)
            context["computers"][entity_id] = {
                "state": state.state,
                "room": room or "unknown",
            }
        elif hint_type == "light" or entity_id.startswith("light."):
            context["lights"][entity_id] = {
                "state": state.state,
                "last_changed": time_since_change,
                "brightness": state.attributes.get("brightness"),
            }
        elif hint_type == "motion" or (entity_id.startswith("binary_sensor.") and "motion" in entity_id.lower()):
            context["motion"][entity_id] = {
                "state": state.state,
                "last_changed": time_since_change,
            }
        elif hint_type == "door" or (
            entity_id.startswith("binary_sensor.")
            and any(x in entity_id.lower() for x in ["door", "window", "contact"])
        ):
            context["doors"][entity_id] = {
                "state": state.state,
                "last_changed": time_since_change,
            }
        elif hint_type == "media" or entity_id.startswith("media_player."):
            media_info = {
                "state": state.state,
                "last_changed": time_since_change,
            }
            if state.attributes.get("media_title"):
                media_info["playing"] = state.attributes.get("media_title")
            if state.attributes.get("app_name"):
                media_info["app"] = state.attributes.get("app_name")
            context["media"][entity_id] = media_info
        elif hint_type == "camera" or (
            entity_id.startswith("binary_sensor.")
            and any(x in entity_id.lower() for x in ["_person", "_animal", "_pet", "_human"])
        ):
            context["ai_detection"][entity_id] = {
                "state": state.state,
                "last_changed": time_since_change,
            }
        elif hint_type == "climate" or (
            entity_id.startswith("sensor.") and any(x in entity_id.lower() for x in ["temperature", "humidity"])
        ):
            context["climate"][entity_id] = {
                "state": state.state,
                "unit": state.attributes.get("unit_of_measurement", ""),
            }
        elif hint_type == "presence" or entity_id.startswith(("device_tracker.", "person.")):
            context["device_trackers"][entity_id] = {
                "state": state.state,
                "last_changed": time_since_change,
            }
        # Default: skip uncategorized entities rather than pollute context

    async def _log_presence_event(
        self,
        entity_name: str,
        entity_type: str,
        guess: Any,
        context: dict[str, Any],
    ) -> None:
        """Log presence event for ML training."""
        try:
            await self.event_logger.async_log_presence_event(
                entity_name=entity_name,
                entity_type=entity_type,
                room=guess.room,
                confidence=guess.confidence,
                raw_response=guess.raw_response,
                indicators=guess.indicators,
                sensor_context=context,
                detection_method="llm",
            )
        except OSError as err:
            _LOGGER.warning("Failed to log presence event: %s", err)

    async def _check_room_transition(
        self,
        entity_name: str,
        new_room: str,
        confidence: float,
    ) -> None:
        """Check if entity moved rooms, log and record the transition, and fire events."""
        previous_room = self._previous_rooms.get(entity_name)

        # "unknown" means the detection was inconclusive, not that the entity left,
        # so keep the last known room rather than reporting a transition.
        if new_room == ROOM_UNKNOWN:
            return

        if previous_room and previous_room != new_room:
            try:
                await self.event_logger.async_log_room_transition(
                    entity_name=entity_name,
                    from_room=previous_room,
                    to_room=new_room,
                    confidence=confidence,
                )
                _LOGGER.debug("Room transition: %s moved from %s to %s", entity_name, previous_room, new_room)
            except OSError as err:
                _LOGGER.warning("Failed to log room transition: %s", err)

            # record_transition writes to disk every few transitions
            await asyncio.to_thread(
                self.history_tracker.record_transition,
                entity_name,
                previous_room,
                new_room,
                confidence,
            )

        # Fires roomer_person_arrived / roomer_person_left / roomer_room_changed
        self.notification_manager.update_room(entity_name, new_room, confidence)

        self._previous_rooms[entity_name] = new_room

    async def _async_maybe_save_habits(self) -> None:
        """Save learned habits if they changed and the save interval has elapsed."""
        if not self._habits_dirty:
            return
        if time.monotonic() - self._last_habit_save < HABIT_SAVE_INTERVAL.total_seconds():
            return
        self._habits_dirty = False
        self._last_habit_save = time.monotonic()
        await asyncio.to_thread(self.habit_predictor.save_learned_patterns)

    def save_state(self) -> None:
        """Write learned habits and movement history to disk (blocking)."""
        self.habit_predictor.save_learned_patterns()
        self.history_tracker.save_history()
        self._habits_dirty = False
