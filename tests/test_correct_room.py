"""correct_room: the person comes from Roomer's configuration, and the room is validated."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from custom_components.roomer.const import DOMAIN, presence_sensor_unique_id
from custom_components.roomer.habits import HabitPredictor
from custom_components.roomer.services import (
    async_handle_correct_room,
    resolve_tracked_entity,
    validate_room,
)

ROOMS = ["office", "living_room", "kitchen"]


@pytest.fixture
def coordinator(hass, tmp_path):
    """A stand-in coordinator for two people (one with a space in the name) and a pet."""
    coord = MagicMock()
    coord.persons = [{"name": "Ben"}, {"name": "Mary Jane"}]
    coord.pets = [{"name": "Max"}]
    coord.rooms = ROOMS
    coord.habit_predictor = HabitPredictor(config_path=tmp_path)
    coord.area_id_for_room.side_effect = lambda room: {"office": "office_area"}.get(room)
    hass.data.setdefault(DOMAIN, {})["entry1"] = coord
    return coord


def _register(hass, entity_type, name, object_id):
    return er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        presence_sensor_unique_id(entity_type, name),
        suggested_object_id=object_id,
    )


def _call(entity_id, room, confidence=1.0):
    call = MagicMock()
    call.data = {"entity_id": entity_id, "room": room, "confidence": confidence}
    return call


class TestResolveTrackedEntity:
    async def test_renamed_entity_id_resolves_through_unique_id(self, hass, coordinator):
        """sensor.ben_room_3 is Ben, not "Ben 3"."""
        entry = _register(hass, "person", "Ben", "ben_room_3")
        assert entry.entity_id == "sensor.ben_room_3"

        _coord, name, entity_type = resolve_tracked_entity(hass, "sensor.ben_room_3")

        assert (name, entity_type) == ("Ben", "person")

    async def test_name_with_space_and_arbitrary_entity_id(self, hass, coordinator):
        _register(hass, "person", "Mary Jane", "mj_upstairs")

        _coord, name, _type = resolve_tracked_entity(hass, "sensor.mj_upstairs")

        assert name == "Mary Jane"

    async def test_pet(self, hass, coordinator):
        _register(hass, "pet", "Max", "max_room")

        assert resolve_tracked_entity(hass, "sensor.max_room")[1:] == ("Max", "pet")

    async def test_without_registry_entry_matches_configured_names(self, hass, coordinator):
        """Backward compatible: sensor.ben_room works even when the registry has no entry."""
        assert resolve_tracked_entity(hass, "sensor.ben_room")[1] == "Ben"
        assert resolve_tracked_entity(hass, "sensor.ben_room_2")[1] == "Ben"
        assert resolve_tracked_entity(hass, "sensor.mary_jane_room")[1] == "Mary Jane"

    async def test_unknown_entity_is_rejected(self, hass, coordinator):
        with pytest.raises(ServiceValidationError, match="not the room sensor"):
            resolve_tracked_entity(hass, "sensor.kitchen_temperature")

    async def test_other_roomer_entity_is_rejected(self, hass, coordinator):
        er.async_get(hass).async_get_or_create(
            "sensor", DOMAIN, "roomer_room_office_occupants", suggested_object_id="office_occupants"
        )
        with pytest.raises(ServiceValidationError):
            resolve_tracked_entity(hass, "sensor.office_occupants")

    async def test_no_coordinator_returns_none(self, hass):
        assert resolve_tracked_entity(hass, "sensor.ben_room") is None


class TestCorrectRoomLearnsUnderConfiguredName:
    async def test_habit_goes_under_configured_name_not_entity_id(self, hass, coordinator):
        _register(hass, "person", "Ben", "ben_room_3")
        hass.states.async_set("sensor.ben_room_3", "kitchen", {"entity_type": "person"})

        await async_handle_correct_room(hass, _call("sensor.ben_room_3", "office"))

        assert "Ben" in coordinator.habit_predictor.habits
        assert "Ben 3" not in coordinator.habit_predictor.habits
        coordinator.register_correction.assert_called_once_with("Ben", "office", 1.0)
        state = hass.states.get("sensor.ben_room_3")
        assert state.state == "office"
        assert state.attributes["source"] == "manual_correction"
        assert state.attributes["last_changed_reason"] == "manual_correction"
        assert state.attributes["room_area_id"] == "office_area"
        assert state.attributes["indicators"] == ["User corrected"]

    async def test_room_is_canonicalised(self, hass, coordinator):
        _register(hass, "person", "Ben", "ben_room")
        hass.states.async_set("sensor.ben_room", "kitchen")

        await async_handle_correct_room(hass, _call("sensor.ben_room", "Living Room"))

        assert hass.states.get("sensor.ben_room").state == "living_room"


class TestRoomValidation:
    async def test_invalid_room_raises_and_changes_nothing(self, hass, coordinator):
        _register(hass, "person", "Ben", "ben_room")
        hass.states.async_set("sensor.ben_room", "kitchen")

        with pytest.raises(ServiceValidationError, match="garage") as err:
            await async_handle_correct_room(hass, _call("sensor.ben_room", "garage"))

        assert "office, living_room, kitchen, away, unknown" in str(err.value)
        assert hass.states.get("sensor.ben_room").state == "kitchen"
        assert coordinator.habit_predictor.habits == {}
        coordinator.register_correction.assert_not_called()

    @pytest.mark.parametrize("room", ["away", "unknown", "AWAY"])
    async def test_away_and_unknown_are_always_valid(self, hass, coordinator, room):
        _register(hass, "person", "Ben", "ben_room")
        hass.states.async_set("sensor.ben_room", "kitchen")

        await async_handle_correct_room(hass, _call("sensor.ben_room", room))

        assert hass.states.get("sensor.ben_room").state == room.lower()

    def test_validate_room_ignores_case_and_spaces(self):
        assert validate_room("Living-Room", ROOMS) == "living_room"
        assert validate_room("KITCHEN", ROOMS) == "kitchen"

    def test_validate_room_rejects_unknown(self):
        with pytest.raises(ServiceValidationError):
            validate_room("garage", ROOMS)
