"""Binary sensor platform for Roomer."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_CONFIDENCE, ATTR_ROOM_AREA_ID, DOMAIN
from .coordinator import LLMPresenceCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Roomer binary sensors from a config entry."""
    coordinator: LLMPresenceCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[BinarySensorEntity] = []

    # Create binary sensors for each person x room combination
    for person in coordinator.persons:
        person_name = person.get("name", "unknown")
        for room in coordinator.rooms:
            entities.append(
                LLMPresenceRoomBinarySensor(
                    coordinator=coordinator,
                    entity_name=person_name,
                    entity_type="person",
                    room=room,
                )
            )

    # Create binary sensors for each pet x room combination
    for pet in coordinator.pets:
        pet_name = pet.get("name", "unknown")
        for room in coordinator.rooms:
            entities.append(
                LLMPresenceRoomBinarySensor(
                    coordinator=coordinator,
                    entity_name=pet_name,
                    entity_type="pet",
                    room=room,
                )
            )

    async_add_entities(entities)


class LLMPresenceRoomBinarySensor(CoordinatorEntity[LLMPresenceCoordinator], BinarySensorEntity):
    """Binary sensor for presence in a specific room."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(
        self,
        coordinator: LLMPresenceCoordinator,
        entity_name: str,
        entity_type: str,
        room: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._entity_name = entity_name
        self._entity_type = entity_type
        self._room = room

        # Set unique ID and name
        name_slug = entity_name.lower().replace(" ", "_")
        room_slug = room.lower().replace(" ", "_")
        self._attr_unique_id = f"{DOMAIN}_{entity_type}_{name_slug}_{room_slug}"
        self._attr_name = f"{entity_name} in {room.replace('_', ' ').title()}"

        # Set icon based on type
        self._attr_icon = "mdi:account-check" if entity_type == "person" else "mdi:paw"

    @property
    def is_on(self) -> bool | None:
        """Return True if the entity is in this room."""
        if not self.coordinator.data:
            return None

        data_key = "persons" if self._entity_type == "person" else "pets"
        entity_data = self.coordinator.data.get(data_key, {}).get(self._entity_name)

        if entity_data:
            return self._room in [entity_data.room, *(getattr(entity_data, "alternate_rooms", None) or [])]
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data:
            return {}

        data_key = "persons" if self._entity_type == "person" else "pets"
        entity_data = self.coordinator.data.get(data_key, {}).get(self._entity_name)

        if entity_data:
            return {
                ATTR_CONFIDENCE: entity_data.confidence if self.is_on else 0.0,
                "current_room": entity_data.room,
                ATTR_ROOM_AREA_ID: self.coordinator.area_id_for_room(self._room),
                "entity_type": self._entity_type,
            }
        return {}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
