"""Tests for Roomer config flow."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import State
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roomer.const import (
    CONF_CONFIDENCE_WEIGHTS,
    CONF_LEARNING_ENABLED,
    CONF_MODEL,
    CONF_PERSON_DEVICES,
    CONF_PERSONS,
    CONF_PETS,
    CONF_POLL_INTERVAL,
    CONF_PROVIDER,
    CONF_ROOM_ENTITIES,
    CONF_ROOMS,
    CONF_TIMEOUT,
    CONF_URL,
    DEFAULT_CONFIDENCE_WEIGHTS,
    DOMAIN,
    VALID_ROOMS,
)


@pytest.fixture
def mock_setup_entry():
    """Override async_setup_entry."""
    with patch(
        "custom_components.roomer.async_setup_entry",
        return_value=True,
    ) as mock_setup:
        yield mock_setup


class TestConfigFlowUserStep:
    """Test the user step of config flow."""

    @pytest.mark.asyncio
    async def test_user_step_shows_form(self):
        """Test that user step shows the provider configuration form."""
        from custom_components.roomer.config_flow import LLMPresenceConfigFlow

        flow = LLMPresenceConfigFlow()
        flow.hass = MagicMock()

        result = await flow.async_step_user(user_input=None)

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert CONF_PROVIDER in result["data_schema"].schema
        assert CONF_URL in result["data_schema"].schema

    @pytest.mark.asyncio
    async def test_user_step_connection_failure(self):
        """Test error handling when provider connection fails."""
        from custom_components.roomer.config_flow import LLMPresenceConfigFlow

        flow = LLMPresenceConfigFlow()
        flow.hass = MagicMock()

        with patch("custom_components.roomer.config_flow.get_provider") as mock_get:
            mock_provider = MagicMock()
            mock_provider.test_connection = AsyncMock(return_value=False)
            mock_get.return_value = mock_provider

            result = await flow.async_step_user(
                user_input={
                    CONF_PROVIDER: "ollama",
                    CONF_URL: "http://localhost:11434",
                    CONF_POLL_INTERVAL: 30,
                }
            )

        assert result["type"] == FlowResultType.FORM
        assert result["errors"]["base"] == "cannot_connect"

    @pytest.mark.asyncio
    async def test_user_step_success_proceeds_to_model(self):
        """Test successful connection proceeds to model selection."""
        from custom_components.roomer.config_flow import LLMPresenceConfigFlow

        flow = LLMPresenceConfigFlow()
        flow.hass = MagicMock()

        with patch("custom_components.roomer.config_flow.get_provider") as mock_get:
            mock_provider = MagicMock()
            mock_provider.test_connection = AsyncMock(return_value=True)
            mock_provider.get_available_models = AsyncMock(return_value=["llama3.2", "mistral"])
            mock_get.return_value = mock_provider

            result = await flow.async_step_user(
                user_input={
                    CONF_PROVIDER: "ollama",
                    CONF_URL: "http://localhost:11434",
                    CONF_POLL_INTERVAL: 30,
                }
            )

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "model"


class TestConfigFlowModelStep:
    """Test the model selection step."""

    @pytest.mark.asyncio
    async def test_model_step_shows_available_models(self):
        """Test that model step shows available models."""
        from custom_components.roomer.config_flow import LLMPresenceConfigFlow

        flow = LLMPresenceConfigFlow()
        flow.hass = MagicMock()
        flow._data = {CONF_PROVIDER: "ollama", CONF_URL: "http://localhost:11434"}
        flow._available_models = ["llama3.2", "mistral", "codellama"]

        result = await flow.async_step_model(user_input=None)

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "model"
        assert CONF_MODEL in result["data_schema"].schema

    @pytest.mark.asyncio
    async def test_model_step_proceeds_to_rooms(self):
        """Test selecting model proceeds to room configuration."""
        from custom_components.roomer.config_flow import LLMPresenceConfigFlow

        flow = LLMPresenceConfigFlow()
        flow.hass = MagicMock()
        flow._data = {CONF_PROVIDER: "ollama", CONF_URL: "http://localhost:11434"}
        flow._available_models = ["llama3.2"]

        result = await flow.async_step_model(user_input={CONF_MODEL: "llama3.2"})

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "rooms"


class TestConfigFlowRoomsStep:
    """Test the rooms configuration step."""

    @pytest.mark.asyncio
    async def test_rooms_step_shows_form(self):
        """Test that rooms step shows room selection form."""
        from custom_components.roomer.config_flow import LLMPresenceConfigFlow

        flow = LLMPresenceConfigFlow()
        flow.hass = MagicMock()
        flow._data = {
            CONF_PROVIDER: "ollama",
            CONF_URL: "http://localhost:11434",
            CONF_MODEL: "llama3.2",
        }

        result = await flow.async_step_rooms(user_input=None)

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "rooms"
        assert CONF_ROOMS in result["data_schema"].schema

    @pytest.mark.asyncio
    async def test_rooms_step_requires_at_least_one_room(self):
        """Test that at least one room must be selected."""
        from custom_components.roomer.config_flow import LLMPresenceConfigFlow

        flow = LLMPresenceConfigFlow()
        flow.hass = MagicMock()
        flow._data = {
            CONF_PROVIDER: "ollama",
            CONF_URL: "http://localhost:11434",
            CONF_MODEL: "llama3.2",
        }

        result = await flow.async_step_rooms(user_input={CONF_ROOMS: [], "custom_rooms": ""})

        assert result["type"] == FlowResultType.FORM
        assert result["errors"]["base"] == "at_least_one_room"

    @pytest.mark.asyncio
    async def test_rooms_step_accepts_custom_rooms(self):
        """Test that custom rooms can be added."""
        from custom_components.roomer.config_flow import LLMPresenceConfigFlow

        flow = LLMPresenceConfigFlow()
        flow.hass = MagicMock()
        flow._data = {
            CONF_PROVIDER: "ollama",
            CONF_URL: "http://localhost:11434",
            CONF_MODEL: "llama3.2",
        }

        result = await flow.async_step_rooms(user_input={CONF_ROOMS: ["office"], "custom_rooms": "garage, basement"})

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "persons"
        assert "garage" in flow._data[CONF_ROOMS]
        assert "basement" in flow._data[CONF_ROOMS]


class TestConfigFlowPersonsStep:
    """Test the persons configuration step."""

    @pytest.mark.asyncio
    async def test_persons_step_shows_form(self):
        """Test that persons step shows person/pet input form."""
        from custom_components.roomer.config_flow import LLMPresenceConfigFlow

        flow = LLMPresenceConfigFlow()
        flow.hass = MagicMock()
        flow._data = {
            CONF_PROVIDER: "ollama",
            CONF_URL: "http://localhost:11434",
            CONF_MODEL: "llama3.2",
            CONF_ROOMS: ["office", "bedroom"],
        }

        result = await flow.async_step_persons(user_input=None)

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "persons"
        assert CONF_PERSONS in result["data_schema"].schema
        assert CONF_PETS in result["data_schema"].schema

    @pytest.mark.asyncio
    async def test_persons_step_requires_at_least_one_entity(self):
        """Test that at least one person or pet is required."""
        from custom_components.roomer.config_flow import LLMPresenceConfigFlow

        flow = LLMPresenceConfigFlow()
        flow.hass = MagicMock()
        flow._data = {
            CONF_PROVIDER: "ollama",
            CONF_URL: "http://localhost:11434",
            CONF_MODEL: "llama3.2",
            CONF_ROOMS: ["office", "bedroom"],
        }

        result = await flow.async_step_persons(user_input={CONF_PERSONS: "", CONF_PETS: ""})

        assert result["type"] == FlowResultType.FORM
        assert result["errors"]["base"] == "at_least_one_entity"

    @pytest.mark.asyncio
    async def test_persons_step_parses_comma_separated_names(self):
        """Test that comma-separated names are parsed correctly."""
        from custom_components.roomer.config_flow import LLMPresenceConfigFlow

        flow = LLMPresenceConfigFlow()
        flow.hass = MagicMock()
        flow._data = {
            CONF_PROVIDER: "ollama",
            CONF_URL: "http://localhost:11434",
            CONF_MODEL: "llama3.2",
            CONF_ROOMS: ["office", "bedroom"],
        }

        result = await flow.async_step_persons(user_input={CONF_PERSONS: "Alice, Bob", CONF_PETS: "Whiskers"})

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "room_entities"
        assert flow._data[CONF_PERSONS] == [{"name": "Alice"}, {"name": "Bob"}]
        assert flow._data[CONF_PETS] == [{"name": "Whiskers"}]


class TestConfigFlowRoomEntitiesStep:
    """Test the room entities mapping step."""

    @pytest.mark.asyncio
    async def test_room_entities_step_creates_entry(self):
        """Test that room entities step creates config entry."""
        from custom_components.roomer.config_flow import LLMPresenceConfigFlow

        flow = LLMPresenceConfigFlow()
        flow.hass = MagicMock()
        flow.hass.states.get.return_value = State("switch.any", "off")
        flow._data = {
            CONF_PROVIDER: "ollama",
            CONF_URL: "http://localhost:11434",
            CONF_MODEL: "llama3.2",
            CONF_ROOMS: ["office", "bedroom"],
            CONF_PERSONS: [{"name": "Alice"}],
            CONF_PETS: [],
        }

        # Simulate entity selection
        result = await flow.async_step_room_entities(
            user_input={
                "office": ["switch.office_pc", "binary_sensor.office_motion"],
                "bedroom": [],
            }
        )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "Roomer (ollama)"
        assert CONF_ROOM_ENTITIES in result["data"]
        assert CONF_LEARNING_ENABLED in result["data"]


class TestGuessEntityHint:
    """Test the entity hint type guessing logic."""

    def test_guess_motion_sensor(self):
        """Test guessing motion sensor hint type."""
        from custom_components.roomer.config_flow import _guess_entity_hint

        assert _guess_entity_hint("binary_sensor.office_motion") == "motion"
        assert _guess_entity_hint("binary_sensor.living_room_occupancy") == "motion"

    def test_guess_media_player(self):
        """Test guessing media player hint type."""
        from custom_components.roomer.config_flow import _guess_entity_hint

        assert _guess_entity_hint("media_player.living_room_tv") == "media"

    def test_guess_light(self):
        """Test guessing light hint type."""
        from custom_components.roomer.config_flow import _guess_entity_hint

        assert _guess_entity_hint("light.office_light") == "light"

    def test_guess_computer(self):
        """Test guessing computer hint type."""
        from custom_components.roomer.config_flow import _guess_entity_hint

        assert _guess_entity_hint("switch.office_pc") == "computer"
        assert _guess_entity_hint("switch.desktop_computer") == "computer"

    def test_guess_camera(self):
        """Test guessing camera hint type."""
        from custom_components.roomer.config_flow import _guess_entity_hint

        assert _guess_entity_hint("camera.living_room_camera") == "camera"
        assert _guess_entity_hint("binary_sensor.person_detected") == "camera"

    def test_guess_door_sensor(self):
        """Test guessing door/window sensor hint type."""
        from custom_components.roomer.config_flow import _guess_entity_hint

        assert _guess_entity_hint("binary_sensor.front_door") == "door"
        assert _guess_entity_hint("binary_sensor.bedroom_window") == "door"
        assert _guess_entity_hint("binary_sensor.contact_sensor") == "door"

    def test_guess_device_tracker(self):
        """Test guessing device tracker hint type."""
        from custom_components.roomer.config_flow import _guess_entity_hint

        assert _guess_entity_hint("device_tracker.alice_phone") == "presence"

    def test_guess_unknown_defaults_to_appliance(self):
        """Test that unknown entities default to appliance hint type."""
        from custom_components.roomer.config_flow import _guess_entity_hint

        assert _guess_entity_hint("switch.random_switch") == "appliance"
        assert _guess_entity_hint("sensor.unknown_sensor") == "appliance"


OPTIONS_ENTRY_DATA = {
    CONF_PROVIDER: "ollama",
    CONF_URL: "http://localhost:11434",
    CONF_MODEL: "llama3.2",
    CONF_POLL_INTERVAL: 30,
    CONF_ROOMS: ["office", "bedroom", "garage"],
    CONF_PERSONS: [{"name": "Alice"}, {"name": "Bob"}],
    CONF_PETS: [],
    CONF_ROOM_ENTITIES: {
        "office": [{"entity_id": "binary_sensor.office_motion", "hint_type": "motion"}],
    },
    CONF_PERSON_DEVICES: {},
    CONF_LEARNING_ENABLED: True,
}


@pytest.fixture
async def options_entry(hass, enable_custom_integrations):
    """Add a Roomer config entry (not set up) and the entities the forms reference."""
    entry = MockConfigEntry(domain=DOMAIN, version=2, data=OPTIONS_ENTRY_DATA)
    entry.add_to_hass(hass)
    for entity_id in (
        "binary_sensor.office_motion",
        "switch.office_pc",
        "light.bedroom",
        "switch.garage_door",
        "device_tracker.alice_phone",
        "device_tracker.bob_phone",
    ):
        hass.states.async_set(entity_id, "off")
    return entry


async def _save_section(hass, entry, section: str, user_input: dict) -> dict:
    """Open the options flow, pick a menu section and submit it."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": section})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == section
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    return result


async def _open_section(hass, entry, section: str) -> dict:
    """Open an options section form and return its schema defaults by key."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": section})
    defaults = {str(key): key.default() for key in result["data_schema"].schema}
    hass.config_entries.options.async_abort(result["flow_id"])
    return defaults


class TestOptionsFlow:
    """Test the options flow end to end through Home Assistant."""

    async def test_options_flow_does_not_take_config_entry_arg(self):
        """The options flow relies on HA's config_entry property (2024.11+ pattern)."""
        from custom_components.roomer.config_flow import LLMPresenceConfigFlow, LLMPresenceOptionsFlow

        flow = LLMPresenceConfigFlow.async_get_options_flow(MagicMock())
        assert isinstance(flow, LLMPresenceOptionsFlow)
        assert "config_entry" not in LLMPresenceOptionsFlow.__dict__

    async def test_sections_saved_in_sequence_are_all_kept(self, hass, options_entry):
        """Saving one section must not wipe what other sections saved."""
        await _save_section(
            hass,
            options_entry,
            "general",
            {CONF_POLL_INTERVAL: 60, CONF_TIMEOUT: 45, CONF_LEARNING_ENABLED: False},
        )
        await _save_section(
            hass,
            options_entry,
            "room_entities",
            {
                "office": ["binary_sensor.office_motion", "switch.office_pc"],
                "bedroom": ["light.bedroom"],
                "garage": [],
            },
        )
        await _save_section(
            hass,
            options_entry,
            "person_devices",
            {"Alice": ["device_tracker.alice_phone"], "Bob": ["device_tracker.bob_phone"]},
        )
        await _save_section(hass, options_entry, "confidence_weights", {"weight_camera": 90, "weight_motion": 40})

        options = options_entry.options
        assert options[CONF_POLL_INTERVAL] == 60
        assert options[CONF_TIMEOUT] == 45
        assert options[CONF_LEARNING_ENABLED] is False
        assert [e["entity_id"] for e in options[CONF_ROOM_ENTITIES]["office"]] == [
            "binary_sensor.office_motion",
            "switch.office_pc",
        ]
        assert options[CONF_ROOM_ENTITIES]["bedroom"] == [
            {"entity_id": "light.bedroom", "hint_type": "light", "weight": 1.0, "detects": "any"}
        ]
        assert "garage" not in options[CONF_ROOM_ENTITIES]
        assert options[CONF_PERSON_DEVICES] == {
            "Alice": ["device_tracker.alice_phone"],
            "Bob": ["device_tracker.bob_phone"],
        }
        assert options[CONF_CONFIDENCE_WEIGHTS]["camera"] == pytest.approx(0.90)
        assert options[CONF_CONFIDENCE_WEIGHTS]["motion"] == pytest.approx(0.40)
        # Types without a slider keep their current value
        assert options[CONF_CONFIDENCE_WEIGHTS]["climate"] == DEFAULT_CONFIDENCE_WEIGHTS["climate"]

    async def test_resaving_a_section_keeps_the_others(self, hass, options_entry):
        """Saving the same section twice only changes that section."""
        await _save_section(hass, options_entry, "person_devices", {"Alice": ["device_tracker.alice_phone"]})
        await _save_section(
            hass,
            options_entry,
            "general",
            {CONF_POLL_INTERVAL: 20, CONF_TIMEOUT: 30, CONF_LEARNING_ENABLED: True},
        )
        await _save_section(
            hass,
            options_entry,
            "general",
            {CONF_POLL_INTERVAL: 90, CONF_TIMEOUT: 30, CONF_LEARNING_ENABLED: True},
        )

        assert options_entry.options[CONF_POLL_INTERVAL] == 90
        assert options_entry.options[CONF_PERSON_DEVICES] == {"Alice": ["device_tracker.alice_phone"]}

    async def test_forms_default_to_last_saved_options(self, hass, options_entry):
        """Forms show the last saved values, falling back to setup data."""
        defaults = await _open_section(hass, options_entry, "general")
        assert defaults[CONF_POLL_INTERVAL] == 30  # from entry.data
        assert defaults[CONF_LEARNING_ENABLED] is True

        defaults = await _open_section(hass, options_entry, "room_entities")
        assert defaults["office"] == ["binary_sensor.office_motion"]  # from entry.data

        await _save_section(
            hass,
            options_entry,
            "general",
            {CONF_POLL_INTERVAL: 120, CONF_TIMEOUT: 60, CONF_LEARNING_ENABLED: False},
        )
        await _save_section(
            hass,
            options_entry,
            "room_entities",
            {"office": ["switch.office_pc"], "bedroom": ["light.bedroom"], "garage": []},
        )
        await _save_section(hass, options_entry, "person_devices", {"Bob": ["device_tracker.bob_phone"]})
        await _save_section(hass, options_entry, "confidence_weights", {"weight_door": 75})

        defaults = await _open_section(hass, options_entry, "general")
        assert defaults == {CONF_POLL_INTERVAL: 120, CONF_TIMEOUT: 60, CONF_LEARNING_ENABLED: False}

        defaults = await _open_section(hass, options_entry, "room_entities")
        assert defaults == {"office": ["switch.office_pc"], "bedroom": ["light.bedroom"], "garage": []}

        defaults = await _open_section(hass, options_entry, "person_devices")
        assert defaults == {"Alice": [], "Bob": ["device_tracker.bob_phone"]}

        defaults = await _open_section(hass, options_entry, "confidence_weights")
        assert defaults["weight_door"] == 75
        assert defaults["weight_camera"] == round(DEFAULT_CONFIDENCE_WEIGHTS["camera"] * 100)

    async def test_room_entities_skips_missing_entities(self, hass, options_entry):
        """Entities that don't exist are dropped and empty rooms removed."""
        await _save_section(
            hass,
            options_entry,
            "room_entities",
            {"office": ["switch.does_not_exist"], "bedroom": ["light.bedroom"], "garage": []},
        )

        assert options_entry.options[CONF_ROOM_ENTITIES] == {
            "bedroom": [{"entity_id": "light.bedroom", "hint_type": "light", "weight": 1.0, "detects": "any"}],
        }


class TestOptionsFlowLabels:
    """Static form keys must have labels so the UI doesn't show raw keys."""

    @staticmethod
    def _load(path: str) -> dict:
        return json.loads((Path(__file__).parent.parent / "custom_components" / "roomer" / path).read_text())

    @pytest.mark.parametrize("path", ["strings.json", "translations/en.json"])
    def test_weight_labels_present(self, path):
        from custom_components.roomer.config_flow import WEIGHT_HINT_TYPES

        labels = self._load(path)["options"]["step"]["confidence_weights"]["data"]
        for hint_type in WEIGHT_HINT_TYPES:
            assert f"weight_{hint_type}" in labels

    @pytest.mark.parametrize("path", ["strings.json", "translations/en.json"])
    @pytest.mark.parametrize("section", ["config", "options"])
    def test_builtin_room_labels_present(self, path, section):
        labels = self._load(path)[section]["step"]["room_entities"]["data"]
        for room in VALID_ROOMS:
            if room in ("away", "unknown"):
                continue
            assert room in labels


class TestConfigFlowEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_model_list_uses_default(self):
        """Test that empty model list uses default model."""
        from custom_components.roomer.config_flow import LLMPresenceConfigFlow

        flow = LLMPresenceConfigFlow()
        flow.hass = MagicMock()
        flow._data = {}
        flow._available_models = []  # Empty list

        result = await flow.async_step_model(user_input=None)

        assert result["type"] == FlowResultType.FORM
        # Schema should still contain model field with default

    @pytest.mark.asyncio
    async def test_whitespace_in_custom_rooms_handled(self):
        """Test that whitespace in custom room names is handled."""
        from custom_components.roomer.config_flow import LLMPresenceConfigFlow

        flow = LLMPresenceConfigFlow()
        flow.hass = MagicMock()
        flow._data = {
            CONF_PROVIDER: "ollama",
            CONF_URL: "http://localhost:11434",
            CONF_MODEL: "llama3.2",
        }

        await flow.async_step_rooms(user_input={CONF_ROOMS: [], "custom_rooms": "  garage  ,   Game Room  ,  "})

        assert "garage" in flow._data[CONF_ROOMS]
        assert "game_room" in flow._data[CONF_ROOMS]

    @pytest.mark.asyncio
    async def test_duplicate_custom_rooms_deduplicated(self):
        """Test that duplicate rooms are not added twice."""
        from custom_components.roomer.config_flow import LLMPresenceConfigFlow

        flow = LLMPresenceConfigFlow()
        flow.hass = MagicMock()
        flow._data = {
            CONF_PROVIDER: "ollama",
            CONF_URL: "http://localhost:11434",
            CONF_MODEL: "llama3.2",
        }

        await flow.async_step_rooms(user_input={CONF_ROOMS: ["office"], "custom_rooms": "office, bedroom"})

        # office should not be duplicated
        assert flow._data[CONF_ROOMS].count("office") == 1
