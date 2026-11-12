# Entities

Roomer creates a small set of entities for every person and pet you set up. This page lists each one, the states it can have, and every attribute it carries.

!!! info "Entity IDs come from your names, not from \"roomer\""
    Home Assistant builds each entity ID from the entity's **name**, and Roomer names its entities after the people, pets and rooms you configured. If you added a person called `Alice` and a room called `office`, you get `sensor.alice_room` and `binary_sensor.alice_in_office`. Nothing is called `sensor.roomer_...`.

    Names with spaces become underscores: a person called `Mary Jane` gets `sensor.mary_jane_room`, and the room `living_room` gives `binary_sensor.mary_jane_in_living_room`.

To see them all, go to **Settings → Devices & services → Roomer** and open the **Entities** tab.

## At a glance

| Entity | One per | Example | What it tells you |
|---|---|---|---|
| Room sensor | person and pet | `sensor.alice_room` | Which room they are in right now |
| Room occupancy binary sensor | person (or pet) × room | `binary_sensor.alice_in_office` | `on` when they are in that room |
| Room occupants sensor | room | `sensor.kitchen_occupants` | How many people are in that room, and who |
| Vision sensor | integration | `sensor.vision_last_identification` | Result of the last camera identification |

## Room sensor: `sensor.<name>_room`

The main entity. Its state is the room Roomer thinks the person or pet is in.

- **Name:** `<Name> Room` (for example "Alice Room")
- **Icon:** `mdi:account` for people, `mdi:paw` for pets
- **Unique ID:** `roomer_person_alice_room` or `roomer_pet_fido_room`

### States

| State | Meaning |
|---|---|
| A room name, such as `office` or `living_room` | One of the rooms you configured. Room names are always lowercase with underscores. |
| `away` | One of the device trackers assigned to this person reports they are not home. See below. |
| `unknown` | Roomer had nothing to go on: no mapped sensor was active and the AI's answer could not be matched to one of your rooms. It also appears briefly before the first update finishes. |
| `unavailable` | The last update failed completely. Check the logs. |

!!! note "How `away` works"
    `away` comes from **device trackers**, such as the Home Assistant Companion app on a phone. A person shows as `away` only when at least one `device_tracker.*` entity is listed under their devices (**Configure → Person Device Ownership**) and **none** of those trackers say `home`. A tracker in another zone (for example `work`) counts as not home. Trackers that are `unavailable` or `unknown` are ignored.

    If a person has no device tracker assigned, Roomer will almost never show them as `away`. Pets never get the device-tracker check.

    A device that reports a room (see [Map your rooms](../getting-started/map-rooms.md#devices-that-report-a-room)) and changed more recently than the tracker wins over `away`.

### Attributes

| Attribute | Type | Example | Meaning |
|---|---|---|---|
| `confidence` | number, 0.0 to 1.0 | `0.46` | How strongly the signals point to this room. It is a fraction, **not** a percentage, and not a true probability. See [Accuracy & limits](accuracy.md). |
| `indicators` | list of text | see below | Human-readable clues behind the decision. Up to five `hint_type: entity` entries for active mapped sensors, followed by a one-line summary from the confidence combiner. When nothing mapped is active it is `["No active clues; time-of-day guess"]` (source `prior`) or a single "Last seen in the office 12m ago; no active clues" line (source `sticky`). |
| `raw_response` | text | `ROOM: office` | Exactly what the AI model replied. When the person is away by device tracker it reads `Device tracker indicates not home`. When a device located them it names the device, such as `sensor.alice_phone_area reports Office`. When the AI server could not be reached it holds the error message, which may be empty for a timeout. |
| `source` | text | `sensor` | Where the room came from: `sensor` (an active mapped entity, with the AI and habits as a tie-break), `device_room` (a device of theirs reported it), `device_tracker` (away), `sticky` (nothing is active, so they stay where they were last seen), `prior` (nothing is active and nothing recent: only a time-of-day guess from the AI and habits, with low confidence), `manual_correction` (set with `roomer.correct_room`) or `llm` (an AI result Roomer did not combine with anything). |
| `last_changed_reason` | text | `motion: hallway_motion` | Why the room last changed: the first clue at the moment it changed, or the source (`device_room`, `manual_correction`) when there was none. It stays the same while the room stays the same, so a UI can say "moved to the hallway because of hallway_motion". Empty until the first update. |
| `room_area_id` | text or `null` | `living_room` | The Home Assistant area id of the current room, so a dashboard can map rooms to areas without guessing. See [Room areas](../getting-started/map-rooms.md#room-areas). `null` for `away`, `unknown` and rooms with no area. |
| `candidate_rooms` | list of text | `["kitchen", "living_room"]` | Only present when one entity covers several rooms (a camera that sees both) and raised more than one room equally. The first is the room in the state. See [One entity, several rooms](../getting-started/map-rooms.md#one-entity-several-rooms). |
| `entity_type` | text | `person` | `person` or `pet`. |

A typical `indicators` value while Alice works at her PC with the desk lamp on:

```yaml
indicators:
  - "computer: alice_pc"
  - "light: office_lamp"
  - "computer: alice_pc | LLM: office"   # combiner summary: strong signals + the AI's pick
```

`indicators` and `raw_response` are the first two things to look at when a result seems wrong. The [Troubleshooting](troubleshooting.md) page explains how to read them.

!!! tip "Last changed time"
    Roomer doesn't add its own timestamp attribute. Use Home Assistant's built-in `last_changed` (when the room last changed) and `last_updated`, for example `{{ states.sensor.alice_room.last_changed }}`.

## Room occupancy binary sensors: `binary_sensor.<name>_in_<room>`

For every person and pet, Roomer creates one binary sensor for each configured room. With two people and five rooms, that is ten binary sensors. They are the easiest thing to use in automations, because they are simply `on` or `off`.

- **Name:** `<Name> in <Room>`, where the room is title-cased with spaces ("Alice in Living Room")
- **Device class:** `occupancy`, so the UI shows "Detected" / "Clear"
- **Icon:** `mdi:account-check` for people, `mdi:paw` for pets
- **Unique ID:** `roomer_person_alice_living_room`

### States

| State | Meaning |
|---|---|
| `on` | The room sensor for this person currently shows this room |
| `off` | They are somewhere else, including `away` or `unknown` |
| `unknown` | No data yet |

There is no `..._in_away` binary sensor, because `away` is not a room you configure. To react to someone leaving, watch the room sensor's state instead (see [Automations](automations.md)).

### Attributes

| Attribute | Type | Meaning |
|---|---|---|
| `confidence` | number, 0.0 to 1.0 | The person's confidence if they are in **this** room; `0.0` otherwise |
| `current_room` | text | Whatever room the person is in right now (same as the room sensor's state) |
| `room_area_id` | text or `null` | The Home Assistant area id this room maps to |
| `entity_type` | text | `person` or `pet` |

## Room occupants sensors: `sensor.<room>_occupants`

For every room you configured, Roomer creates a sensor that answers "who is in the kitchen right now?" in one entity. There is none for `away` or `unknown`.

- **Name:** `<Room> Occupants`, with the room title-cased ("Living Room Occupants")
- **Icon:** `mdi:account-group`
- **Unique ID:** `roomer_room_living_room_occupants`

### States

The state is the number of **people** in the room. Someone raised in two rooms by one shared entity (see [One entity, several rooms](../getting-started/map-rooms.md#one-entity-several-rooms)) counts in both. Pets are listed in the attributes but not counted, so a cat asleep in the office doesn't make the room count as occupied. It is `unknown` until the first update finishes.

### Attributes

| Attribute | Type | Example | Meaning |
|---|---|---|---|
| `people` | list of text | `["Alice", "Bob"]` | The people Roomer currently places in this room |
| `pets` | list of text | `["Miso"]` | The pets in this room |
| `confidence` | map of name to number | `{"Alice": 0.9, "Bob": 0.62}` | Each one's confidence in this room, 0.0 to 1.0 |
| `sources` | map of name to text | `{"Alice": "device_room", "Bob": "sensor"}` | Where each one's room came from, as for the `source` attribute above |
| `room_area_id` | text or `null` | `living_room` | The Home Assistant area id this room maps to |

```yaml
# Turn the office lights off five minutes after the last person leaves
automation:
  - alias: "Office lights off when nobody's there"
    trigger:
      - platform: state
        entity_id: sensor.office_occupants
        to: "0"
        for:
          minutes: 5
    action:
      - service: light.turn_off
        target:
          entity_id: light.office
```

## Vision sensor: `sensor.vision_last_identification`

One per Roomer installation. It shows the result of the most recent camera identification run by the [`roomer.identify_person`](services-events.md) service. It updates only when that service runs; Roomer never calls it on its own.

- **Name:** "Vision Last Identification"
- **Icon:** `mdi:camera-iris`
- **Unique ID:** `roomer_vision_last_identification`

### States

| State | Meaning |
|---|---|
| `none` | Nothing has been identified since Home Assistant started |
| A configured person or pet name, such as `Alice` | The vision model recognised someone you configured |
| Any other text, such as `cat` or `unknown` | What the model said when it didn't match a known name, or `unknown` if the request failed |

### Attributes

| Attribute | Type | Meaning |
|---|---|---|
| `confidence` | text | The model's own label: `high`, `medium` or `low` (`none` before the first run). Not a number. |
| `description` | text | The model's short description of the image |
| `camera` | text | The camera entity that was used, such as `camera.front_door` |
| `detection_type` | text | `person` or `animal` |
| `timestamp` | text | ISO time when this result arrived |
| `raw_response` | text | The vision model's full reply |

!!! warning "Vision results do not change the room sensors"
    In the current version, the identification result is shown only on this sensor and in the `roomer_vision_identification` event. It does **not** feed into `sensor.<name>_room`. You can still use it in your own automations.

The vision sensor does not keep its value across restarts; it returns to `none`.

!!! example "Screenshot needed: entities-list.png"
    The Roomer integration's Entities tab (Settings → Devices & services → Roomer → Entities) for a setup with two people, showing the `sensor.*_room` entities, several `binary_sensor.*_in_*` entities, and `sensor.vision_last_identification`.

!!! example "Screenshot needed: room-sensor-attributes.png"
    The more-info dialog for `sensor.alice_room` with the Attributes section expanded, showing `confidence`, `indicators`, `raw_response` and `entity_type` with realistic values.

## Using attributes in templates

Copy these into **Developer Tools → Template** to try them out:

```jinja
{# Room, prettified: "living_room" -> "Living Room" #}
{{ states('sensor.alice_room') | replace('_', ' ') | title }}

{# Confidence as a whole-number percentage #}
{{ (state_attr('sensor.alice_room', 'confidence') | float(0) * 100) | round }}%

{# The signals behind the current answer, one per line #}
{{ state_attr('sensor.alice_room', 'indicators') | join('\n') }}

{# Everyone Roomer currently places in the kitchen #}
{{ states.binary_sensor
   | selectattr('entity_id', 'search', '_in_kitchen$')
   | selectattr('state', 'eq', 'on')
   | map(attribute='name') | list }}
```
