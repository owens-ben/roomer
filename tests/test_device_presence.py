"""Tests for room-level device presence and the room occupants sensors."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import State

from custom_components.roomer.const import (
    DEFAULT_CONFIDENCE_WEIGHTS,
    DEVICE_ROOM_CONFIDENCE,
    DEVICE_ROOM_SPLIT_CONFIDENCE,
    ENTITY_HINT_MOTION,
)
from custom_components.roomer.device_presence import (
    SOURCE_DEVICE_ROOM,
    DeviceRoomLocator,
    room_key,
    seen_since_away,
)
from custom_components.roomer.habits import ConfidenceCombiner
from custom_components.roomer.providers.base import PresenceGuess

ROOMS = ["office", "living_room", "bedroom", "kitchen", "kids-room"]
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


def make_state(entity_id, state, attributes=None, minutes_ago=None):
    """Build a real HA State, optionally with last_changed some minutes ago."""
    last_changed = NOW - timedelta(minutes=minutes_ago) if minutes_ago is not None else None
    return State(entity_id, state, attributes or {}, last_changed=last_changed)


def make_hass(*states):
    """Mock hass whose states.get returns the given states."""
    by_id = {s.entity_id: s for s in states}
    hass = MagicMock()
    hass.states.get = by_id.get
    return hass


class TestRoomKey:
    """Room and area names are compared loosely."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("Living Room", "living_room"),
            ("living_room", "living_room"),
            ("living-room", "living_room"),
            ("  Office ", "office"),
            ("Kid's Room", "kids_room"),
        ],
    )
    def test_room_key(self, value, expected):
        assert room_key(value) == expected


class TestDeviceRoomLocator:
    """Reading the room a device reports."""

    def test_area_sensor_state_matches_room(self):
        """Bermuda-style area sensor: state is the area name."""
        locator = DeviceRoomLocator(ROOMS)
        reading = locator.read(make_state("sensor.alice_phone_area", "Living Room", minutes_ago=3))

        assert reading.room == "living_room"
        assert reading.reported == "Living Room"
        assert reading.entity_id == "sensor.alice_phone_area"
        assert reading.last_changed == NOW - timedelta(minutes=3)

    def test_returns_the_configured_room_spelling(self):
        """A room configured with a dash still matches an area name with a space."""
        locator = DeviceRoomLocator(ROOMS)
        assert locator.read(make_state("sensor.kid_tablet_area", "Kids Room")).room == "kids-room"

    def test_device_tracker_with_room_state(self):
        """A device_tracker whose state is the room name."""
        locator = DeviceRoomLocator(ROOMS)
        assert locator.read(make_state("device_tracker.bob_watch", "kitchen")).room == "kitchen"

    @pytest.mark.parametrize("attribute", ["area_id", "area_name", "area", "room"])
    def test_room_from_attribute(self, attribute):
        """A home/away tracker carrying the room as an attribute."""
        locator = DeviceRoomLocator(ROOMS)
        state = make_state("device_tracker.alice_phone", "home", {attribute: "Office"})
        assert locator.read(state).room == "office"

    @pytest.mark.parametrize("value", ["unknown", "unavailable", "not_home", "home", "away", "on", "off", ""])
    def test_no_room_states(self, value):
        locator = DeviceRoomLocator(ROOMS)
        assert locator.read(make_state("sensor.alice_phone_area", value)) is None

    @pytest.mark.parametrize(
        "attributes",
        [{"source_type": "gps"}, {"source_type": "gps", "latitude": 51.5, "longitude": -0.1}, {"latitude": 51.5}],
    )
    def test_gps_zone_is_not_a_room(self, attributes, caplog):
        """A phone at a work zone named "Office" isn't in the office room at home."""
        locator = DeviceRoomLocator(ROOMS)
        assert locator.read(make_state("device_tracker.alice_phone", "Office", attributes)) is None
        assert not caplog.records

    def test_ble_tracker_with_source_type_is_a_room(self):
        locator = DeviceRoomLocator(ROOMS)
        state = make_state("device_tracker.bob_watch", "kitchen", {"source_type": "bluetooth_le"})
        assert locator.read(state).room == "kitchen"

    def test_away_and_unknown_are_never_rooms(self):
        """Even when the default room list includes them."""
        locator = DeviceRoomLocator(["office", "away", "unknown"])
        assert locator.match_room("away") is None
        assert locator.match_room("unknown") is None

    def test_unmatched_area_is_not_a_room(self):
        locator = DeviceRoomLocator(ROOMS)
        assert locator.read(make_state("sensor.alice_phone_area", "Master Bedroom")) is None

    def test_unmatched_area_warns_once(self, caplog):
        locator = DeviceRoomLocator(ROOMS)
        state = make_state("sensor.alice_phone_area", "Master Bedroom")

        locator.read(state)
        locator.read(state)

        warnings = [r for r in caplog.records if "Master Bedroom" in r.getMessage()]
        assert len(warnings) == 1
        assert "sensor.alice_phone_area" in warnings[0].getMessage()

    def test_other_personal_devices_do_not_warn(self, caplog):
        """A PC switch or battery sensor isn't a room tracker, so no warning."""
        locator = DeviceRoomLocator(ROOMS)
        locator.read(make_state("sensor.alice_phone_battery_state", "discharging"))
        locator.read(make_state("switch.alice_pc", "on"))
        assert not caplog.records

    def test_locate_skips_missing_and_non_room_entities(self):
        hass = make_hass(
            make_state("sensor.alice_phone_area", "Office"),
            make_state("switch.alice_pc", "on"),
            make_state("device_tracker.alice_phone", "home"),
        )
        locator = DeviceRoomLocator(ROOMS)

        readings = locator.locate(
            hass,
            ["sensor.alice_phone_area", "switch.alice_pc", "device_tracker.alice_phone", "sensor.missing"],
        )

        assert [r.entity_id for r in readings] == ["sensor.alice_phone_area"]


class TestDeviceRoomGuess:
    """Turning readings into a guess."""

    def _readings(self, *states):
        locator = DeviceRoomLocator(ROOMS)
        return locator, [locator.read(s) for s in states]

    def test_single_device(self):
        locator, readings = self._readings(make_state("sensor.alice_phone_area", "Office", minutes_ago=5))
        guess = locator.guess(readings)

        assert guess.room == "office"
        assert guess.confidence == DEVICE_ROOM_CONFIDENCE
        assert guess.source == SOURCE_DEVICE_ROOM
        assert guess.indicators == ["device: alice_phone_area in office"]
        assert "sensor.alice_phone_area reports Office" in guess.raw_response

    def test_devices_agree(self):
        locator, readings = self._readings(
            make_state("sensor.alice_phone_area", "Office", minutes_ago=5),
            make_state("sensor.alice_watch_area", "office", minutes_ago=2),
        )
        guess = locator.guess(readings)

        assert guess.room == "office"
        assert guess.confidence == DEVICE_ROOM_CONFIDENCE

    def test_devices_disagree_most_recent_wins(self):
        """Phone left on the desk, watch moved to the kitchen with its owner."""
        locator, readings = self._readings(
            make_state("sensor.alice_phone_area", "Office", minutes_ago=40),
            make_state("sensor.alice_watch_area", "Kitchen", minutes_ago=1),
        )
        guess = locator.guess(readings)

        assert guess.room == "kitchen"
        assert guess.confidence == DEVICE_ROOM_SPLIT_CONFIDENCE
        assert guess.indicators[0] == "device: alice_watch_area in kitchen"

    def test_majority_beats_recency(self):
        locator, readings = self._readings(
            make_state("sensor.alice_phone_area", "Office", minutes_ago=40),
            make_state("sensor.alice_watch_area", "Office", minutes_ago=30),
            make_state("sensor.alice_keys_area", "Kitchen", minutes_ago=1),
        )
        guess = locator.guess(readings)

        assert guess.room == "office"
        assert guess.confidence == DEVICE_ROOM_SPLIT_CONFIDENCE


class TestSeenSinceAway:
    """Resolving a home/away tracker that disagrees with a room tracker."""

    def test_room_reported_after_tracker_went_away(self):
        """Arriving home: Bluetooth sees the phone before Wi-Fi marks it home."""
        hass = make_hass(make_state("device_tracker.alice_wifi", "not_home", minutes_ago=300))
        locator = DeviceRoomLocator(ROOMS)
        readings = [locator.read(make_state("sensor.alice_phone_area", "Office", minutes_ago=1))]

        assert seen_since_away(hass, readings, ["device_tracker.alice_wifi"]) is True

    def test_tracker_went_away_after_room_reported(self):
        """Leaving home: the room sensor still shows the last room."""
        hass = make_hass(make_state("device_tracker.alice_wifi", "not_home", minutes_ago=2))
        locator = DeviceRoomLocator(ROOMS)
        readings = [locator.read(make_state("sensor.alice_phone_area", "Office", minutes_ago=90))]

        assert seen_since_away(hass, readings, ["device_tracker.alice_wifi"]) is False

    def test_unavailable_trackers_are_ignored(self):
        """A tracker that just went unavailable doesn't count as a recent departure."""
        hass = make_hass(
            make_state("device_tracker.alice_wifi", "not_home", minutes_ago=300),
            make_state("device_tracker.alice_router", "unavailable", minutes_ago=0),
        )
        locator = DeviceRoomLocator(ROOMS)
        readings = [locator.read(make_state("sensor.alice_phone_area", "Office", minutes_ago=1))]

        assert seen_since_away(hass, readings, ["device_tracker.alice_wifi", "device_tracker.alice_router"]) is True

    def test_without_timestamps_the_tracker_wins(self):
        tracker = MagicMock(entity_id="device_tracker.alice_wifi", state="not_home", last_changed=None)
        hass = make_hass(tracker)
        locator = DeviceRoomLocator(ROOMS)
        readings = [locator.read(make_state("sensor.alice_phone_area", "Office", minutes_ago=1))]

        assert seen_since_away(hass, readings, ["device_tracker.alice_wifi"]) is False
        assert seen_since_away(hass, [], ["device_tracker.alice_wifi"]) is False


@pytest.fixture
def coordinator(habit_predictor):
    """A coordinator with just the parts _process_entity needs."""
    from custom_components.roomer.coordinator import DeviceTrackerHelper, LLMPresenceCoordinator

    with patch.object(LLMPresenceCoordinator, "__init__", lambda self: None):
        coord = LLMPresenceCoordinator()
    coord.rooms = ROOMS
    coord.room_entities = {
        "kitchen": [{"entity_id": "binary_sensor.kitchen_motion", "hint_type": ENTITY_HINT_MOTION}],
    }
    coord.person_devices = {}
    coord.learning_enabled = True
    coord.device_tracker_helper = DeviceTrackerHelper()
    coord.device_room_locator = DeviceRoomLocator(ROOMS)
    coord.habit_predictor = habit_predictor
    coord.confidence_combiner = ConfidenceCombiner(DEFAULT_CONFIDENCE_WEIGHTS.copy())
    coord.event_logger = MagicMock()
    coord.event_logger.async_log_presence_event = AsyncMock()
    coord.event_logger.async_log_room_transition = AsyncMock()
    coord.provider = MagicMock()
    coord.provider.deduce_presence = AsyncMock(
        return_value=PresenceGuess(room="kitchen", confidence=0.6, raw_response="ROOM: kitchen", indicators=[])
    )
    coord.history_tracker = MagicMock()
    coord.notification_manager = MagicMock()
    coord._habits_dirty = False
    coord._previous_rooms = {}
    coord._last_clue = {}
    coord._reason_state = {}
    coord.hass = make_hass()
    return coord


class TestCoordinatorDevicePresence:
    """The coordinator places people and pets by their devices."""

    async def test_person_located_by_device_skips_llm(self, coordinator):
        coordinator.hass = make_hass(make_state("sensor.alice_phone_area", "Office", minutes_ago=5))
        coordinator.person_devices = {"Alice": ["sensor.alice_phone_area"]}

        guess = await coordinator._process_entity("Alice", "person", {}, [])

        assert guess.room == "office"
        assert guess.source == SOURCE_DEVICE_ROOM
        assert guess.confidence == DEVICE_ROOM_CONFIDENCE
        coordinator.provider.deduce_presence.assert_not_called()
        coordinator.event_logger.async_log_presence_event.assert_awaited_once()

    async def test_device_location_beats_shared_sensors(self, coordinator):
        """Motion in the kitchen doesn't pull Alice out of the room her phone is in."""
        coordinator.hass = make_hass(
            make_state("sensor.alice_phone_area", "Office", minutes_ago=5),
            make_state("binary_sensor.kitchen_motion", "on"),
        )
        coordinator.person_devices = {"Alice": ["sensor.alice_phone_area"]}
        active = [
            {"entity_id": "binary_sensor.kitchen_motion", "hint_type": "motion", "room": "kitchen", "state": "on"}
        ]

        guess = await coordinator._process_entity("Alice", "person", {}, active)

        assert guess.room == "office"

    async def test_person_without_room_device_uses_normal_pipeline(self, coordinator):
        coordinator.hass = make_hass(make_state("sensor.alice_phone_area", "unknown"))
        coordinator.person_devices = {"Alice": ["sensor.alice_phone_area"]}

        guess = await coordinator._process_entity("Alice", "person", {}, [])

        coordinator.provider.deduce_presence.assert_awaited_once()
        assert guess.source == "prior"  # no active clue, so only the LLM's time-of-day guess

    async def test_pet_located_by_tag(self, coordinator):
        coordinator.hass = make_hass(make_state("sensor.whiskers_tag_area", "Bedroom", minutes_ago=10))
        coordinator.person_devices = {"Whiskers": ["sensor.whiskers_tag_area"]}

        guess = await coordinator._process_entity("Whiskers", "pet", {}, [], is_pet=True)

        assert guess.room == "bedroom"
        coordinator.provider.deduce_presence.assert_not_called()

    async def test_device_location_is_learned(self, coordinator):
        coordinator.hass = make_hass(make_state("sensor.alice_phone_area", "Office", minutes_ago=5))
        coordinator.person_devices = {"Alice": ["sensor.alice_phone_area"]}

        await coordinator._process_entity("Alice", "person", {}, [])

        assert coordinator.habit_predictor.habits["Alice"]
        assert coordinator._habits_dirty is True

    async def test_device_location_fires_room_events(self, coordinator):
        """Arrival/departure/room-change events are fed from device locations too."""
        coordinator.hass = make_hass(make_state("sensor.alice_phone_area", "Office", minutes_ago=5))
        coordinator.person_devices = {"Alice": ["sensor.alice_phone_area"]}

        await coordinator._process_entity("Alice", "person", {}, [])

        coordinator.notification_manager.update_room.assert_called_once_with("Alice", "office", DEVICE_ROOM_CONFIDENCE)

    async def test_room_change_is_logged_as_transition(self, coordinator):
        coordinator.person_devices = {"Alice": ["sensor.alice_phone_area"]}
        coordinator.hass = make_hass(make_state("sensor.alice_phone_area", "Office", minutes_ago=5))
        await coordinator._process_entity("Alice", "person", {}, [])

        coordinator.hass = make_hass(make_state("sensor.alice_phone_area", "Kitchen", minutes_ago=0))
        await coordinator._process_entity("Alice", "person", {}, [])

        coordinator.event_logger.async_log_room_transition.assert_awaited_once_with(
            entity_name="Alice", from_room="office", to_room="kitchen", confidence=DEVICE_ROOM_CONFIDENCE
        )

    async def test_tracker_away_after_last_room_means_away(self, coordinator):
        """Left the house: Wi-Fi says away more recently than the room sensor changed."""
        coordinator.hass = make_hass(
            make_state("sensor.alice_phone_area", "Office", minutes_ago=90),
            make_state("device_tracker.alice_wifi", "not_home", minutes_ago=2),
        )
        coordinator.person_devices = {"Alice": ["sensor.alice_phone_area", "device_tracker.alice_wifi"]}

        guess = await coordinator._process_entity("Alice", "person", {}, [])

        assert guess.room == "away"
        assert guess.source == "device_tracker"

    async def test_room_seen_after_tracker_away_means_home(self, coordinator):
        """Just got home: Bluetooth sees the phone before Wi-Fi catches up."""
        coordinator.hass = make_hass(
            make_state("sensor.alice_phone_area", "Living Room", minutes_ago=1),
            make_state("device_tracker.alice_wifi", "not_home", minutes_ago=300),
        )
        coordinator.person_devices = {"Alice": ["sensor.alice_phone_area", "device_tracker.alice_wifi"]}

        guess = await coordinator._process_entity("Alice", "person", {}, [])

        assert guess.room == "living_room"
        assert guess.source == SOURCE_DEVICE_ROOM

    async def test_gps_tracker_at_office_zone_is_away(self, coordinator):
        """At a work zone called "Office": away, not in the office room."""
        coordinator.hass = make_hass(
            make_state("device_tracker.alice_phone", "Office", {"source_type": "gps", "latitude": 51.5}, minutes_ago=30)
        )
        coordinator.person_devices = {"Alice": ["device_tracker.alice_phone"]}

        guess = await coordinator._process_entity("Alice", "person", {}, [])

        assert guess.room == "away"
        coordinator.provider.deduce_presence.assert_not_called()

    async def test_room_named_device_tracker_is_not_away(self, coordinator):
        """A device_tracker whose state is a room used to count as 'not home'."""
        coordinator.hass = make_hass(make_state("device_tracker.bob_watch", "kitchen", minutes_ago=4))
        coordinator.person_devices = {"Bob": ["device_tracker.bob_watch"]}

        guess = await coordinator._process_entity("Bob", "person", {}, [])

        assert guess.room == "kitchen"
        assert guess.source == SOURCE_DEVICE_ROOM


class TestRoomOccupantsSensor:
    """Who is in each room right now."""

    @pytest.fixture
    def data_coordinator(self):
        coordinator = MagicMock()
        coordinator.rooms = ["office", "living_room", "kitchen", "away", "unknown"]
        coordinator.area_id_for_room.return_value = None
        coordinator.persons = [{"name": "Alice"}, {"name": "Bob"}, {"name": "Carol"}]
        coordinator.pets = [{"name": "Whiskers"}]
        coordinator.data = {
            "persons": {
                "Alice": PresenceGuess("office", 0.9, "", [], source="device_room"),
                "Bob": PresenceGuess("office", 0.62, "", [], source="llm"),
                "Carol": PresenceGuess("away", 0.95, "", [], source="device_tracker"),
            },
            "pets": {
                "Whiskers": PresenceGuess("living_room", 0.4, "", []),
            },
        }
        return coordinator

    def test_names_and_ids(self, data_coordinator):
        from custom_components.roomer.sensor import RoomOccupantsSensor

        sensor = RoomOccupantsSensor(data_coordinator, "living_room")

        assert sensor._attr_name == "Living Room Occupants"
        assert sensor._attr_unique_id == "roomer_room_living_room_occupants"

    def test_counts_people_and_lists_names(self, data_coordinator):
        from custom_components.roomer.sensor import RoomOccupantsSensor

        sensor = RoomOccupantsSensor(data_coordinator, "office")

        assert sensor.native_value == 2
        assert sensor.extra_state_attributes == {
            "people": ["Alice", "Bob"],
            "pets": [],
            "confidence": {"Alice": 0.9, "Bob": 0.62},
            "sources": {"Alice": "device_room", "Bob": "llm"},
            "room_area_id": None,
        }

    def test_pet_alone_is_zero_people(self, data_coordinator):
        from custom_components.roomer.sensor import RoomOccupantsSensor

        sensor = RoomOccupantsSensor(data_coordinator, "living_room")

        assert sensor.native_value == 0
        assert sensor.extra_state_attributes["pets"] == ["Whiskers"]

    def test_empty_room(self, data_coordinator):
        from custom_components.roomer.sensor import RoomOccupantsSensor

        sensor = RoomOccupantsSensor(data_coordinator, "kitchen")

        assert sensor.native_value == 0
        assert sensor.extra_state_attributes["people"] == []

    def test_no_data_yet(self, data_coordinator):
        from custom_components.roomer.sensor import RoomOccupantsSensor

        data_coordinator.data = None
        sensor = RoomOccupantsSensor(data_coordinator, "office")

        assert sensor.native_value is None
        assert sensor.extra_state_attributes == {}

    async def test_one_sensor_per_real_room(self, data_coordinator):
        """No occupants sensor for the 'away' and 'unknown' pseudo-rooms."""
        from custom_components.roomer.sensor import RoomOccupantsSensor, async_setup_entry

        hass = MagicMock()
        hass.data = {"roomer": {"entry": data_coordinator}}
        entry = MagicMock()
        entry.entry_id = "entry"
        added = []

        await async_setup_entry(hass, entry, added.extend)

        rooms = [e._room for e in added if isinstance(e, RoomOccupantsSensor)]
        assert rooms == ["office", "living_room", "kitchen"]

    def test_person_sensor_reports_source(self, data_coordinator):
        from custom_components.roomer.sensor import LLMPresenceSensor

        sensor = LLMPresenceSensor(data_coordinator, "Alice", "person")

        assert sensor.extra_state_attributes["source"] == "device_room"
