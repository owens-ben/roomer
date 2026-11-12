"""
Tests for improved confidence scoring algorithm (TDD).

These tests verify that confidence scoring properly weights different signals
and combines them intelligently.
"""

import pytest


class TestConfidenceWeights:
    """Test default confidence weights."""

    def test_light_confidence_minimum(self):
        """Light-only indicators should have at least 35% base confidence."""
        from custom_components.roomer.const import DEFAULT_CONFIDENCE_WEIGHTS, ENTITY_HINT_LIGHT

        # Light confidence should be at least 0.35
        assert DEFAULT_CONFIDENCE_WEIGHTS[ENTITY_HINT_LIGHT] >= 0.35

    def test_motion_higher_than_light(self):
        """Motion sensors should have higher confidence than lights."""
        from custom_components.roomer.const import (
            DEFAULT_CONFIDENCE_WEIGHTS,
            ENTITY_HINT_LIGHT,
            ENTITY_HINT_MOTION,
        )

        assert DEFAULT_CONFIDENCE_WEIGHTS[ENTITY_HINT_MOTION] > DEFAULT_CONFIDENCE_WEIGHTS[ENTITY_HINT_LIGHT]

    def test_computer_very_high_confidence(self):
        """Computer/PC indicators should have very high confidence."""
        from custom_components.roomer.const import DEFAULT_CONFIDENCE_WEIGHTS, ENTITY_HINT_COMPUTER

        assert DEFAULT_CONFIDENCE_WEIGHTS[ENTITY_HINT_COMPUTER] >= 0.85

    def test_camera_highest_confidence(self):
        """Camera AI detection should have highest confidence."""
        from custom_components.roomer.const import DEFAULT_CONFIDENCE_WEIGHTS, ENTITY_HINT_CAMERA

        assert DEFAULT_CONFIDENCE_WEIGHTS[ENTITY_HINT_CAMERA] >= 0.90


class TestMultipleIndicators:
    """Test confidence combination with multiple indicators."""

    def test_multiple_indicators_increase_confidence(self):
        """Multiple indicators in same room should increase confidence."""
        from custom_components.roomer.const import DEFAULT_CONFIDENCE_WEIGHTS
        from custom_components.roomer.habits import ConfidenceCombiner

        combiner = ConfidenceCombiner(DEFAULT_CONFIDENCE_WEIGHTS)

        # Single light indicator
        single_indicators = [
            {"entity_id": "light.living_room", "hint_type": "light", "room": "living_room", "state": "on"}
        ]

        # Multiple indicators
        multiple_indicators = [
            {"entity_id": "light.living_room", "hint_type": "light", "room": "living_room", "state": "on"},
            {
                "entity_id": "binary_sensor.living_room_motion",
                "hint_type": "motion",
                "room": "living_room",
                "state": "on",
            },
        ]

        room1, conf1, _ = combiner.combine(
            llm_room="living_room",
            llm_confidence=0.5,
            habit_room=None,
            habit_confidence=0,
            sensor_indicators=single_indicators,
            entity_name="Test",
            room_entities={},
        )

        room2, conf2, _ = combiner.combine(
            llm_room="living_room",
            llm_confidence=0.5,
            habit_room=None,
            habit_confidence=0,
            sensor_indicators=multiple_indicators,
            entity_name="Test",
            room_entities={},
        )

        # Multiple indicators should yield higher confidence
        assert conf2 > conf1

    def test_conflicting_indicators_resolved(self):
        """Conflicting indicators should be resolved by weight."""
        from custom_components.roomer.const import DEFAULT_CONFIDENCE_WEIGHTS
        from custom_components.roomer.habits import ConfidenceCombiner

        combiner = ConfidenceCombiner(DEFAULT_CONFIDENCE_WEIGHTS)

        # Light in living room, but motion in kitchen
        # Use unknown LLM room so it doesn't bias the result
        indicators = [
            {"entity_id": "light.living_room", "hint_type": "light", "room": "living_room", "state": "on"},
            {"entity_id": "binary_sensor.kitchen_motion", "hint_type": "motion", "room": "kitchen", "state": "on"},
        ]

        room, confidence, _ = combiner.combine(
            llm_room="unknown",  # Don't bias with LLM
            llm_confidence=0.0,
            habit_room=None,
            habit_confidence=0,
            sensor_indicators=indicators,
            entity_name="Test",
            room_entities={},
        )

        # Motion (0.60) should win over light (0.35)
        assert room == "kitchen"


class TestTimeDecay:
    """Test time-based confidence decay."""

    def test_recent_motion_high_confidence(self):
        """Recent motion (<1 min) should have high confidence."""
        from custom_components.roomer.habits import calculate_time_decay

        # Motion 30 seconds ago
        decay = calculate_time_decay(seconds_ago=30, sensor_type="motion")
        assert decay >= 0.9

    def test_old_motion_lower_confidence(self):
        """Old motion (>5 min) should have lower confidence."""
        from custom_components.roomer.habits import calculate_time_decay

        # Motion 10 minutes ago
        decay = calculate_time_decay(seconds_ago=600, sensor_type="motion")
        assert decay < 0.5

    def test_light_no_decay(self):
        """Lights don't decay - if on, they're on."""
        from custom_components.roomer.habits import calculate_time_decay

        # Light on for 30 minutes
        decay = calculate_time_decay(seconds_ago=1800, sensor_type="light")
        assert decay >= 0.9


class TestConfidenceCombiner:
    """Test the ConfidenceCombiner class."""

    def test_combiner_exists(self):
        """ConfidenceCombiner should exist and be importable."""
        from custom_components.roomer.habits import ConfidenceCombiner

        assert ConfidenceCombiner is not None

    def test_combiner_returns_tuple(self):
        """Combiner should return (room, confidence, explanation)."""
        from custom_components.roomer.const import DEFAULT_CONFIDENCE_WEIGHTS
        from custom_components.roomer.habits import ConfidenceCombiner

        combiner = ConfidenceCombiner(DEFAULT_CONFIDENCE_WEIGHTS)

        result = combiner.combine(
            llm_room="office",
            llm_confidence=0.7,
            habit_room=None,
            habit_confidence=0,
            sensor_indicators=[],
            entity_name="Test",
            room_entities={},
        )

        assert isinstance(result, tuple)
        assert len(result) == 3
        room, confidence, explanation = result
        assert isinstance(room, str)
        assert isinstance(confidence, float)

    def test_llm_fallback_when_no_sensors(self):
        """Without sensor data, should use LLM prediction."""
        from custom_components.roomer.const import DEFAULT_CONFIDENCE_WEIGHTS
        from custom_components.roomer.habits import ConfidenceCombiner

        combiner = ConfidenceCombiner(DEFAULT_CONFIDENCE_WEIGHTS)

        room, confidence, _ = combiner.combine(
            llm_room="bedroom",
            llm_confidence=0.6,
            habit_room=None,
            habit_confidence=0,
            sensor_indicators=[],
            entity_name="Test",
            room_entities={},
        )

        assert room == "bedroom"


class TestConfidenceBounds:
    """Test confidence value bounds."""

    def test_confidence_max_100(self):
        """Confidence should never exceed 1.0 (100%)."""
        from custom_components.roomer.const import DEFAULT_CONFIDENCE_WEIGHTS
        from custom_components.roomer.habits import ConfidenceCombiner

        combiner = ConfidenceCombiner(DEFAULT_CONFIDENCE_WEIGHTS)

        # Lots of strong indicators
        indicators = [
            {"entity_id": "cam.person", "hint_type": "camera", "room": "office", "state": "on"},
            {"entity_id": "switch.pc", "hint_type": "computer", "room": "office", "state": "on"},
            {"entity_id": "motion.office", "hint_type": "motion", "room": "office", "state": "on"},
            {"entity_id": "light.office", "hint_type": "light", "room": "office", "state": "on"},
        ]

        room, confidence, _ = combiner.combine(
            llm_room="office",
            llm_confidence=0.9,
            habit_room="office",
            habit_confidence=0.8,
            sensor_indicators=indicators,
            entity_name="Test",
            room_entities={},
        )

        assert confidence <= 1.0

    def test_confidence_min_0(self):
        """Confidence should never be negative."""
        from custom_components.roomer.const import DEFAULT_CONFIDENCE_WEIGHTS
        from custom_components.roomer.habits import ConfidenceCombiner

        combiner = ConfidenceCombiner(DEFAULT_CONFIDENCE_WEIGHTS)

        room, confidence, _ = combiner.combine(
            llm_room="unknown",
            llm_confidence=0.0,
            habit_room=None,
            habit_confidence=0,
            sensor_indicators=[],
            entity_name="Test",
            room_entities={},
        )

        assert confidence >= 0.0


def _indicator(hint_type: str, room: str, state: str = "on") -> dict:
    return {"entity_id": f"sensor.{room}_{hint_type}", "hint_type": hint_type, "room": room, "state": state}


def _combine(**kwargs):
    from custom_components.roomer.const import DEFAULT_CONFIDENCE_WEIGHTS
    from custom_components.roomer.habits import ConfidenceCombiner

    kwargs.setdefault("habit_room", None)
    kwargs.setdefault("habit_confidence", 0)
    kwargs.setdefault("sensor_indicators", [])
    return ConfidenceCombiner(dict(DEFAULT_CONFIDENCE_WEIGHTS)).combine(**kwargs)


# Matches the gate in RoomerCoordinator before learn_from_event().
HABIT_LEARNING_THRESHOLD = 0.7


class TestCombinedConfidenceValues:
    """Concrete confidence values for the noisy-OR combiner.

    "Before" values are from the old combiner, which summed weights and divided
    by the top three default weights (0.95 + 0.85 + 0.80 = 2.60).
    """

    def test_motion_pc_and_llm_agree(self):
        """Before: (0.60 + 0.85 + 0.45) / 2.6 = 0.73. After: 1 - 0.40*0.15*0.55 = 0.967."""
        room, confidence, explanation = _combine(
            llm_room="office",
            llm_confidence=0.9,
            sensor_indicators=[_indicator("motion", "office"), _indicator("computer", "office")],
        )
        assert room == "office"
        assert confidence == pytest.approx(0.967)
        assert "Multiple signals agree" in explanation

    def test_motion_and_llm_agree_reaches_learning_threshold(self):
        """Before: (0.60 + 0.40) / 2.6 = 0.38, so habits never learned. After: 0.76."""
        room, confidence, _ = _combine(
            llm_room="office",
            llm_confidence=0.8,
            sensor_indicators=[_indicator("motion", "office")],
        )
        assert room == "office"
        assert confidence == pytest.approx(0.76)
        assert confidence >= HABIT_LEARNING_THRESHOLD

    def test_media_light_and_llm_agree(self):
        """Before: (0.80 + 0.35 + 0.40) / 2.6 = 0.60. After: 1 - 0.20*0.65*0.60 = 0.922."""
        room, confidence, _ = _combine(
            llm_room="living_room",
            llm_confidence=0.8,
            sensor_indicators=[
                _indicator("media", "living_room", "playing"),
                _indicator("light", "living_room"),
            ],
        )
        assert room == "living_room"
        assert confidence == pytest.approx(0.922)

    def test_motion_habit_and_llm_agree(self):
        """Before: (0.60 + 0.28 + 0.35) / 2.6 = 0.47. After: 1 - 0.40*0.72*0.65 = 0.8128."""
        room, confidence, _ = _combine(
            llm_room="kitchen",
            llm_confidence=0.7,
            habit_room="kitchen",
            habit_confidence=0.8,
            sensor_indicators=[_indicator("motion", "kitchen")],
        )
        assert room == "kitchen"
        assert confidence == pytest.approx(0.8128)

    def test_single_camera_uses_its_weight(self):
        """Before: 0.95 / 2.6 = 0.37. After: the camera weight itself, 0.95."""
        room, confidence, _ = _combine(
            llm_room="unknown",
            llm_confidence=0.0,
            sensor_indicators=[_indicator("camera", "office")],
        )
        assert room == "office"
        assert confidence == pytest.approx(0.95)

    def test_weak_evidence_stays_below_learning_threshold(self):
        """Light plus a lukewarm LLM. Before: 0.25. After: 1 - 0.65*0.70 = 0.545."""
        _, confidence, _ = _combine(
            llm_room="living_room",
            llm_confidence=0.6,
            sensor_indicators=[_indicator("light", "living_room")],
        )
        assert confidence == pytest.approx(0.545)
        assert confidence < HABIT_LEARNING_THRESHOLD

    def test_llm_alone_is_capped_by_its_weight(self):
        """Before: 0.35 / 2.6 = 0.13. After: 0.7 * 0.5 = 0.35."""
        room, confidence, _ = _combine(llm_room="bedroom", llm_confidence=0.7)
        assert room == "bedroom"
        assert confidence == pytest.approx(0.35)

    def test_same_hint_type_does_not_compound(self):
        """Three lights in one room count as one light signal, not three."""
        _, confidence, _ = _combine(
            llm_room="unknown",
            llm_confidence=0.0,
            sensor_indicators=[_indicator("light", "living_room") for _ in range(3)],
        )
        assert confidence == pytest.approx(0.35)

    def test_owned_device_counts_on_top_of_anonymous_signal(self):
        """The owner's PC adds a second, owned computer signal: 1 - 0.15*0.15 = 0.9775."""
        pc = _indicator("computer", "office")
        owned_pc = {**pc, "owned_by": "Alice"}
        _, anonymous, _ = _combine(llm_room="unknown", llm_confidence=0.0, sensor_indicators=[pc])
        _, owner, _ = _combine(llm_room="unknown", llm_confidence=0.0, sensor_indicators=[pc, owned_pc])
        assert anonymous == pytest.approx(0.85)
        assert owner == pytest.approx(0.9775)

    def test_owned_device_beats_anonymous_signal_elsewhere(self):
        """Alice's PC in the office outweighs anonymous TV in the living room for her."""
        pc = _indicator("computer", "office")
        room, confidence, _ = _combine(
            llm_room="unknown",
            llm_confidence=0.0,
            sensor_indicators=[pc, {**pc, "owned_by": "Alice"}, _indicator("media", "living_room", "playing")],
        )
        assert room == "office"
        assert confidence == pytest.approx(0.9775 * (1 - 0.5 * 0.8))

    def test_conflicting_room_discounts_winner(self):
        """Kitchen motion vs living room light: 0.60 * (1 - 0.5*0.35) = 0.495."""
        room, confidence, _ = _combine(
            llm_room="unknown",
            llm_confidence=0.0,
            sensor_indicators=[_indicator("light", "living_room"), _indicator("motion", "kitchen")],
        )
        assert room == "kitchen"
        assert confidence == pytest.approx(0.495)

    def test_strong_agreement_beats_conflict(self):
        """Camera + LLM in office vs motion in kitchen: 0.97 * (1 - 0.5*0.6) = 0.679."""
        room, confidence, _ = _combine(
            llm_room="office",
            llm_confidence=0.8,
            sensor_indicators=[_indicator("camera", "office"), _indicator("motion", "kitchen")],
        )
        assert room == "office"
        assert confidence == pytest.approx(0.679)

    def test_everything_agreeing_stays_below_one(self):
        """Before: clamped to exactly 1.0. After: very high but never certain."""
        _, confidence, _ = _combine(
            llm_room="office",
            llm_confidence=0.9,
            habit_room="office",
            habit_confidence=0.8,
            sensor_indicators=[
                _indicator("camera", "office"),
                _indicator("computer", "office"),
                _indicator("motion", "office"),
                _indicator("light", "office"),
            ],
        )
        assert 0.99 < confidence < 1.0

    def test_agreement_explanation_needs_two_strong_sources(self):
        """One strong signal plus weak ones is not reported as agreement."""
        _, _, explanation = _combine(
            llm_room="office",
            llm_confidence=0.6,  # 0.6 * 0.5 = 0.30, not strong
            sensor_indicators=[_indicator("motion", "office"), _indicator("light", "office")],
        )
        assert "Multiple signals agree" not in explanation

    def test_weight_of_one_is_capped(self):
        """A custom weight of 1.0 must not make one signal certain."""
        from custom_components.roomer.habits import ConfidenceCombiner

        combiner = ConfidenceCombiner({"camera": 1.0, "llm_reasoning": 0.5, "habit": 0.35})
        _, confidence, _ = combiner.combine(
            llm_room="unknown",
            llm_confidence=0.0,
            sensor_indicators=[_indicator("camera", "office")],
        )
        assert confidence < 1.0


class TestLLMConfidence:
    """The LLM is asked for, and can report, its own confidence."""

    @pytest.mark.parametrize("entity_type", ["person", "pet"])
    def test_system_prompt_asks_for_confidence(self, entity_type):
        from custom_components.roomer.providers.ollama import OllamaProvider

        provider = OllamaProvider(url="http://localhost:11434", model="llama3.2")
        prompt = provider._get_system_prompt("Alice", entity_type, ["office", "kitchen"])
        assert "CONFIDENCE:" in prompt

    @pytest.mark.parametrize(
        ("response", "expected"),
        [
            ("ROOM: office\nCONFIDENCE: 0.92", 0.92),
            ("ROOM: office\nCONFIDENCE: 0.4", 0.4),
            ("ROOM: office\nCONFIDENCE: 85", 0.85),
            ("ROOM: office\nCONFIDENCE: 85%", 0.85),
            ("ROOM: office\nCONFIDENCE: 0.9.", 0.9),
            ("ROOM: office", 0.7),  # Missing confidence keeps the old default
        ],
    )
    def test_parse_confidence(self, response, expected):
        from custom_components.roomer.providers.base import parse_llm_response

        room, confidence, _ = parse_llm_response(response, ["office", "kitchen"])
        assert room == "office"
        assert confidence == pytest.approx(expected)
