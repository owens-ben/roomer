"""Validate and exercise the automation blueprints in blueprints/.

Each blueprint is loaded with Home Assistant's blueprint schema, its inputs are
substituted, and the result is set up as a real automation so that triggers,
the top-level ``variables:`` block and the template conditions are checked
against state changes rather than just parsed.
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import timedelta
from pathlib import Path

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.components.automation import DOMAIN as AUTOMATION_DOMAIN  # noqa: E402
from homeassistant.components.automation.config import async_validate_config_item  # noqa: E402
from homeassistant.components.blueprint import schemas  # noqa: E402
from homeassistant.components.blueprint.models import Blueprint, BlueprintInputs  # noqa: E402
from homeassistant.setup import async_setup_component  # noqa: E402
from homeassistant.util import dt as dt_util  # noqa: E402
from homeassistant.util.yaml import load_yaml_dict  # noqa: E402
from pytest_homeassistant_custom_component.common import (  # noqa: E402
    async_fire_time_changed,
    async_mock_service,
)

BLUEPRINT_DIR = Path(__file__).parent.parent / "blueprints"
BLUEPRINTS = sorted(p.name for p in BLUEPRINT_DIR.glob("*.yaml"))

MINIMAL_INPUTS = {
    "follow_me_music.yaml": {
        "person_sensor": "sensor.alice_room",
        "room_speaker_map": {"office": "media_player.office", "kitchen": "media_player.kitchen"},
    },
    "goodbye_routine.yaml": {"person_sensors": ["sensor.alice_room"]},
    "room_based_climate.yaml": {
        "person_sensor": "sensor.alice_room",
        "target_room": "office",
        "climate_entity": "climate.office",
    },
    "welcome_home_lights.yaml": {
        "person_sensor": "sensor.alice_room",
        "lights": {"entity_id": "light.hall"},
    },
}


def _substitute(name: str, inputs: dict) -> dict:
    kwargs = {"expected_domain": AUTOMATION_DOMAIN}
    # Newer Home Assistant takes the schema explicitly; older versions
    # (installed on Python 3.11) always apply BLUEPRINT_SCHEMA.
    if "schema" in inspect.signature(Blueprint.__init__).parameters:
        kwargs["schema"] = schemas.BLUEPRINT_SCHEMA
    blueprint = Blueprint(load_yaml_dict(str(BLUEPRINT_DIR / name)), **kwargs)
    config = BlueprintInputs(blueprint, {"use_blueprint": {"path": name, "input": inputs}}).async_substitute()
    config["id"] = name
    return config


async def _validate(hass, name: str, config: dict) -> None:
    """Validate an automation config; older Home Assistant raises instead of recording the error."""
    assert await async_setup_component(hass, "homeassistant", {})
    result = await async_validate_config_item(hass, name, config)
    assert result is not None
    assert getattr(result, "validation_error", None) is None
    assert not getattr(result, "validation_failed", False)


async def _setup(hass, name: str, inputs: dict) -> None:
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, AUTOMATION_DOMAIN, {AUTOMATION_DOMAIN: [_substitute(name, inputs)]})
    await hass.async_block_till_done()


async def _settle(hass) -> None:
    """Let triggered automations run up to their first delay.

    hass.async_block_till_done() would wait for the whole run, including the
    delay, so it is only used once time has been advanced past it.
    """
    for _ in range(20):
        await asyncio.sleep(0)


async def _advance(hass, **kwargs) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(**kwargs))
    await _settle(hass)


def test_every_blueprint_has_minimal_inputs():
    assert sorted(MINIMAL_INPUTS) == BLUEPRINTS


@pytest.mark.parametrize("name", BLUEPRINTS)
async def test_blueprint_validates(hass, name):
    """Blueprint schema and the substituted automation config are both valid."""
    await _validate(hass, name, _substitute(name, MINIMAL_INPUTS[name]))


async def test_goodbye_validates_with_all_optional_inputs(hass):
    config = _substitute(
        "goodbye_routine.yaml",
        {
            "person_sensors": ["sensor.alice_room"],
            "turn_off_lights": {"entity_id": "light.hall"},
            "lock_doors": {"entity_id": "lock.front"},
            "arm_alarm": "alarm_control_panel.home",
            "set_climate_away": "climate.house",
        },
    )
    await _validate(hass, "goodbye", config)


async def test_welcome_home_fires_on_away_to_room(hass):
    calls = async_mock_service(hass, "light", "turn_on")
    async_mock_service(hass, "light", "turn_off")
    hass.states.async_set("sensor.alice_room", "away")
    await _setup(
        hass, "welcome_home_lights.yaml", {**MINIMAL_INPUTS["welcome_home_lights.yaml"], "only_after_dark": False}
    )

    hass.states.async_set("sensor.alice_room", "unknown")
    await _settle(hass)
    assert not calls  # away -> unknown is not an arrival

    hass.states.async_set("sensor.alice_room", "away")
    hass.states.async_set("sensor.alice_room", "office")
    await _settle(hass)
    assert len(calls) == 1
    assert calls[0].data["entity_id"] == ["light.hall"]
    assert calls[0].data["brightness_pct"] == 80

    hass.states.async_set("sensor.alice_room", "kitchen")
    await _settle(hass)
    assert len(calls) == 1  # room to room is not an arrival
    await _advance(hass, minutes=6)


@pytest.mark.parametrize(("sun_state", "expected_calls"), [("above_horizon", 0), ("below_horizon", 1)])
async def test_welcome_home_only_after_dark(hass, sun_state, expected_calls):
    calls = async_mock_service(hass, "light", "turn_on")
    async_mock_service(hass, "light", "turn_off")
    hass.states.async_set("sun.sun", sun_state)
    hass.states.async_set("sensor.alice_room", "away")
    await _setup(hass, "welcome_home_lights.yaml", MINIMAL_INPUTS["welcome_home_lights.yaml"])

    hass.states.async_set("sensor.alice_room", "office")
    await _settle(hass)
    assert len(calls) == expected_calls
    await _advance(hass, minutes=6)


async def test_goodbye_waits_until_everyone_is_away(hass):
    locks = async_mock_service(hass, "lock", "lock")
    lights = async_mock_service(hass, "light", "turn_off")
    hass.states.async_set("sensor.alice_room", "office")
    hass.states.async_set("sensor.bob_room", "kitchen")
    await _setup(
        hass,
        "goodbye_routine.yaml",
        {
            "person_sensors": ["sensor.alice_room", "sensor.bob_room"],
            "lock_doors": {"entity_id": "lock.front"},
            "delay_minutes": 1,
        },
    )

    hass.states.async_set("sensor.alice_room", "away")
    await _settle(hass)
    await _advance(hass, minutes=2)
    assert not locks  # Bob is still home

    hass.states.async_set("sensor.bob_room", "away")
    await _settle(hass)
    await _advance(hass, minutes=4)
    assert len(locks) == 1
    assert locks[0].data["entity_id"] == ["lock.front"]
    assert not lights  # No lights configured, but the locks still ran


async def test_goodbye_skips_if_they_come_back(hass):
    locks = async_mock_service(hass, "lock", "lock")
    hass.states.async_set("sensor.alice_room", "office")
    await _setup(
        hass,
        "goodbye_routine.yaml",
        {"person_sensors": ["sensor.alice_room"], "lock_doors": {"entity_id": "lock.front"}, "delay_minutes": 1},
    )

    hass.states.async_set("sensor.alice_room", "away")
    await _settle(hass)
    hass.states.async_set("sensor.alice_room", "entry")
    await _settle(hass)
    await _advance(hass, minutes=2)
    assert not locks


async def test_room_based_climate(hass):
    calls = async_mock_service(hass, "climate", "set_temperature")
    hass.states.async_set("sensor.alice_room", "kitchen")
    await _setup(hass, "room_based_climate.yaml", MINIMAL_INPUTS["room_based_climate.yaml"])

    hass.states.async_set("sensor.alice_room", "office", {"confidence": 0.8})
    await _settle(hass)
    assert [c.data["temperature"] for c in calls] == [72]

    hass.states.async_set("sensor.alice_room", "office", {"confidence": 0.9})
    await _settle(hass)
    assert len(calls) == 1  # Attribute-only update is ignored

    hass.states.async_set("sensor.alice_room", "kitchen")
    await _settle(hass)
    assert [c.data["temperature"] for c in calls] == [72, 68]


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [
        (None, "office"),
        ("office", None),
        ("unknown", "office"),
        ("office", "unknown"),
        ("unavailable", "office"),
        ("office", "unavailable"),
    ],
)
async def test_room_based_climate_ignores_invalid_states(hass, caplog, from_state, to_state):
    calls = async_mock_service(hass, "climate", "set_temperature")
    if from_state is not None:
        hass.states.async_set("sensor.alice_room", from_state)
    await _setup(hass, "room_based_climate.yaml", MINIMAL_INPUTS["room_based_climate.yaml"])

    if to_state is None:
        hass.states.async_remove("sensor.alice_room")
    else:
        hass.states.async_set("sensor.alice_room", to_state)
    await hass.async_block_till_done()

    assert not calls
    assert not any(record.levelname == "ERROR" for record in caplog.records)


@pytest.mark.parametrize(("confidence", "moves"), [(0.65, False), (0.76, True)])
async def test_follow_me_music_confidence_gate(hass, confidence, moves):
    pauses = async_mock_service(hass, "media_player", "media_pause")
    plays = async_mock_service(hass, "media_player", "media_play")
    hass.states.async_set("sensor.alice_room", "office", {"confidence": 0.9})
    await _setup(hass, "follow_me_music.yaml", MINIMAL_INPUTS["follow_me_music.yaml"])

    hass.states.async_set("sensor.alice_room", "kitchen", {"confidence": confidence})
    await _settle(hass)
    await _advance(hass, seconds=2)

    if moves:
        assert pauses[0].data["entity_id"] == ["media_player.office"]
        assert plays[0].data["entity_id"] == ["media_player.kitchen"]
    else:
        assert not pauses and not plays
