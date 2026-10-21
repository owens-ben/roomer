"""Base class for LLM providers."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import aiohttp

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclass
class PresenceGuess:
    """Result of a presence detection query."""

    room: str
    confidence: float  # 0.0 to 1.0
    raw_response: str
    indicators: list[str]  # What signals led to this guess
    source: str = "llm"  # Source of prediction: llm, device_tracker, habit, sensor

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "room": self.room,
            "confidence": self.confidence,
            "raw_response": self.raw_response,
            "indicators": self.indicators,
            "source": self.source,
        }


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""

    def __init__(self, url: str, model: str, timeout: int = 30, **kwargs) -> None:
        """Initialize the provider."""
        self.url = url
        self.model = model
        self.timeout = timeout
        self._extra_config = kwargs
        self._session: aiohttp.ClientSession | None = None

    def _get_session(self) -> aiohttp.ClientSession:
        """Get or create a shared aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def async_close(self) -> None:
        """Close the shared aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _call_with_retry(
        self,
        coro_factory,
        max_retries: int = 1,
        backoff: float = 2.0,
    ):
        """Call an async function with retry logic.

        Args:
            coro_factory: A callable that returns a new coroutine each call.
            max_retries: Number of retries after first failure.
            backoff: Seconds to wait between retries.

        Returns:
            The result of the coroutine.
        """
        last_err = None
        for attempt in range(1 + max_retries):
            try:
                return await coro_factory()
            except (aiohttp.ClientError, TimeoutError) as err:
                last_err = err
                if attempt < max_retries:
                    _LOGGER.debug(
                        "Retry %d/%d after %s: %s",
                        attempt + 1,
                        max_retries,
                        type(err).__name__,
                        err,
                    )
                    await asyncio.sleep(backoff * (attempt + 1))
        raise last_err  # type: ignore[misc]

    @abstractmethod
    async def deduce_presence(
        self,
        hass: HomeAssistant,
        context: dict[str, Any],
        entity_name: str,
        entity_type: str,  # "person" or "pet"
        rooms: list[str],
    ) -> PresenceGuess:
        """Query the LLM to deduce room presence.

        Args:
            hass: Home Assistant instance
            context: Dictionary of sensor states (lights, motion, media, trackers)
            entity_name: Name of the person or pet
            entity_type: "person" or "pet"
            rooms: List of valid room names

        Returns:
            PresenceGuess with room, confidence, and supporting data
        """
        pass

    @abstractmethod
    async def test_connection(self) -> bool:
        """Test if the provider is reachable and working.

        Returns:
            True if connection successful, False otherwise
        """
        pass

    @abstractmethod
    async def get_available_models(self) -> list[str]:
        """Get list of available models from the provider.

        Returns:
            List of model names
        """
        pass

    # Maximum context size in characters to avoid exceeding model token windows
    MAX_CONTEXT_CHARS = 4000

    def _format_context_for_prompt(
        self,
        context: dict[str, Any],
        entity_name: str,
        entity_type: str,
    ) -> str:
        """Format sensor context into a human-readable prompt.

        Assembles per-category sections in priority order within a character budget.
        """
        # Build sections in priority order (highest signal first)
        sections = [
            self._format_time_context(context),
            self._format_ai_detection(context),
            self._format_motion(context),
            self._format_computers(context),
            self._format_media(context),
            self._format_lights(context),
            self._format_doors(context),
            self._format_device_trackers(context),
            self._format_climate(context),
        ]

        # Add habit hint if available
        habit_hint = context.get("habit_hint", "")
        if habit_hint:
            sections.append(habit_hint)

        # Add active indicators from coordinator
        active = context.get("active_indicators", [])
        if active:
            section_lines = ["ACTIVE INDICATORS:"]
            for ind in active[:10]:
                section_lines.append(f"  - {ind}")
            sections.append("\n".join(section_lines))

        # Assemble within budget
        result_parts = []
        total_len = 0
        for section in sections:
            if not section:
                continue
            if total_len + len(section) > self.MAX_CONTEXT_CHARS:
                break
            result_parts.append(section)
            total_len += len(section) + 1  # +1 for newline

        return "\n".join(result_parts)

    def _format_time_context(self, context: dict[str, Any]) -> str:
        """Format time context section."""
        time_ctx = context.get("time_context", {})
        lines = [f"CURRENT TIME: {time_ctx.get('current_time', 'unknown')} ({time_ctx.get('day_of_week', 'unknown')})"]
        if time_ctx.get("is_night"):
            lines.append("  ** NIGHTTIME (10pm-6am) **")
        elif time_ctx.get("is_morning"):
            lines.append("  ** MORNING (6am-10am) **")
        elif time_ctx.get("is_evening"):
            lines.append("  ** EVENING (6pm-10pm) **")
        return "\n".join(lines)

    def _format_ai_detection(self, context: dict[str, Any]) -> str:
        """Format camera AI detection section."""
        ai = context.get("ai_detection", {})
        if not ai:
            return ""
        lines = ["CAMERA AI DETECTION (very reliable):"]
        for entity_id, data in ai.items():
            camera = entity_id.replace("binary_sensor.", "").replace("_", " ").title()
            state = data.get("state")
            changed = data.get("last_changed", "")
            if state == "on":
                lines.append(f"  - {camera}: DETECTED NOW")
            else:
                lines.append(f"  - {camera}: none (last {changed})")
        return "\n".join(lines)

    def _format_motion(self, context: dict[str, Any]) -> str:
        """Format motion sensor section."""
        motion = context.get("motion", {})
        if not motion:
            return ""
        lines = ["MOTION SENSORS:"]
        for entity_id, data in motion.items():
            room = entity_id.replace("binary_sensor.", "").replace("_motion", "").replace("_", " ").title()
            state = data.get("state")
            changed = data.get("last_changed", "")
            if state == "on":
                lines.append(f"  - {room}: MOTION NOW")
            else:
                lines.append(f"  - {room}: none (last {changed})")
        return "\n".join(lines)

    def _format_computers(self, context: dict[str, Any]) -> str:
        """Format computers/workstations section."""
        computers = context.get("computers", {})
        if not computers:
            return ""
        lines = ["COMPUTERS (PC on = person at desk):"]
        for entity_id, data in computers.items():
            name = entity_id.split(".")[-1].replace("_", " ").title()
            state = data.get("state", "unknown")
            room = data.get("room", "")
            if state in ["on", "home"]:
                lines.append(f"  - {name}: ON/ACTIVE" + (f" in {room}" if room else ""))
            else:
                lines.append(f"  - {name}: off")
        return "\n".join(lines)

    def _format_media(self, context: dict[str, Any]) -> str:
        """Format media devices section."""
        media = context.get("media", {})
        if not media:
            return ""
        lines = ["MEDIA DEVICES:"]
        for entity_id, data in media.items():
            device = entity_id.replace("media_player.", "").replace("_", " ").title()
            state = data.get("state", "unknown")
            changed = data.get("last_changed", "")
            if state == "playing":
                app = data.get("app", "")
                playing = data.get("playing", "")
                info = f"PLAYING {app} {playing}".strip()
                lines.append(f"  - {device}: {info}")
            elif state == "paused":
                lines.append(f"  - {device}: PAUSED ({changed})")
            elif state in ("idle", "off"):
                lines.append(f"  - {device}: {state} ({changed})")
        return "\n".join(lines)

    def _format_lights(self, context: dict[str, Any]) -> str:
        """Format lights section."""
        lights = context.get("lights", {})
        if not lights:
            return ""
        lines = ["LIGHTS:"]
        for entity_id, data in lights.items():
            room = entity_id.replace("light.", "").replace("_", " ").title()
            state = data.get("state", "unknown")
            changed = data.get("last_changed", "")
            if state == "on":
                brightness = data.get("brightness")
                if brightness:
                    pct = round(brightness / 255 * 100)
                    lines.append(f"  - {room}: ON ({pct}%) ({changed})")
                else:
                    lines.append(f"  - {room}: ON ({changed})")
            elif state == "off" and changed:
                lines.append(f"  - {room}: off ({changed})")
        return "\n".join(lines)

    def _format_doors(self, context: dict[str, Any]) -> str:
        """Format doors/windows section."""
        doors = context.get("doors", {})
        if not doors:
            return ""
        lines = ["DOORS/WINDOWS:"]
        for entity_id, data in doors.items():
            name = entity_id.replace("binary_sensor.", "").replace("_", " ").title()
            state = "OPEN" if data.get("state") == "on" else "closed"
            changed = data.get("last_changed", "")
            lines.append(f"  - {name}: {state} ({changed})")
        return "\n".join(lines)

    def _format_device_trackers(self, context: dict[str, Any]) -> str:
        """Format device trackers section."""
        trackers = context.get("device_trackers", {})
        if not trackers:
            return ""
        lines = ["DEVICE TRACKERS:"]
        for entity_id, data in trackers.items():
            device = entity_id.replace("device_tracker.", "").replace("person.", "").replace("_", " ").title()
            state = data.get("state", "unknown")
            if state == "home":
                lines.append(f"  - {device}: HOME")
            elif state in ["not_home", "away"]:
                lines.append(f"  - {device}: AWAY")
            else:
                lines.append(f"  - {device}: {state}")
        return "\n".join(lines)

    def _format_climate(self, context: dict[str, Any]) -> str:
        """Format climate sensors section."""
        climate = context.get("climate", {})
        if not climate:
            return ""
        lines = ["CLIMATE SENSORS:"]
        for entity_id, data in climate.items():
            name = entity_id.replace("sensor.", "").replace("_", " ").title()
            state = data.get("state", "unknown")
            unit = data.get("unit", "")
            lines.append(f"  - {name}: {state}{unit}")
        return "\n".join(lines)

    def _extract_indicators(
        self,
        context: dict[str, Any],
        room: str,
        entity_name: str | None = None,
        room_entities: dict[str, list[dict]] | None = None,
    ) -> list[str]:
        """Extract indicators that support the room guess.

        Uses configured room_entities for entity-to-room mapping when available,
        falls back to name-based matching.
        """
        indicators = []
        room_lower = room.lower().replace(" ", "_")

        # Build reverse lookup: entity_id -> configured room
        entity_room_map: dict[str, str] = {}
        if room_entities:
            for cfg_room, entities in room_entities.items():
                for ent in entities:
                    eid = ent.get("entity_id", "")
                    if eid:
                        entity_room_map[eid] = cfg_room

        def _entity_in_room(entity_id: str, target_room: str) -> bool:
            """Check if entity belongs to target_room via config or name."""
            configured = entity_room_map.get(entity_id)
            if configured:
                return configured.lower().replace(" ", "_") == target_room.lower().replace(" ", "_")
            return room_lower in entity_id.lower()

        for entity_id, data in context.get("lights", {}).items():
            if _entity_in_room(entity_id, room) and data.get("state") == "on":
                indicators.append(f"Light on: {entity_id}")

        for entity_id, data in context.get("motion", {}).items():
            if _entity_in_room(entity_id, room) and data.get("state") == "on":
                indicators.append(f"Motion detected: {entity_id}")

        for entity_id, data in context.get("media", {}).items():
            if data.get("state") == "playing" and _entity_in_room(entity_id, room):
                indicators.append(f"Media playing: {entity_id}")

        for entity_id, data in context.get("computers", {}).items():
            if data.get("state") in ["on", "home"]:
                comp_room = data.get("room", "")
                if comp_room and comp_room.lower() == room.lower().replace(" ", "_"):
                    indicators.append(f"PC active: {entity_id}")
                elif _entity_in_room(entity_id, room):
                    indicators.append(f"PC active: {entity_id}")

        for entity_id, data in context.get("ai_detection", {}).items():
            if data.get("state") == "on" and _entity_in_room(entity_id, room):
                indicators.append(f"Camera detection: {entity_id}")

        return indicators

    def _create_fallback_guess(
        self,
        context: dict[str, Any],
        entity_name: str,
        entity_type: str,
        rooms: list[str],
        error_msg: str = "Fallback",
    ) -> PresenceGuess:
        """Create a fallback guess based on strong indicators when LLM fails.

        Uses deterministic logic based on sensor state to make a reasonable guess.
        """
        indicators = []

        # Check if any PC is on
        pc_is_on = False
        pc_room = "office"
        for data in context.get("computers", {}).values():
            if data.get("state") in ["on", "home"]:
                pc_is_on = True
                pc_room = data.get("room", "office")
                break

        # Check media state
        media_room = None
        for data in context.get("media", {}).values():
            if data.get("state") == "playing":
                # Use configured room if available, else guess from name
                media_room = data.get("room") or "living_room"
                break

        room = "unknown"
        confidence = 0.3

        if entity_type == "person":
            if pc_is_on:
                room = pc_room
                confidence = 0.5
                indicators.append("PC active (fallback)")
            elif media_room:
                room = media_room
                confidence = 0.55
                indicators.append("Media playing (fallback)")
            else:
                room = "living_room" if "living_room" in rooms else rooms[0] if rooms else "unknown"
                confidence = 0.3
        elif entity_type == "pet":
            if media_room:
                room = media_room
                confidence = 0.4
                indicators.append("TV on - pet with family (fallback)")
            elif pc_is_on:
                room = pc_room
                confidence = 0.35
                indicators.append("PC active - pet with owner (fallback)")
            else:
                room = "bedroom" if "bedroom" in rooms else rooms[0] if rooms else "unknown"
                confidence = 0.3

        indicators.extend(self._extract_indicators(context, room, entity_name))

        _LOGGER.info(
            "Fallback guess for %s: %s (%.0f%%) - %s",
            entity_name,
            room,
            confidence * 100,
            error_msg,
        )

        return PresenceGuess(
            room=room,
            confidence=confidence,
            raw_response=error_msg,
            indicators=indicators,
        )

    def _get_system_prompt(
        self,
        entity_name: str,
        entity_type: str,
        rooms: list[str],
    ) -> str:
        """Get the system prompt for presence detection."""
        rooms_str = ", ".join(rooms)

        if entity_type == "pet":
            return f"""You are a smart home presence detection AI. Determine which room the pet '{entity_name}' is most likely in.

RULES FOR PETS:
1. Pets follow their owners - if owners are in a room, pet is likely there too
2. At night, pets often sleep in bedrooms
3. Motion in a dark room might be a pet
4. Door recently opened - pet might have moved

OUTPUT FORMAT (exactly):
ROOM: <room_name>
CONFIDENCE: <0.0 to 1.0>

CONFIDENCE is how sure you are: 0.9+ when a camera sees the pet in the room, around 0.5 when guessing from owners, motion or time of day.

Valid rooms: {rooms_str}"""

        return f"""You are a smart home presence detection AI. Determine which room {entity_name} is most likely in.

REASONING RULES (priority order):
1. DEVICE TRACKER: "not_home"/"away" → respond "away"
2. CAMERA AI DETECTION: Very reliable - trust it
3. TV/MEDIA PLAYING: Person is in that room
4. PC/COMPUTER ON: Person at their desk
5. LIGHTS ON: Strong indicator
6. MOTION: Recent motion is a good indicator
7. TIME: Use only as tie-breaker

Camera AI and sensor data OVERRIDE time-of-day assumptions.

OUTPUT FORMAT (exactly):
ROOM: <room_name>
CONFIDENCE: <0.0 to 1.0>

CONFIDENCE is how sure you are: 0.9+ when a strong signal (camera, media, PC) points at the room, around 0.5 when guessing from weak hints or time of day.

Valid rooms: {rooms_str}"""


def _parse_confidence(value: str) -> float:
    """Parse a CONFIDENCE value, accepting 0.85 as well as 85 (percent)."""
    try:
        confidence = float(value.rstrip("."))
    except ValueError:
        return 0.7
    if confidence > 1.0:
        confidence /= 100
    return confidence


def parse_llm_response(
    response: str,
    valid_rooms: list[str],
) -> tuple[str, float, str]:
    """Parse LLM response to extract room, confidence, and reason.

    Handles multiple response formats:
    - "ROOM: living_room" (preferred)
    - "ROOM: office\\nCONFIDENCE: 0.8\\nREASON: Light is on"
    - JSON: {"room": "office", "confidence": 0.8}
    - Plain room name: "office"

    Returns:
        Tuple of (room, confidence, reason)
    """
    response = response.strip()
    valid_lower = [r.lower() for r in valid_rooms]

    # Try JSON format first
    try:
        data = json.loads(response)
        room = data.get("room", "unknown").lower()
        confidence = float(data.get("confidence", 0.5))
        reason = data.get("reason", "")
        if room in valid_lower:
            return room, min(1.0, max(0.0, confidence)), reason
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        pass

    # Try structured format: ROOM: xxx (supports hyphens and underscores)
    room_match = re.search(r"ROOM:\s*([\w_-]+)", response, re.IGNORECASE)
    conf_match = re.search(r"CONFIDENCE:\s*([\d.]+)", response, re.IGNORECASE)
    reason_match = re.search(r"REASON:\s*(.+?)(?:\n|$)", response, re.IGNORECASE)

    if room_match:
        room = room_match.group(1).lower()
        confidence = _parse_confidence(conf_match.group(1)) if conf_match else 0.7
        reason = reason_match.group(1).strip() if reason_match else ""
        if room in valid_lower:
            return room, min(1.0, max(0.0, confidence)), reason

    # Try plain room name (exact match in response)
    response_lower = response.lower().replace(" ", "_")
    for room in valid_rooms:
        if room.lower() in response_lower:
            conf_match = re.search(r"(\d+(?:\.\d+)?)\s*%", response)
            if conf_match:
                confidence = float(conf_match.group(1)) / 100
            else:
                confidence = 0.6
            return room.lower(), min(1.0, confidence), ""

    # Last resort: single-word response
    single_word = response_lower.strip().split("\n")[0].split()[0] if response_lower.strip() else ""
    if single_word in valid_lower:
        return single_word, 0.6, ""

    return "unknown", 0.0, "Could not parse response"
