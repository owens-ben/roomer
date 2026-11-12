"""Config flow for Roomer integration."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_CONFIDENCE_WEIGHTS,
    CONF_LEARNING_ENABLED,
    CONF_MODEL,
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
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PROVIDER,
    DEFAULT_TIMEOUT,
    DEFAULT_URL,
    DETECTS_OPTIONS,
    DOMAIN,
    ROOM_AWAY,
    ROOM_UNKNOWN,
    SUPPORTED_PROVIDERS,
    VALID_ROOMS,
)
from .entity_hints import guess_detects, guess_entity_hint, normalize_room_entities
from .providers import get_provider

_LOGGER = logging.getLogger(__name__)

ROOM_ENTITY_DOMAINS = [
    "binary_sensor",
    "sensor",
    "light",
    "switch",
    "media_player",
    "device_tracker",
    "camera",
]

PERSON_DEVICE_DOMAINS = ["device_tracker", "binary_sensor", "switch", "sensor"]

# Weight sliders shown in the options flow. Labels live in strings.json under
# options.step.confidence_weights.data.weight_<hint_type>.
WEIGHT_HINT_TYPES = [
    "camera",
    "computer",
    "media",
    "motion",
    "presence",
    "appliance",
    "light",
    "door",
    "llm_reasoning",
    "habit",
]


def _guess_entity_hint(entity_id: str, device_class: str | None = None) -> str:
    """Guess the entity hint type (see entity_hints.guess_entity_hint)."""
    return guess_entity_hint(entity_id, device_class)


def _entry_for(hass, entity_id: str, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the stored mapping entry for an entity, keeping what is already known about it."""
    state = hass.states.get(entity_id)
    device_class = state.attributes.get("device_class") if state else None
    friendly_name = state.attributes.get("friendly_name") if state else None
    entry = dict(existing or {})
    entry["entity_id"] = entity_id
    entry.setdefault("hint_type", _guess_entity_hint(entity_id, device_class))
    entry.setdefault("weight", 1.0)
    entry.setdefault("detects", guess_detects(entity_id, friendly_name))
    return entry


class LLMPresenceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Roomer."""

    VERSION = 3  # 3: room_entities entries carry weight and detects (multi-room mapping)

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data: dict[str, Any] = {}
        self._available_models: list[str] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step - provider configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Test connection to provider
            provider = get_provider(
                provider_type=user_input[CONF_PROVIDER],
                url=user_input[CONF_URL],
                model=user_input.get(CONF_MODEL, DEFAULT_MODEL),
            )

            if await provider.test_connection():
                self._data.update(user_input)
                self._available_models = await provider.get_available_models()
                return await self.async_step_model()
            else:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PROVIDER, default=DEFAULT_PROVIDER): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=SUPPORTED_PROVIDERS,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(CONF_URL, default=DEFAULT_URL): str,
                    vol.Optional(CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=5,
                            max=300,
                            step=5,
                            unit_of_measurement="seconds",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_model(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle model selection step."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_rooms()

        # Build model options
        model_options = self._available_models if self._available_models else [DEFAULT_MODEL]

        return self.async_show_form(
            step_id="model",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MODEL, default=model_options[0] if model_options else DEFAULT_MODEL
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=model_options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            custom_value=True,
                        )
                    ),
                }
            ),
        )

    async def async_step_rooms(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle room configuration step."""

        errors: dict[str, str] = {}

        if user_input is not None:
            rooms = user_input.get(CONF_ROOMS, [])
            custom_rooms = user_input.get("custom_rooms", "")

            # Add custom rooms with sanitization
            if custom_rooms:
                for room in custom_rooms.split(","):
                    room = room.strip().lower().replace(" ", "_")
                    # Remove any characters that aren't alphanumeric, underscore, or hyphen
                    room = re.sub(r"[^\w-]", "", room)
                    if room and room not in rooms:
                        rooms.append(room)

            # Sanitize all room names (including predefined ones)
            sanitized = []
            for room in rooms:
                room = room.strip().lower().replace(" ", "_")
                room = re.sub(r"[^\w-]", "", room)
                if room and room not in sanitized:
                    sanitized.append(room)
            rooms = sanitized

            if not rooms:
                errors["base"] = "at_least_one_room"
            else:
                self._data[CONF_ROOMS] = rooms
                return await self.async_step_persons()

        return self.async_show_form(
            step_id="rooms",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ROOMS, default=VALID_ROOMS[:6]): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=VALID_ROOMS[:-2],  # Exclude 'away' and 'unknown'
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Optional("custom_rooms", default=""): str,
                }
            ),
            description_placeholders={
                "custom_rooms_hint": "Add custom rooms (comma-separated, e.g., garage, basement)",
            },
            errors=errors,
        )

    async def async_step_persons(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle person/pet configuration step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Parse persons and pets from input
            persons = []
            pets = []

            persons_input = user_input.get(CONF_PERSONS, "")
            if persons_input:
                for name in persons_input.split(","):
                    name = name.strip()
                    if name:
                        persons.append({"name": name})

            pets_input = user_input.get(CONF_PETS, "")
            if pets_input:
                for name in pets_input.split(","):
                    name = name.strip()
                    if name:
                        pets.append({"name": name})

            # Validate that at least one person or pet is configured
            if not persons and not pets:
                errors["base"] = "at_least_one_entity"
            else:
                self._data[CONF_PERSONS] = persons
                self._data[CONF_PETS] = pets
                return await self.async_step_room_entities()

        return self.async_show_form(
            step_id="persons",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PERSONS, default=""): str,
                    vol.Optional(CONF_PETS, default=""): str,
                }
            ),
            description_placeholders={
                "persons_hint": "Comma-separated names (e.g., Alice, Bob)",
                "pets_hint": "Comma-separated names (e.g., Fido, Whiskers)",
            },
            errors=errors,
        )

    async def async_step_room_entities(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle room-entity mapping configuration."""
        if user_input is not None:
            # Process room entity mappings, validating entities exist
            room_entities = {}
            invalid_entities = []
            for room in self._data.get(CONF_ROOMS, []):
                entities = user_input.get(room, [])
                if entities:
                    valid = []
                    for e in entities:
                        if self.hass.states.get(e) is not None:
                            valid.append(_entry_for(self.hass, e))
                        else:
                            invalid_entities.append(e)
                    if valid:
                        room_entities[room] = valid

            if invalid_entities:
                _LOGGER.warning(
                    "Skipped non-existent entities during config: %s",
                    ", ".join(invalid_entities),
                )

            self._data[CONF_ROOM_ENTITIES] = room_entities

            # Initialize empty person devices (can be configured in options later)
            self._data[CONF_PERSON_DEVICES] = {}
            self._data[CONF_LEARNING_ENABLED] = True

            # Create the config entry
            return self.async_create_entry(
                title=f"Roomer ({self._data[CONF_PROVIDER]})",
                data=self._data,
            )

        # Build dynamic schema based on selected rooms
        rooms = self._data.get(CONF_ROOMS, [])
        schema_dict = {}

        for room in rooms:
            # One entity selector per room, keyed by the room name so the UI
            # shows the room (translated for built-in rooms, raw for custom ones)
            schema_dict[vol.Optional(room, default=[])] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    multiple=True,
                    filter=selector.EntityFilterSelectorConfig(domain=ROOM_ENTITY_DOMAINS),
                )
            )

        return self.async_show_form(
            step_id="room_entities",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "room_hint": "Select entities that indicate activity in each room. This helps Roomer understand which sensors/devices belong to which room.",
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return LLMPresenceOptionsFlow()


class LLMPresenceOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Roomer.

    Each section only edits its own keys, so results are merged into the
    existing options instead of replacing them. Home Assistant provides
    ``self.config_entry``.
    """

    def _get(self, key: str, default: Any = None) -> Any:
        """Get a value from options first, then data, then default."""
        return self.config_entry.options.get(key, self.config_entry.data.get(key, default))

    def _save(self, new_options: dict[str, Any]) -> FlowResult:
        """Merge one section's values into the existing options and save."""
        return self.async_create_entry(title="", data={**self.config_entry.options, **new_options})

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage the options - show menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "general",
                "room_entities",
                "multi_room",
                "room_areas",
                "person_devices",
                "confidence_weights",
            ],
        )

    async def async_step_general(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """General options."""
        if user_input is not None:
            return self._save(user_input)

        return self.async_show_form(
            step_id="general",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_POLL_INTERVAL,
                        default=self._get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=5,
                            max=300,
                            step=5,
                            unit_of_measurement="seconds",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Optional(
                        CONF_TIMEOUT,
                        default=self._get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=5,
                            max=120,
                            step=5,
                            unit_of_measurement="seconds",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Optional(
                        CONF_LEARNING_ENABLED,
                        default=self._get(CONF_LEARNING_ENABLED, DEFAULT_LEARNING_ENABLED),
                    ): bool,
                }
            ),
        )

    async def async_step_room_entities(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure room-entity mappings."""
        if user_input is not None:
            # Process and save room entity mappings, validating entities exist
            room_entities = dict(normalize_room_entities(self._get(CONF_ROOM_ENTITIES, {})))
            rooms = self._get(CONF_ROOMS, [])
            invalid_entities = []

            for room in rooms:
                entities = user_input.get(room, [])
                if entities:
                    valid = []
                    known = {e["entity_id"]: e for e in room_entities.get(room, [])}
                    for e in entities:
                        if self.hass.states.get(e) is not None:
                            # Keep what is already known (weight, detects) for entities that stay
                            valid.append(_entry_for(self.hass, e, known.get(e)))
                        else:
                            invalid_entities.append(e)
                    if valid:
                        room_entities[room] = valid
                    elif room in room_entities:
                        del room_entities[room]
                elif room in room_entities:
                    del room_entities[room]

            if invalid_entities:
                _LOGGER.warning(
                    "Skipped non-existent entities during options update: %s",
                    ", ".join(invalid_entities),
                )

            return self._save({CONF_ROOM_ENTITIES: room_entities})

        # Build dynamic schema, one picker per room keyed by the room name
        rooms = self._get(CONF_ROOMS, [])
        current_mappings = normalize_room_entities(self._get(CONF_ROOM_ENTITIES, {}))
        schema_dict = {}

        for room in rooms:
            current_entities = [e["entity_id"] for e in current_mappings.get(room, [])]
            schema_dict[vol.Optional(room, default=current_entities)] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    multiple=True,
                    filter=selector.EntityFilterSelectorConfig(domain=ROOM_ENTITY_DOMAINS),
                )
            )

        return self.async_show_form(
            step_id="room_entities",
            data_schema=vol.Schema(schema_dict),
        )

    async def async_step_multi_room(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Map one entity to several rooms, e.g. a camera that sees two rooms.

        The entity is stored under each chosen room. ``split_weight`` shares its
        evidence between them instead of giving each room all of it, and
        ``detects`` limits a camera detection to people or to animals.
        """
        errors: dict[str, str] = {}
        rooms = self._get(CONF_ROOMS, [])

        if user_input is not None:
            entity_id = user_input["entity_id"]
            chosen = [r for r in user_input.get("rooms", []) if r in rooms]
            if self.hass.states.get(entity_id) is None:
                errors["entity_id"] = "entity_not_found"
            else:
                room_entities = normalize_room_entities(self._get(CONF_ROOM_ENTITIES, {}))
                previous: dict[str, Any] | None = None
                for room in list(room_entities):
                    kept = []
                    for entry in room_entities[room]:
                        if entry["entity_id"] == entity_id:
                            previous = previous or entry
                        else:
                            kept.append(entry)
                    if kept:
                        room_entities[room] = kept
                    else:
                        del room_entities[room]

                if chosen:
                    base = _entry_for(self.hass, entity_id, {"hint_type": previous["hint_type"]} if previous else None)
                    detects = user_input.get("detects", "auto")
                    if detects != "auto":
                        base["detects"] = detects
                    base["weight"] = round(1 / len(chosen), 3) if user_input.get("split_weight") else 1.0
                    for room in chosen:
                        room_entities.setdefault(room, []).append(dict(base))
                return self._save({CONF_ROOM_ENTITIES: room_entities})

        return self.async_show_form(
            step_id="multi_room",
            data_schema=vol.Schema(
                {
                    vol.Required("entity_id"): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            filter=selector.EntityFilterSelectorConfig(domain=ROOM_ENTITY_DOMAINS),
                        )
                    ),
                    vol.Optional("rooms", default=[]): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=rooms,
                            multiple=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional("detects", default="auto"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["auto", *DETECTS_OPTIONS],
                            translation_key="detects",
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional("split_weight", default=False): selector.BooleanSelector(),
                }
            ),
            errors=errors,
        )

    async def async_step_room_areas(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Map rooms to Home Assistant areas, exposed as ``room_area_id``."""
        rooms = self._get(CONF_ROOMS, [])
        current = self._get(CONF_ROOM_AREAS, {}) or {}

        if user_input is not None:
            return self._save({CONF_ROOM_AREAS: {room: user_input[room] for room in rooms if user_input.get(room)}})

        schema_dict = {}
        for room in rooms:
            if room in (ROOM_AWAY, ROOM_UNKNOWN):
                continue
            key = vol.Optional(room, description={"suggested_value": current.get(room)})
            schema_dict[key] = selector.AreaSelector()

        return self.async_show_form(step_id="room_areas", data_schema=vol.Schema(schema_dict))

    async def async_step_person_devices(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure person-device ownership mappings."""
        if user_input is not None:
            # Process and save person device mappings
            person_devices = {}
            persons = self._get(CONF_PERSONS, [])
            pets = self._get(CONF_PETS, [])

            for person in persons + pets:
                name = person.get("name", "")
                devices = user_input.get(name, [])
                if devices:
                    person_devices[name] = devices

            return self._save({CONF_PERSON_DEVICES: person_devices})

        # Build dynamic schema, one picker per person/pet keyed by their name
        # so the UI labels each picker with the name
        persons = self._get(CONF_PERSONS, [])
        pets = self._get(CONF_PETS, [])
        current_mappings = self._get(CONF_PERSON_DEVICES, {})
        schema_dict = {}

        for entity in persons + pets:
            name = entity.get("name", "")
            current_devices = current_mappings.get(name, [])
            schema_dict[vol.Optional(name, default=current_devices)] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    multiple=True,
                    filter=selector.EntityFilterSelectorConfig(domain=PERSON_DEVICE_DOMAINS),
                )
            )

        return self.async_show_form(
            step_id="person_devices",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "hint": "Assign devices owned by each person (their phone, PC, etc). If that device is active, it strongly suggests that person is nearby.",
            },
        )

    async def async_step_confidence_weights(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure confidence weights for different signal types."""
        current_weights = self._get(CONF_CONFIDENCE_WEIGHTS, DEFAULT_CONFIDENCE_WEIGHTS)

        if user_input is not None:
            # Start from the current weights so types without a slider (e.g. climate) are kept
            weights = dict(current_weights)
            for key, value in user_input.items():
                if key.startswith("weight_"):
                    hint_type = key.replace("weight_", "")
                    weights[hint_type] = value / 100  # Convert from percentage

            return self._save({CONF_CONFIDENCE_WEIGHTS: weights})

        schema_dict = {}

        for hint_type in WEIGHT_HINT_TYPES:
            default_value = round(current_weights.get(hint_type, 0.5) * 100)
            schema_dict[vol.Optional(f"weight_{hint_type}", default=default_value)] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=100,
                    step=5,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            )

        return self.async_show_form(
            step_id="confidence_weights",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "hint": "Adjust how much each signal type contributes to presence detection. Higher = more influence.",
            },
        )
