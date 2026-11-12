"""Helpers for typing and normalising mapped room entities.

A mapped entity is stored per room as ``{"entity_id", "hint_type"}`` with two
optional keys:

- ``weight``: share of the entity's evidence given to this room (default 1.0).
  An entity mapped to several rooms can split its weight between them.
- ``detects``: ``person``, ``animal`` or ``any`` (default). A camera's person
  detection only counts towards people, an animal detection only towards pets.
"""

from __future__ import annotations

import re
from typing import Any

from .const import (
    DETECTS_ANIMAL,
    DETECTS_ANY,
    DETECTS_PERSON,
    ENTITY_HINT_APPLIANCE,
    ENTITY_HINT_CAMERA,
    ENTITY_HINT_COMPUTER,
    ENTITY_HINT_LIGHT,
    ENTITY_HINT_MEDIA,
    ENTITY_HINT_MOTION,
)

# device_class values of binary sensors, mapped to a hint type
_MOTION_DEVICE_CLASSES = {"motion", "occupancy", "presence", "moving"}
_DOOR_DEVICE_CLASSES = {"door", "window", "garage_door", "opening"}

_PERSON_WORDS = {"person", "human", "people"}
_ANIMAL_WORDS = {"animal", "pet", "dog", "cat"}


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t}


def guess_entity_hint(entity_id: str, device_class: str | None = None) -> str:
    """Guess the hint type of an entity.

    Order: the entity's domain, then camera AI detections (person/animal in the
    name), then its ``device_class`` (motion, occupancy and presence are motion;
    door and window are door), and finally substrings of the entity id.
    """
    entity_lower = entity_id.lower()
    domain, _, object_id = entity_lower.partition(".")
    tokens = _tokens(object_id)

    if domain == "light":
        return ENTITY_HINT_LIGHT
    if domain == "media_player":
        return ENTITY_HINT_MEDIA
    if domain == "camera":
        return ENTITY_HINT_CAMERA
    if domain == "device_tracker":
        return "presence"

    if domain == "binary_sensor" and tokens & (_PERSON_WORDS | _ANIMAL_WORDS):
        return ENTITY_HINT_CAMERA

    dc = (device_class or "").lower()
    if dc in _MOTION_DEVICE_CLASSES:
        return ENTITY_HINT_MOTION
    if dc in _DOOR_DEVICE_CLASSES:
        return "door"

    # Fall back to substrings of the entity id
    if "motion" in entity_lower or "occupancy" in entity_lower or "presence" in tokens:
        return ENTITY_HINT_MOTION
    if "media_player" in entity_lower or "tv" in tokens:
        return ENTITY_HINT_MEDIA
    if "pc" in tokens or "computer" in entity_lower or "desktop" in entity_lower:
        return ENTITY_HINT_COMPUTER
    if "camera" in entity_lower or "person" in entity_lower or "animal" in entity_lower:
        return ENTITY_HINT_CAMERA
    if "door" in entity_lower or "window" in entity_lower or "contact" in entity_lower:
        return "door"
    if "temperature" in entity_lower or "humidity" in entity_lower:
        return "climate"
    return ENTITY_HINT_APPLIANCE


def guess_detects(entity_id: str, name: str | None = None) -> str:
    """Guess what a camera detection entity detects: person, animal or any."""
    tokens = _tokens(entity_id.partition(".")[2]) | _tokens(name or "")
    if tokens & _PERSON_WORDS:
        return DETECTS_PERSON
    if tokens & _ANIMAL_WORDS:
        return DETECTS_ANIMAL
    return DETECTS_ANY


def normalize_room_entities(raw: Any) -> dict[str, list[dict[str, Any]]]:
    """Return room_entities in the canonical ``{room: [entry, ...]}`` form.

    Accepts what older versions stored (entity id strings, entries without a
    weight) and entries that list several rooms (``{"entity_id": ..., "rooms":
    [...]}``), which are expanded to one entry per room, splitting the weight
    evenly unless one is given.
    """
    result: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(raw, dict):
        return result

    def add(room: str, entry: dict[str, Any]) -> None:
        bucket = result.setdefault(room, [])
        if not any(e["entity_id"] == entry["entity_id"] for e in bucket):
            bucket.append(entry)

    for room, entries in raw.items():
        if not isinstance(entries, list):
            continue
        for item in entries:
            if isinstance(item, str):
                item = {"entity_id": item}
            if not isinstance(item, dict) or not item.get("entity_id"):
                continue
            entry = {k: v for k, v in item.items() if k != "rooms"}
            entry.setdefault("hint_type", guess_entity_hint(entry["entity_id"]))
            extra_rooms = item.get("rooms")
            if isinstance(extra_rooms, list) and extra_rooms:
                all_rooms = list(dict.fromkeys([room, *extra_rooms]))
                entry.setdefault("weight", round(1 / len(all_rooms), 3))
                for r in all_rooms:
                    add(r, dict(entry))
                continue
            weight = entry.get("weight", 1.0)
            try:
                weight = min(1.0, max(0.0, float(weight)))
            except (TypeError, ValueError):
                weight = 1.0
            entry["weight"] = weight
            if entry.get("detects") not in (DETECTS_PERSON, DETECTS_ANIMAL, DETECTS_ANY):
                entry["detects"] = DETECTS_ANY
            add(room, entry)
    return result
