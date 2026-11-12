"""Habit learning and pattern-based presence prediction.

Roomer learns presence patterns over time from observed data.
No hardcoded patterns - all patterns are learned from your household's actual behavior.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .const import (
    DEFAULT_CONFIDENCE_WEIGHTS,
    ENTITY_HINT_MEDIA,
)

_LOGGER = logging.getLogger(__name__)


def calculate_time_decay(seconds_ago: int, sensor_type: str = "motion") -> float:
    """Calculate time decay factor for sensor readings.

    Motion sensors decay over time - recent motion is more indicative.
    Lights don't decay - if on, they're on.

    Args:
        seconds_ago: How many seconds ago the event occurred
        sensor_type: Type of sensor ("motion", "light", "media", etc.)

    Returns:
        Decay factor from 0.0 to 1.0
    """
    # Lights and appliances don't decay - their state is current
    non_decaying = ["light", "appliance", "computer", "media"]
    if sensor_type in non_decaying:
        return 1.0

    # Motion sensors decay over time
    if sensor_type == "motion":
        if seconds_ago < 60:
            # Recent motion (< 1 min) - very high confidence
            return 1.0
        elif seconds_ago < 300:
            # Motion in last 5 minutes - high confidence
            return 0.95 - (seconds_ago - 60) / 4800  # Linear decay from 0.95 to 0.9
        elif seconds_ago < 600:
            # Motion in last 10 minutes - decaying confidence
            return 0.7 - (seconds_ago - 300) / 1500  # Linear decay from 0.7 to 0.5
        elif seconds_ago < 1800:
            # Motion in last 30 minutes - lower confidence
            return 0.4 - (seconds_ago - 600) / 4000  # Linear decay from 0.4 to 0.1
        else:
            # Old motion - very low confidence
            return max(0.1, 0.1 - (seconds_ago - 1800) / 36000)

    # Doors decay faster - door opening is momentary
    if sensor_type == "door":
        if seconds_ago < 30:
            return 1.0
        elif seconds_ago < 120:
            return 0.8
        elif seconds_ago < 300:
            return 0.5
        else:
            return 0.2

    # Default: moderate decay
    if seconds_ago < 300:
        return 1.0
    elif seconds_ago < 900:
        return 0.7
    else:
        return 0.4


class HabitPredictor:
    """Predict presence based on learned habits and patterns.

    Patterns are learned over time from observed presence events.
    No default patterns - starts blank and learns from your household.
    """

    def __init__(self, config_path: Path | None = None):
        """Initialize with optional path to learned patterns."""
        self._config_path = config_path or Path("/config")
        self._learned_patterns_path = self._config_path / "roomer_learned_habits.json"
        self.habits: dict[str, dict] = {}
        self._load_learned_patterns()

    def _load_learned_patterns(self) -> None:
        """Load learned patterns from file if available."""
        try:
            if self._learned_patterns_path.exists():
                with open(self._learned_patterns_path) as f:
                    data = json.load(f)
                    # Convert string keys back to tuples for time ranges
                    for person, patterns in data.get("patterns", {}).items():
                        self.habits[person] = {}
                        for time_key, pattern in patterns.items():
                            # Parse "0-4" format back to (0, 4) tuple
                            if "-" in time_key:
                                start, end = map(int, time_key.split("-"))
                                self.habits[person][(start, end)] = tuple(pattern)
                _LOGGER.info("Loaded learned habit patterns for %d people", len(self.habits))
        except (OSError, json.JSONDecodeError, KeyError, ValueError) as err:
            _LOGGER.debug("No learned patterns loaded: %s", err)

    def save_learned_patterns(self) -> None:
        """Save current patterns to file."""
        try:
            # Convert tuple keys to strings for JSON serialization
            data = {"patterns": {}}
            # Copy the items: this may run in a worker thread while the loop learns
            for person, patterns in list(self.habits.items()):
                data["patterns"][person] = {}
                for time_range, pattern in list(patterns.items()):
                    if isinstance(time_range, tuple):
                        time_key = f"{time_range[0]}-{time_range[1]}"
                        data["patterns"][person][time_key] = list(pattern)

            with open(self._learned_patterns_path, "w") as f:
                json.dump(data, f, indent=2)
            _LOGGER.info("Saved learned habit patterns")
        except OSError as err:
            _LOGGER.warning("Could not save learned patterns: %s", err)

    def learn_from_event(
        self,
        entity_name: str,
        room: str,
        confidence: float,
        timestamp: datetime | None = None,
    ) -> None:
        """Learn from an observed presence event.

        Call this when a presence is confirmed (high confidence or user correction).
        Over time, patterns will emerge.
        """
        if confidence < 0.7:
            # Only learn from confident observations
            return

        ts = timestamp or datetime.now()
        hour = ts.hour
        # Weekend detection removed - unused

        # Find or create time slot (2-hour windows)
        slot_start = (hour // 2) * 2
        slot_end = slot_start + 2
        time_range = (slot_start, slot_end)

        if entity_name not in self.habits:
            self.habits[entity_name] = {}

        # Get existing pattern or create new
        existing = self.habits[entity_name].get(time_range)

        if existing:
            # Update existing pattern with weighted average
            old_room, old_conf, old_count = existing[0], existing[1], existing[2] if len(existing) > 2 else 1
            if old_room == room:
                # Same room - increase confidence
                new_conf = (old_conf * old_count + confidence) / (old_count + 1)
                self.habits[entity_name][time_range] = (room, min(0.95, new_conf), old_count + 1)
            else:
                # Different room - only update if new observation is stronger
                if confidence > old_conf:
                    self.habits[entity_name][time_range] = (room, confidence, 1)
        else:
            # New pattern
            self.habits[entity_name][time_range] = (room, confidence, 1)

        _LOGGER.debug("Learned pattern: %s at %02d:00 -> %s (conf: %.2f)", entity_name, hour, room, confidence)

    def get_habit_hint(
        self,
        entity_name: str,
        entity_type: str = "person",
    ) -> dict[str, Any]:
        """Get habit-based prediction for current time.

        Returns:
            Dict with predicted_room, confidence, reason, and hint_text
        """
        now = datetime.now()
        hour = now.hour

        # Get habits for this entity
        person_habits = self.habits.get(entity_name, {})

        if not person_habits:
            return {
                "predicted_room": "unknown",
                "confidence": 0.0,
                "reason": "no learned patterns yet",
                "hint_text": f"No learned patterns for {entity_name} yet. Patterns will emerge over time.",
                "source": "none",
            }

        # Find matching time slot
        for time_range, pattern in person_habits.items():
            if isinstance(time_range, tuple) and len(time_range) == 2:
                start, end = time_range
                if start <= hour < end:
                    room = pattern[0]
                    conf = pattern[1]
                    return {
                        "predicted_room": room,
                        "confidence": conf,
                        "reason": "learned pattern",
                        "hint_text": f"Based on learned patterns, {entity_name} is usually in {room} at this time.",
                        "source": "learned_habit",
                    }

        return {
            "predicted_room": "unknown",
            "confidence": 0.0,
            "reason": "no pattern for this time",
            "hint_text": f"No learned pattern for {entity_name} at this hour.",
            "source": "none",
        }

    def get_habit_context_for_prompt(self, entity_name: str, entity_type: str = "person") -> str:
        """Get habit hint formatted for LLM prompt."""
        hint = self.get_habit_hint(entity_name, entity_type)

        if hint["confidence"] > 0:
            return f"""
LEARNED PATTERN HINT (use as context, not absolute truth):
{hint["hint_text"]}
Confidence: {int(hint["confidence"] * 100)}%
Note: This is a learned pattern - actual sensor data should override if contradictory.
"""
        return ""

    def get_daily_schedule(self, entity_name: str) -> list[dict]:
        """Get the full daily schedule for a person."""
        schedule = []
        person_habits = self.habits.get(entity_name, {})

        for time_range, pattern in sorted(person_habits.items()):
            if isinstance(time_range, tuple) and len(time_range) == 2:
                schedule.append(
                    {
                        "start_hour": time_range[0],
                        "end_hour": time_range[1],
                        "room": pattern[0],
                        "confidence": pattern[1],
                        "observations": pattern[2] if len(pattern) > 2 else 1,
                    }
                )

        return schedule

    def clear_patterns(self, entity_name: str | None = None) -> None:
        """Clear learned patterns for a person or all patterns."""
        if entity_name:
            self.habits.pop(entity_name, None)
            _LOGGER.info("Cleared patterns for %s", entity_name)
        else:
            self.habits.clear()
            _LOGGER.info("Cleared all learned patterns")
        self.save_learned_patterns()


# Fraction of the runner-up room's support subtracted from the winner's.
# Kept below 1.0 because in a shared home a competing signal is often
# another person rather than evidence against this one.
CONFLICT_PENALTY = 0.5

# Weight at or above which a signal counts as "strong" for the explanation.
STRONG_SIGNAL_WEIGHT = 0.5

# Cap on any single piece of evidence so one signal can never claim certainty.
MAX_SIGNAL_WEIGHT = 0.99


class ConfidenceCombiner:
    """Combine confidence scores from multiple sources using configured weights.

    Each weight is read as "how likely this signal alone is to be right".
    Signals pointing at the same room are combined with a noisy-OR,
    ``1 - prod(1 - w)``, so agreeing evidence raises confidence towards 1.0
    without exceeding it. Only the strongest signal of each hint type counts
    per room, so three lights in one room are not three independent votes;
    a person's owned device counts separately from the same anonymous signal.
    The winner is then discounted by the support for the runner-up room.
    """

    def __init__(self, weights: dict[str, float] | None = None):
        """Initialize with optional custom weights."""
        self.weights = weights or DEFAULT_CONFIDENCE_WEIGHTS.copy()

    def update_weights(self, new_weights: dict[str, float]) -> None:
        """Update confidence weights."""
        self.weights.update(new_weights)

    def combine(
        self,
        llm_room: str,
        llm_confidence: float,
        habit_room: str | None = None,
        habit_confidence: float = 0.0,
        sensor_indicators: list[dict] | None = None,
        entity_name: str | None = None,
        room_entities: dict[str, list[dict]] | None = None,
        active_entities: dict[str, str] | None = None,
    ) -> tuple[str, float, str]:
        """Combine multiple signals into final prediction.

        Args:
            llm_room: Room predicted by LLM
            llm_confidence: LLM's confidence
            habit_room: Room from learned habit patterns
            habit_confidence: Habit pattern confidence
            sensor_indicators: List of indicator dicts with entity_id, hint_type, room
            entity_name: Name of person (for person-specific device logic)
            room_entities: Configured room-to-entity mappings
            active_entities: Currently active entities {entity_id: state}

        Returns:
            Tuple of (room, confidence, explanation)
        """
        # Strongest evidence per (room, source), where source is a hint type,
        # "llm_reasoning" or "habit".
        evidence: dict[str, dict[str, float]] = {}
        explanations: list[str] = []

        def add(room: str, source: str, weight: float) -> None:
            weight = max(0.0, min(MAX_SIGNAL_WEIGHT, weight))
            sources = evidence.setdefault(room, {})
            sources[source] = max(sources.get(source, 0.0), weight)

        # Process sensor indicators
        if sensor_indicators:
            for indicator in sensor_indicators:
                room = indicator.get("room")
                hint_type = indicator.get("hint_type", "motion")
                entity_id = indicator.get("entity_id", "")
                state = indicator.get("state", "on")

                if not room or room == "unknown":
                    continue

                # Get weight for this hint type
                weight = self.weights.get(hint_type, 0.3)

                # Adjust weight based on state
                if hint_type == ENTITY_HINT_MEDIA:
                    if state == "playing":
                        weight = self.weights.get(ENTITY_HINT_MEDIA, 0.8)
                    elif state == "paused":
                        weight = self.weights.get(ENTITY_HINT_MEDIA, 0.8) * 0.7
                    else:
                        weight = 0.1

                # A person's own device is extra evidence on top of the
                # anonymous one (see _get_person_indicators), so keep it apart.
                source = f"{hint_type}:owned" if indicator.get("owned_by") else hint_type
                add(room, source, weight)

                # Build explanation
                if weight >= STRONG_SIGNAL_WEIGHT:
                    short_entity = entity_id.split(".")[-1] if "." in entity_id else entity_id
                    explanations.append(f"{hint_type}: {short_entity}")

        # LLM reasoning
        if llm_room and llm_room != "unknown":
            add(llm_room, "llm_reasoning", llm_confidence * self.weights.get("llm_reasoning", 0.5))
            if llm_confidence >= 0.5:
                explanations.append(f"LLM: {llm_room}")

        # Habit prediction
        if habit_room and habit_room != "unknown" and habit_confidence > 0:
            add(habit_room, "habit", habit_confidence * self.weights.get("habit", 0.35))

        support: dict[str, float] = {}
        for room, sources in evidence.items():
            miss = 1.0
            for weight in sources.values():
                miss *= 1.0 - weight
            support[room] = 1.0 - miss

        if not support or max(support.values()) <= 0:
            return "unknown", 0.0, "No signals available"

        # Find the room with highest combined support
        ranked = sorted(support.items(), key=lambda item: item[1], reverse=True)
        best_room, best_support = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0.0

        final_confidence = best_support * (1.0 - CONFLICT_PENALTY * runner_up)
        final_confidence = max(0.0, min(1.0, final_confidence))

        strong_sources = [w for w in evidence[best_room].values() if w >= STRONG_SIGNAL_WEIGHT]
        if len(strong_sources) >= 2:
            explanations.insert(0, "Multiple signals agree")

        explanation = " | ".join(explanations[:4])  # Limit explanation length

        return best_room, final_confidence, explanation
