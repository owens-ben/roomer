"""Options flow for multi-room entities and room areas, config entry migration, and executor use."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roomer import async_migrate_entry
from custom_components.roomer.config_flow import LLMPresenceConfigFlow
from custom_components.roomer.const import (
    CONF_ROOM_AREAS,
    CONF_ROOM_ENTITIES,
    CONF_ROOMS,
    DOMAIN,
)

DATA = {
    "provider": "ollama",
    "url": "http://localhost:11434",
    "model": "llama3.2",
    CONF_ROOMS: ["office", "kitchen", "living_room"],
    "persons": [{"name": "Ben"}],
    "pets": [],
    CONF_ROOM_ENTITIES: {
        "office": [{"entity_id": "binary_sensor.office_motion", "hint_type": "motion"}],
    },
}


@pytest.fixture
async def entry(hass, enable_custom_integrations):
    entry = MockConfigEntry(domain=DOMAIN, version=2, data=DATA)
    entry.add_to_hass(hass)
    hass.states.async_set("binary_sensor.office_motion", "off")
    hass.states.async_set(
        "binary_sensor.reolink_person", "off", {"device_class": "motion", "friendly_name": "Reolink Person"}
    )
    hass.states.async_set("binary_sensor.presence_living_room", "off", {"device_class": "presence"})
    return entry


async def _submit(hass, entry, step, user_input):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": step})
    assert result["step_id"] == step
    return await hass.config_entries.options.async_configure(result["flow_id"], user_input)


class TestMultiRoomStep:
    async def test_menu_offers_the_new_steps(self, hass, entry):
        result = await hass.config_entries.options.async_init(entry.entry_id)

        assert "multi_room" in result["menu_options"]
        assert "room_areas" in result["menu_options"]

    async def test_entity_is_stored_under_every_chosen_room(self, hass, entry):
        result = await _submit(
            hass,
            entry,
            "multi_room",
            {"entity_id": "binary_sensor.reolink_person", "rooms": ["kitchen", "living_room"]},
        )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        stored = entry.options[CONF_ROOM_ENTITIES]
        for room in ("kitchen", "living_room"):
            assert stored[room] == [
                {"entity_id": "binary_sensor.reolink_person", "hint_type": "camera", "weight": 1.0, "detects": "person"}
            ]
        # Existing mappings are kept
        assert stored["office"][0]["entity_id"] == "binary_sensor.office_motion"

    async def test_split_weight_shares_the_evidence(self, hass, entry):
        await _submit(
            hass,
            entry,
            "multi_room",
            {"entity_id": "binary_sensor.reolink_person", "rooms": ["kitchen", "living_room"], "split_weight": True},
        )

        stored = entry.options[CONF_ROOM_ENTITIES]
        assert stored["kitchen"][0]["weight"] == 0.5
        assert stored["living_room"][0]["weight"] == 0.5

    async def test_detects_can_be_set(self, hass, entry):
        await _submit(
            hass,
            entry,
            "multi_room",
            {"entity_id": "binary_sensor.reolink_person", "rooms": ["kitchen"], "detects": "animal"},
        )

        assert entry.options[CONF_ROOM_ENTITIES]["kitchen"][0]["detects"] == "animal"

    async def test_device_class_types_the_entity(self, hass, entry):
        await _submit(
            hass, entry, "multi_room", {"entity_id": "binary_sensor.presence_living_room", "rooms": ["living_room"]}
        )

        assert entry.options[CONF_ROOM_ENTITIES]["living_room"][0]["hint_type"] == "motion"

    async def test_remapping_replaces_the_old_rooms(self, hass, entry):
        await _submit(
            hass,
            entry,
            "multi_room",
            {"entity_id": "binary_sensor.reolink_person", "rooms": ["kitchen", "living_room"]},
        )
        await _submit(hass, entry, "multi_room", {"entity_id": "binary_sensor.reolink_person", "rooms": ["kitchen"]})

        stored = entry.options[CONF_ROOM_ENTITIES]
        assert "living_room" not in stored
        assert [e["entity_id"] for e in stored["kitchen"]] == ["binary_sensor.reolink_person"]

    async def test_no_rooms_removes_the_entity(self, hass, entry):
        await _submit(hass, entry, "multi_room", {"entity_id": "binary_sensor.office_motion", "rooms": []})

        assert "office" not in entry.options[CONF_ROOM_ENTITIES]

    async def test_missing_entity_is_an_error(self, hass, entry):
        result = await _submit(hass, entry, "multi_room", {"entity_id": "binary_sensor.nope", "rooms": ["kitchen"]})

        assert result["type"] == FlowResultType.FORM
        assert result["errors"] == {"entity_id": "entity_not_found"}

    async def test_per_room_step_keeps_weight_and_detects_of_unchanged_entities(self, hass, entry):
        await _submit(
            hass,
            entry,
            "multi_room",
            {"entity_id": "binary_sensor.reolink_person", "rooms": ["kitchen", "living_room"], "split_weight": True},
        )

        await _submit(
            hass,
            entry,
            "room_entities",
            {"office": ["binary_sensor.office_motion"], "kitchen": ["binary_sensor.reolink_person"]},
        )

        kitchen = entry.options[CONF_ROOM_ENTITIES]["kitchen"][0]
        assert (kitchen["weight"], kitchen["detects"]) == (0.5, "person")


class TestRoomAreasStep:
    async def test_areas_are_saved_per_room(self, hass, entry):
        result = await _submit(hass, entry, "room_areas", {"office": "study", "kitchen": "kitchen_area"})

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert entry.options[CONF_ROOM_AREAS] == {"office": "study", "kitchen": "kitchen_area"}

    async def test_clearing_a_room_removes_its_area(self, hass, entry):
        await _submit(hass, entry, "room_areas", {"office": "study", "kitchen": "kitchen_area"})
        await _submit(hass, entry, "room_areas", {"kitchen": "kitchen_area"})

        assert entry.options[CONF_ROOM_AREAS] == {"kitchen": "kitchen_area"}

    async def test_form_suggests_the_saved_area(self, hass, entry):
        await _submit(hass, entry, "room_areas", {"office": "study"})
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "room_areas"})

        suggested = {str(k): k.description["suggested_value"] for k in result["data_schema"].schema}
        assert suggested["office"] == "study"


class TestMigration:
    async def test_version_2_single_room_config_is_migrated(self, hass):
        legacy = MockConfigEntry(
            domain=DOMAIN,
            version=2,
            data={
                **DATA,
                CONF_ROOM_ENTITIES: {
                    "office": [{"entity_id": "binary_sensor.office_motion", "hint_type": "motion"}],
                    "kitchen": ["binary_sensor.kitchen_motion"],
                },
            },
            options={CONF_ROOM_ENTITIES: {"office": [{"entity_id": "switch.office_pc", "hint_type": "computer"}]}},
        )
        legacy.add_to_hass(hass)

        assert await async_migrate_entry(hass, legacy) is True

        assert legacy.version == LLMPresenceConfigFlow.VERSION == 3
        assert legacy.data[CONF_ROOM_ENTITIES]["office"] == [
            {"entity_id": "binary_sensor.office_motion", "hint_type": "motion", "weight": 1.0, "detects": "any"}
        ]
        assert legacy.data[CONF_ROOM_ENTITIES]["kitchen"][0]["hint_type"] == "motion"
        assert legacy.options[CONF_ROOM_ENTITIES]["office"][0]["weight"] == 1.0

    async def test_current_version_is_left_alone(self, hass):
        current = MockConfigEntry(domain=DOMAIN, version=3, data=DATA)
        current.add_to_hass(hass)

        assert await async_migrate_entry(hass, current) is True
        assert current.data[CONF_ROOM_ENTITIES] == DATA[CONF_ROOM_ENTITIES]

    async def test_newer_version_is_refused(self, hass):
        future = MockConfigEntry(domain=DOMAIN, version=4, data=DATA)
        future.add_to_hass(hass)

        assert await async_migrate_entry(hass, future) is False


class TestFileIoOffTheEventLoop:
    """Setup builds the file-backed components in the executor (HA's blocking-call warnings)."""

    async def test_setup_builds_and_cleans_up_in_the_executor(self):
        from custom_components.roomer import async_setup_entry

        hass = MagicMock()
        hass.data = {}
        hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
        hass.services.has_service = MagicMock(return_value=False)
        hass.config_entries.async_forward_entry_setups = AsyncMock()
        entry = MagicMock()
        entry.entry_id = "e1"
        entry.data = {"persons": [], "pets": []}
        entry.options = {}

        with (
            patch("custom_components.roomer.LLMPresenceCoordinator") as coord_cls,
            patch("custom_components.roomer.EventLogger") as logger_cls,
            patch("custom_components.roomer.HabitPredictor") as habits_cls,
            patch("custom_components.roomer.HistoryTracker") as history_cls,
            patch("custom_components.roomer.VisionIdentifier"),
            patch("custom_components.roomer.CameraTrackingController"),
        ):
            coord_cls.return_value.async_config_entry_first_refresh = AsyncMock()
            logger_cls.return_value.cleanup = MagicMock(return_value={})
            await async_setup_entry(hass, entry)

        executed = [call.args[0] for call in hass.async_add_executor_job.await_args_list]
        assert habits_cls in executed
        assert history_cls in executed
        assert logger_cls.return_value.cleanup in executed
        # The EventLogger is built through functools.partial
        assert any(getattr(f, "func", None) is logger_cls for f in executed)
        # The coordinator got the pre-built tracker instead of creating its own in the loop
        assert coord_cls.call_args.kwargs["history_tracker"] is history_cls.return_value
        # Nothing was constructed directly on the loop
        habits_cls.assert_called_once_with()
        history_cls.assert_called_once_with()

    async def test_cleanup_storage_service_runs_in_the_executor(self):
        from custom_components.roomer.const import DOMAIN
        from custom_components.roomer.services import async_handle_cleanup_storage

        hass = MagicMock()
        event_logger = MagicMock()
        event_logger.cleanup = MagicMock(return_value={"total_deleted": 1})
        hass.data = {DOMAIN: {"event_logger": event_logger}}
        hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
        call = MagicMock()
        call.data = {}

        await async_handle_cleanup_storage(hass, call)

        hass.async_add_executor_job.assert_awaited_once_with(event_logger.cleanup)
