"""Indicator typing (device_class first) and room_entities normalisation."""

from __future__ import annotations

import pytest

from custom_components.roomer.entity_hints import guess_detects, guess_entity_hint, normalize_room_entities


class TestGuessEntityHint:
    def test_mmwave_presence_sensor_is_motion_by_device_class(self):
        """binary_sensor.presence_living_room was typed "appliance" from its name alone."""
        assert guess_entity_hint("binary_sensor.presence_living_room", "presence") == "motion"

    def test_third_reality_motion_sensor_by_device_class(self):
        assert guess_entity_hint("binary_sensor.third_reality_inc_3rms16bz", "motion") == "motion"

    @pytest.mark.parametrize("device_class", ["motion", "occupancy", "presence", "moving"])
    def test_motion_family_device_classes(self, device_class):
        assert guess_entity_hint("binary_sensor.xyz_1234", device_class) == "motion"

    @pytest.mark.parametrize("device_class", ["door", "window", "garage_door", "opening"])
    def test_door_family_device_classes(self, device_class):
        assert guess_entity_hint("binary_sensor.xyz_1234", device_class) == "door"

    def test_device_class_beats_a_misleading_name(self):
        assert guess_entity_hint("binary_sensor.office_door_thing", "motion") == "motion"

    def test_presence_in_name_is_motion_without_device_class(self):
        assert guess_entity_hint("binary_sensor.presence_living_room") == "motion"

    def test_unknown_device_class_falls_back_to_substrings(self):
        assert guess_entity_hint("binary_sensor.office_motion", "battery") == "motion"
        assert guess_entity_hint("binary_sensor.front_door", "lock") == "door"

    def test_unknowns_are_appliance(self):
        assert guess_entity_hint("binary_sensor.third_reality_inc_3rms16bz") == "appliance"
        assert guess_entity_hint("switch.coffee_maker") == "appliance"

    def test_domains(self):
        assert guess_entity_hint("light.kitchen_motion_light") == "light"
        assert guess_entity_hint("media_player.living_room_tv") == "media"
        assert guess_entity_hint("camera.front") == "camera"
        assert guess_entity_hint("device_tracker.phone") == "presence"

    def test_pc_and_tv_match_whole_words_only(self):
        assert guess_entity_hint("switch.office_pc") == "computer"
        assert guess_entity_hint("switch.carpet_heater") == "appliance"
        assert guess_entity_hint("switch.upcoming_pcb") == "appliance"
        assert guess_entity_hint("switch.living_tv") == "media"

    def test_camera_detection_sensors(self):
        assert guess_entity_hint("binary_sensor.reolink_person", "motion") == "camera"
        assert guess_entity_hint("binary_sensor.reolink_animal", "motion") == "camera"

    def test_existing_substring_behaviour_is_kept(self):
        assert guess_entity_hint("sensor.room_temperature") == "climate"
        assert guess_entity_hint("binary_sensor.window_contact") == "door"


class TestGuessDetects:
    def test_person_and_animal(self):
        assert guess_detects("binary_sensor.reolink_person") == "person"
        assert guess_detects("binary_sensor.reolink_animal") == "animal"
        assert guess_detects("binary_sensor.reolink_pet") == "animal"

    def test_friendly_name_is_used(self):
        assert guess_detects("binary_sensor.cam_1", "Kitchen camera Person") == "person"

    def test_default_is_any(self):
        assert guess_detects("binary_sensor.office_motion") == "any"
        assert guess_detects("binary_sensor.carpet_motion") == "any"


class TestNormalizeRoomEntities:
    def test_old_single_room_config_gets_defaults(self):
        old = {"office": [{"entity_id": "binary_sensor.office_motion", "hint_type": "motion"}]}

        assert normalize_room_entities(old) == {
            "office": [
                {"entity_id": "binary_sensor.office_motion", "hint_type": "motion", "weight": 1.0, "detects": "any"}
            ]
        }

    def test_plain_entity_ids_are_accepted(self):
        result = normalize_room_entities({"office": ["binary_sensor.office_motion"]})

        assert result["office"][0]["hint_type"] == "motion"

    def test_rooms_list_expands_and_splits_weight(self):
        raw = {"kitchen": [{"entity_id": "binary_sensor.cam_person", "hint_type": "camera", "rooms": ["living_room"]}]}

        result = normalize_room_entities(raw)

        assert result["kitchen"][0]["weight"] == 0.5
        assert result["living_room"][0]["entity_id"] == "binary_sensor.cam_person"
        assert "rooms" not in result["kitchen"][0]

    def test_explicit_weight_and_detects_are_kept(self):
        raw = {"kitchen": [{"entity_id": "x.y", "hint_type": "camera", "weight": 0.4, "detects": "person"}]}

        entry = normalize_room_entities(raw)["kitchen"][0]

        assert (entry["weight"], entry["detects"]) == (0.4, "person")

    def test_bad_values_are_repaired(self):
        raw = {"a": [{"entity_id": "x.y", "weight": "lots", "detects": "cats"}, {"nope": 1}, 5], "b": "junk"}

        result = normalize_room_entities(raw)

        assert result == {"a": [{"entity_id": "x.y", "hint_type": "appliance", "weight": 1.0, "detects": "any"}]}

    def test_is_idempotent(self):
        once = normalize_room_entities({"office": ["binary_sensor.office_motion"]})
        assert normalize_room_entities(once) == once

    def test_not_a_dict(self):
        assert normalize_room_entities(None) == {}
