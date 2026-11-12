"""Multi-room entities, person/animal detections, priors, sticky rooms and the new attributes."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import State
from homeassistant.helpers import area_registry as ar

from custom_components.roomer.const import (
    DEFAULT_CONFIDENCE_WEIGHTS,
    PRIOR_INDICATOR,
    PRIOR_MAX_CONFIDENCE,
    STICKY_HALF_LIFE,
    STICKY_MAX_AGE,
    STICKY_MAX_CONFIDENCE,
)
from custom_components.roomer.device_presence import DeviceRoomLocator
from custom_components.roomer.habits import ConfidenceCombiner
from custom_components.roomer.providers.base import PresenceGuess

ROOMS = ["office", "living_room", "kitchen", "bedroom"]

CAMERA_PERSON = "binary_sensor.reolink_person"
CAMERA_ANIMAL = "binary_sensor.reolink_animal"


def _indicator(entity_id, room, hint="camera", weight=1.0, shared=False, detects="any", state="on"):
    return {
        "entity_id": entity_id,
        "hint_type": hint,
        "room": room,
        "state": state,
        "weight": weight,
        "shared": shared,
        "detects": detects,
    }


class TestCombinerMultiRoom:
    @pytest.fixture
    def combiner(self):
        return ConfidenceCombiner(DEFAULT_CONFIDENCE_WEIGHTS.copy())

    def test_weight_scales_an_indicator(self, combiner):
        full = combiner.combine("unknown", 0.0, sensor_indicators=[_indicator(CAMERA_PERSON, "kitchen")])
        half = combiner.combine("unknown", 0.0, sensor_indicators=[_indicator(CAMERA_PERSON, "kitchen", weight=0.5)])

        assert half[1] == pytest.approx(full[1] / 2)

    def test_camera_over_two_rooms_raises_both(self, combiner):
        indicators = [
            _indicator(CAMERA_PERSON, "kitchen", shared=True),
            _indicator(CAMERA_PERSON, "living_room", shared=True),
        ]

        room, _conf, _why, alternates = combiner.combine_with_alternates("unknown", 0.0, sensor_indicators=indicators)

        assert {room, *alternates} == {"kitchen", "living_room"}
        assert len(alternates) == 1

    def test_tie_goes_to_the_preferred_room(self, combiner):
        indicators = [
            _indicator(CAMERA_PERSON, "kitchen", shared=True),
            _indicator(CAMERA_PERSON, "living_room", shared=True),
        ]

        room, *_ = combiner.combine_with_alternates(
            "unknown", 0.0, sensor_indicators=indicators, prefer_room="living_room"
        )

        assert room == "living_room"

    def test_other_evidence_breaks_the_tie_and_keeps_the_camera_room_as_alternate(self, combiner):
        indicators = [
            _indicator(CAMERA_PERSON, "kitchen", shared=True),
            _indicator(CAMERA_PERSON, "living_room", shared=True),
            _indicator("media_player.tv", "living_room", hint="media", state="playing"),
        ]

        room, _c, _w, alternates = combiner.combine_with_alternates("unknown", 0.0, sensor_indicators=indicators)

        assert room == "living_room"
        # The kitchen scored well below the living room, so it is not raised as well
        assert alternates == []

    def test_unrelated_rooms_are_not_alternates(self, combiner):
        """Two ordinary sensors in different rooms are not "both rooms"."""
        indicators = [
            _indicator("binary_sensor.office_motion", "office", hint="motion"),
            _indicator("binary_sensor.kitchen_motion", "kitchen", hint="motion"),
        ]

        _room, _c, _w, alternates = combiner.combine_with_alternates("unknown", 0.0, sensor_indicators=indicators)

        assert alternates == []

    def test_combine_keeps_its_three_value_result(self, combiner):
        result = combiner.combine("office", 0.8)
        assert len(result) == 3


def _coordinator(hass_states=(), room_entities=None):
    from custom_components.roomer.coordinator import DeviceTrackerHelper, LLMPresenceCoordinator
    from custom_components.roomer.habits import HabitPredictor

    with patch.object(LLMPresenceCoordinator, "__init__", lambda self: None):
        coord = LLMPresenceCoordinator()
    coord.rooms = ROOMS
    coord.room_entities = room_entities or {}
    coord.room_areas = {}
    coord.person_devices = {}
    coord.learning_enabled = False
    coord.device_tracker_helper = DeviceTrackerHelper()
    coord.device_room_locator = DeviceRoomLocator(ROOMS)
    coord.habit_predictor = MagicMock(spec=HabitPredictor)
    coord.habit_predictor.get_habit_hint.return_value = {}
    coord.habit_predictor.get_habit_context_for_prompt.return_value = ""
    coord.confidence_combiner = ConfidenceCombiner(DEFAULT_CONFIDENCE_WEIGHTS.copy())
    coord.event_logger = MagicMock()
    coord.event_logger.async_log_presence_event = AsyncMock()
    coord.event_logger.async_log_room_transition = AsyncMock()
    coord.provider = MagicMock()
    coord.provider.deduce_presence = AsyncMock(
        side_effect=lambda **_kw: PresenceGuess(
            room="bedroom", confidence=0.5, raw_response="ROOM: bedroom", indicators=["LLM"]
        )
    )
    coord.history_tracker = MagicMock()
    coord.notification_manager = MagicMock()
    coord._habits_dirty = False
    coord._previous_rooms = {}
    coord._last_clue = {}
    coord._reason_state = {}
    states = {s.entity_id: s for s in hass_states}
    coord.hass = MagicMock()
    coord.hass.states.get = states.get
    return coord


CAMERA_ENTRIES = {
    "kitchen": [{"entity_id": CAMERA_PERSON, "hint_type": "camera", "weight": 1.0, "detects": "person"}],
    "living_room": [{"entity_id": CAMERA_PERSON, "hint_type": "camera", "weight": 1.0, "detects": "person"}],
    "office": [{"entity_id": CAMERA_ANIMAL, "hint_type": "camera", "weight": 1.0, "detects": "animal"}],
}


class TestMultiRoomCamera:
    async def test_active_indicators_carry_weight_detects_and_shared(self):
        coord = _coordinator([State(CAMERA_PERSON, "on")], CAMERA_ENTRIES)

        active = coord._get_active_indicators({})

        assert sorted(i["room"] for i in active) == ["kitchen", "living_room"]
        assert all(i["shared"] and i["detects"] == "person" for i in active)

    async def test_one_camera_raises_both_rooms_for_a_person(self):
        coord = _coordinator([State(CAMERA_PERSON, "on")], CAMERA_ENTRIES)
        active = coord._get_active_indicators({})

        guess = await coord._process_entity("Ben", "person", {}, active)

        assert guess.source == "sensor"
        assert set(guess.rooms) == {"kitchen", "living_room"}

    async def test_person_detection_does_not_count_for_pets(self):
        coord = _coordinator([State(CAMERA_PERSON, "on")], CAMERA_ENTRIES)
        active = coord._get_active_indicators({})

        guess = await coord._process_entity("Max", "pet", {}, active, is_pet=True)

        # No clue applies to the pet, so only a prior remains
        assert guess.source == "prior"
        assert guess.alternate_rooms == []

    async def test_animal_detection_does_not_count_for_people(self):
        coord = _coordinator([State(CAMERA_ANIMAL, "on")], CAMERA_ENTRIES)
        active = coord._get_active_indicators({})

        person = await coord._process_entity("Ben", "person", {}, active)
        pet = await coord._process_entity("Max", "pet", {}, active, is_pet=True)

        assert person.source == "prior"
        assert (pet.source, pet.room) == ("sensor", "office")

    async def test_multi_room_entity_split_weight_lowers_confidence(self):
        full = _coordinator([State(CAMERA_PERSON, "on")], CAMERA_ENTRIES)
        split_entries = {room: [{**CAMERA_ENTRIES[room][0], "weight": 0.5}] for room in ("kitchen", "living_room")}
        split = _coordinator([State(CAMERA_PERSON, "on")], split_entries)

        full_guess = await full._process_entity("Ben", "person", {}, full._get_active_indicators({}))
        split_guess = await split._process_entity("Ben", "person", {}, split._get_active_indicators({}))

        assert split_guess.confidence < full_guess.confidence
        assert set(split_guess.rooms) == {"kitchen", "living_room"}

    async def test_single_room_config_behaves_as_before(self):
        entries = {"office": [{"entity_id": "binary_sensor.office_motion", "hint_type": "motion"}]}
        coord = _coordinator([State("binary_sensor.office_motion", "on")], entries)
        active = coord._get_active_indicators({})

        guess = await coord._process_entity("Ben", "person", {}, active)

        assert guess.room == "office"
        assert guess.alternate_rooms == []

    async def test_tie_keeps_the_previous_room(self):
        coord = _coordinator([State(CAMERA_PERSON, "on")], CAMERA_ENTRIES)
        coord._previous_rooms["Ben"] = "living_room"

        guess = await coord._process_entity("Ben", "person", {}, coord._get_active_indicators({}))

        assert guess.room == "living_room"
        assert guess.alternate_rooms == ["kitchen"]


class TestPriorAndSticky:
    async def test_quiet_house_is_an_explicit_low_confidence_prior(self):
        coord = _coordinator()

        guess = await coord._process_entity("Ben", "person", {}, [])

        assert guess.source == "prior"
        assert guess.indicators == [PRIOR_INDICATOR]
        assert guess.confidence <= PRIOR_MAX_CONFIDENCE
        assert guess.room == "bedroom"  # the LLM's guess is kept, honestly labelled
        assert not any(str(i).startswith("LLM") for i in guess.indicators)

    async def test_prior_confidence_is_capped_even_when_llm_is_sure(self):
        coord = _coordinator()
        coord.provider.deduce_presence.side_effect = lambda **_kw: PresenceGuess("bedroom", 1.0, "x", [])
        coord.habit_predictor.get_habit_hint.return_value = {"predicted_room": "bedroom", "confidence": 1.0}

        guess = await coord._process_entity("Ben", "person", {}, [])

        assert guess.source == "prior"
        assert guess.confidence <= PRIOR_MAX_CONFIDENCE

    async def test_active_clue_is_not_a_prior(self):
        entries = {"office": [{"entity_id": "binary_sensor.office_motion", "hint_type": "motion"}]}
        coord = _coordinator([State("binary_sensor.office_motion", "on")], entries)

        guess = await coord._process_entity("Ben", "person", {}, coord._get_active_indicators({}))

        assert guess.source == "sensor"
        assert PRIOR_INDICATOR not in guess.indicators

    async def test_recent_clue_makes_them_stay_where_last_seen(self):
        entries = {"office": [{"entity_id": "binary_sensor.office_motion", "hint_type": "motion"}]}
        coord = _coordinator([State("binary_sensor.office_motion", "on")], entries)
        first = await coord._process_entity("Ben", "person", {}, coord._get_active_indicators({}))
        coord.provider.deduce_presence.reset_mock()

        coord.hass.states.get = {}.get  # the motion sensor clears
        guess = await coord._process_entity("Ben", "person", {}, [])

        assert guess.room == "office"
        assert guess.source == "sticky"
        assert "Last seen in office" in guess.indicators[0]
        assert 0 < guess.confidence <= STICKY_MAX_CONFIDENCE
        assert first.source == "sensor"
        coord.provider.deduce_presence.assert_not_called()

    async def test_sticky_confidence_decays_with_time(self):
        coord = _coordinator()
        now = time.monotonic()
        coord._last_clue["Ben"] = ("office", 0.8, now - 60)
        soon = coord._sticky_guess("Ben")
        coord._last_clue["Ben"] = ("office", 0.8, now - STICKY_HALF_LIFE)
        later = coord._sticky_guess("Ben")

        assert soon.confidence > later.confidence
        assert later.confidence == pytest.approx(soon.confidence / 2, rel=0.1)

    async def test_sticky_expires_into_the_prior(self):
        coord = _coordinator()
        coord._last_clue["Ben"] = ("office", 0.9, time.monotonic() - STICKY_MAX_AGE - 10)

        guess = await coord._process_entity("Ben", "person", {}, [])

        assert guess.source == "prior"

    async def test_sticky_fades_out_when_too_weak(self):
        coord = _coordinator()
        coord._last_clue["Ben"] = ("office", 0.35, time.monotonic() - 3 * STICKY_HALF_LIFE)

        assert coord._sticky_guess("Ben") is None

    async def test_weak_clues_are_not_remembered(self):
        coord = _coordinator()
        coord._remember_clue("Ben", "office", 0.1)
        coord._remember_clue("Ben", "unknown", 0.9)
        coord._remember_clue("Ben", "away", 0.9)

        assert coord._last_clue == {}

    async def test_away_forgets_the_last_room(self):
        coord = _coordinator()
        coord.person_devices = {"Ben": ["device_tracker.ben_phone"]}
        coord._last_clue["Ben"] = ("office", 0.9, time.monotonic())
        coord.hass.states.get = {"device_tracker.ben_phone": State("device_tracker.ben_phone", "not_home")}.get

        guess = await coord._process_entity("Ben", "person", {}, [])

        assert guess.room == "away"
        assert "Ben" not in coord._last_clue

    async def test_correction_makes_them_stay(self):
        coord = _coordinator()
        coord.register_correction("Ben", "kitchen", 1.0)

        guess = await coord._process_entity("Ben", "person", {}, [])

        assert (guess.room, guess.source) == ("kitchen", "sticky")
        coord._annotate_change_reason("Ben", guess)
        assert guess.last_changed_reason == "manual_correction"

    async def test_other_sensors_beat_a_sticky_room(self):
        entries = {"kitchen": [{"entity_id": "binary_sensor.kitchen_motion", "hint_type": "motion"}]}
        coord = _coordinator([State("binary_sensor.kitchen_motion", "on")], entries)
        coord._last_clue["Ben"] = ("office", 0.9, time.monotonic())

        guess = await coord._process_entity("Ben", "person", {}, coord._get_active_indicators({}))

        assert (guess.room, guess.source) == ("kitchen", "sensor")


class TestLastChangedReason:
    def test_reason_is_set_on_change_and_kept_while_the_room_stays(self):
        coord = _coordinator()
        first = PresenceGuess("office", 0.8, "", ["motion: office_motion"], source="sensor")
        coord._annotate_change_reason("Ben", first)
        same = PresenceGuess("office", 0.8, "", ["media: tv"], source="sensor")
        coord._annotate_change_reason("Ben", same)
        moved = PresenceGuess("kitchen", 0.8, "", ["motion: kitchen_motion"], source="sensor")
        coord._annotate_change_reason("Ben", moved)

        assert first.last_changed_reason == "motion: office_motion"
        assert same.last_changed_reason == "motion: office_motion"
        assert moved.last_changed_reason == "motion: kitchen_motion"

    def test_falls_back_to_source_without_indicators(self):
        coord = _coordinator()
        guess = PresenceGuess("office", 0.9, "", [], source="device_room")
        coord._annotate_change_reason("Ben", guess)

        assert guess.last_changed_reason == "device_room"

    def test_unknown_is_not_a_change(self):
        coord = _coordinator()
        coord._annotate_change_reason("Ben", PresenceGuess("office", 0.9, "", ["motion: a"], source="sensor"))
        unknown = PresenceGuess("unknown", 0.0, "", [], source="prior")
        coord._annotate_change_reason("Ben", unknown)

        assert unknown.last_changed_reason == "motion: a"


class TestRoomAreaId:
    def test_configured_mapping_wins(self):
        coord = _coordinator()
        coord.room_areas = {"office": "study_area"}

        assert coord.area_id_for_room("office") == "study_area"

    def test_away_and_unknown_have_no_area(self):
        coord = _coordinator()
        coord.room_areas = {"away": "x"}

        assert coord.area_id_for_room("away") is None
        assert coord.area_id_for_room("unknown") is None
        assert coord.area_id_for_room(None) is None

    async def test_matches_an_area_by_name(self, hass):
        coord = _coordinator()
        coord.hass = hass
        area = ar.async_get(hass).async_create("Living Room")

        assert coord.area_id_for_room("living_room") == area.id
        assert coord.area_id_for_room("garage") is None


class TestSensorAttributes:
    def _sensor(self, guess, area="area_1"):
        from custom_components.roomer.sensor import LLMPresenceSensor

        coordinator = MagicMock()
        coordinator.data = {"persons": {"Ben": guess}, "pets": {}}
        coordinator.area_id_for_room.return_value = area
        return LLMPresenceSensor(coordinator, "Ben", "person")

    def test_attributes_for_homescape(self):
        guess = PresenceGuess(
            "office",
            0.82,
            "ROOM: office",
            ["motion: office_motion"],
            source="sensor",
            last_changed_reason="motion: office_motion",
        )

        attrs = self._sensor(guess).extra_state_attributes

        assert attrs["confidence"] == 0.82
        assert attrs["indicators"] == ["motion: office_motion"]
        assert attrs["source"] == "sensor"
        assert attrs["last_changed_reason"] == "motion: office_motion"
        assert attrs["room_area_id"] == "area_1"
        # Existing attributes are untouched
        assert attrs["raw_response"] == "ROOM: office"
        assert attrs["entity_type"] == "person"

    def test_room_area_id_is_none_when_unmapped(self):
        guess = PresenceGuess("office", 0.5, "", [])

        assert self._sensor(guess, area=None).extra_state_attributes["room_area_id"] is None

    def test_candidate_rooms_only_when_several(self):
        single = PresenceGuess("office", 0.5, "", [])
        multi = PresenceGuess("kitchen", 0.9, "", [], alternate_rooms=["living_room"])

        assert "candidate_rooms" not in self._sensor(single).extra_state_attributes
        assert self._sensor(multi).extra_state_attributes["candidate_rooms"] == ["kitchen", "living_room"]

    def test_occupants_and_binary_sensors_count_alternate_rooms(self):
        from custom_components.roomer.binary_sensor import LLMPresenceRoomBinarySensor
        from custom_components.roomer.sensor import RoomOccupantsSensor

        coordinator = MagicMock()
        coordinator.area_id_for_room.return_value = None
        coordinator.data = {
            "persons": {"Ben": PresenceGuess("kitchen", 0.9, "", [], alternate_rooms=["living_room"])},
            "pets": {},
        }

        assert RoomOccupantsSensor(coordinator, "living_room").native_value == 1
        assert RoomOccupantsSensor(coordinator, "kitchen").native_value == 1
        assert RoomOccupantsSensor(coordinator, "office").native_value == 0
        assert LLMPresenceRoomBinarySensor(coordinator, "Ben", "person", "living_room").is_on is True
        assert LLMPresenceRoomBinarySensor(coordinator, "Ben", "person", "office").is_on is False
