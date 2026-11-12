# Map your rooms

Roomer only looks at entities you've told it about. You give it two kinds of
mapping:

- **Room mapping** says *where* things are. Example: the office motion sensor is
  in the office.
- **Device ownership** says *whose* things are. Example: this PC belongs to Alice.

Room mapping helps Roomer pick a room. Device ownership is what lets it tell
people apart.

## Before you start

You did your first room mapping in the last screen of [First setup](first-setup.md).
To change mappings later, or to assign devices to people, use Roomer's options:

1. Go to **Settings → Devices & services → Roomer**.
2. Select **Configure**.
3. Choose a section from the menu: **General Settings**, **Room Entity
   Mapping**, **Entity Covering Several Rooms**, **Room Areas**, **Person
   Device Ownership** or **Confidence Weights**.

!!! example "Screenshot needed: options-menu.png"
    The "Roomer Options" menu showing the four choices: General Settings, Room Entity Mapping, Person Device Ownership, Confidence Weights.

Each section saves only its own settings and keeps what you saved in the
others. The forms open with your last saved values. Roomer reloads itself when
you save, so changes take effect straight away. Your room sensors briefly
become unavailable while it restarts with the new settings.

## How Roomer reads an entity

When you map an entity to a room, Roomer decides what **type** of clue it is.
It looks at the entity's domain and **device class** first (so a
`binary_sensor` with the `motion`, `occupancy` or `presence` device class is
motion, whatever it is called, which covers mmWave presence sensors and
sensors named after a model number), then at words in its entity ID. Roomer
checks these rules in order and uses the first one that matches:

| If… | Type | Default weight |
|---|---|---|
| it is a `light.`, `media_player.`, `camera.` or `device_tracker.` entity | light, media, camera or presence | 35%, 80%, 95%, 70% |
| a binary sensor's name has the word `person`, `animal`, `pet`, `human`, `dog` or `cat` | camera | 95% |
| its device class is `motion`, `occupancy`, `presence` or `moving` | motion | 60% |
| its device class is `door`, `window`, `garage_door` or `opening` | door | 40% |
| the entity ID contains `motion` or `occupancy`, or the word `presence` | motion | 60% |
| the entity ID contains `media_player`, or the word `tv` | media | 80% |
| the entity ID contains the word `pc`, or `computer` or `desktop` | computer | 85% |
| the entity ID contains `camera`, `person` or `animal` | camera | 95% |
| the entity ID contains `door`, `window` or `contact` | door | 40% |
| the entity ID contains `temperature` or `humidity` | climate | 20% |
| anything else | appliance | 50% |

The weight is how much the clue counts when Roomer
[combines the evidence](how-it-works.md#4-combine-the-evidence).

An entity counts as a clue only while it's **active**, which means its state is
`on`, `home`, `detected`, `playing`, `open` or `occupied`. A media player also
counts when it's `paused`, at a lower weight.

!!! tip "Name things so Roomer guesses right"
    The type is worked out once, when you save the mapping. If a name gives the
    wrong type (for example, `switch.tv_room_lamp` would count as media), rename
    the entity ID in Home Assistant first, then map it again. Use the
    person-detection **binary sensor** from your camera system (like
    `binary_sensor.kitchen_person`), not the `camera.` entity itself. A camera
    entity's state is never "active".

## Room Entity Mapping

This screen has one picker per room, labelled with the room's name. It accepts binary sensors, sensors, lights,
switches, media players, device trackers and cameras. For each room, add the
things that show someone is in that room right now.

Good choices:

- motion and occupancy sensors
- the room's main lights
- TVs, speakers and consoles
- computers and their "in use" sensors
- door sensors for rooms with one main door
- camera person-detection sensors

!!! warning "Don't map phones to rooms"
    A phone's `device_tracker` says `home` wherever you are in the house. If you
    map it to a room, Roomer treats that room as active whenever anyone's phone
    is home. Assign phones under **Person Device Ownership** instead.

Remember that room-mapped entities count **equally for everyone at home**. The
office motion sensor doesn't know who moved.

!!! example "Screenshot needed: options-room-entities.png"
    The "Room Entity Mapping" options screen with several entities selected for the office and living room.

## Person Device Ownership

This screen has one picker per person and pet, labelled with their name. It accepts device trackers,
binary sensors, switches and sensors. Add the devices that belong to that person.

Roomer uses them in three ways:

- **Devices that report a room place that person.** A phone, watch or tag that
  says which room it's in (Bluetooth room tracking, such as Bermuda or
  ESPresense) puts its owner in that room. See
  [Devices that report a room](#devices-that-report-a-room) below.
- **Device trackers decide home or away.** If all of a person's
  `device_tracker` entities say they're away, Roomer marks them `away` straight
  away, at 95% confidence. If any says `home`, Roomer works out which room
  they're in.
- **Other devices point to that person.** When an owned device is active, it
  counts as a strong clue (computer weight, 85%) for that person only, in the
  device's room. **The device must also be mapped to a room** under Room Entity
  Mapping, or Roomer won't know where it is and will ignore it.

Pets appear on this screen too. Only a device that reports a room (such as a
Bluetooth tag on a collar) is used for a pet.

!!! example "Screenshot needed: options-person-devices.png"
    The "Person Device Ownership" options screen with a phone tracker and a PC switch assigned to Alice, and a phone tracker and gaming PC assigned to Bob.

### Devices that report a room

Bluetooth room-presence tools tell you which room a phone, watch or tag is in.
Assign that entity to its owner here, and Roomer takes the room it reports. It
doesn't ask the language model, because this is the one clue that belongs to a
single person. **Nothing else in the house, such as someone else's motion or PC,
can pull them into another room.** The entity does not need to be mapped under
Room Entity Mapping.

| Tool | Entity to assign | Reports |
|---|---|---|
| [Bermuda](https://github.com/agittins/bermuda) | The device's **Area** sensor, such as `sensor.alice_phone_area` | The area's name, such as `Office` |
| ESPresense or room-assistant, through Home Assistant's [`mqtt_room`](https://www.home-assistant.io/integrations/mqtt_room/) sensor | The `mqtt_room` sensor you create for each device | The room name the node reports, such as `office` |

Your entity names will differ. What matters is that the entity's state is a
room or area name. Roomer also reads the room from an `area_id`, `area_name`,
`area` or `room` attribute, so Bermuda's Area sensor works either way. Bermuda
also creates a home/away `device_tracker` for each device. Assign that too, so
Roomer can tell when someone has left.

- **The names must match your Roomer rooms.** Capitals, spaces and dashes don't
  matter, so `Living Room`, `living-room` and `living_room` are the same. If a
  sensor ending in `_area` or `_room`, or a device tracker, reports a room that
  Roomer doesn't have, the log shows a warning naming the entity and the value.
  Rename the area in Home Assistant or the room in Roomer so they agree.
- **How sure Roomer is.** One device, or several that agree: `source` is
  `device_room` and `confidence` is 0.9. If a person's devices disagree (a phone
  left on the desk while the watch moves with them), the room most devices report
  wins, then the device that changed most recently, at 0.7.
- **Roomer trusts the device.** It reports where the *device* is, not where the
  person is. A phone charging in the bedroom keeps its owner in the bedroom.
  Assign a second device they carry, such as a watch. When one person's devices
  name different rooms, the one that moved most recently wins.
- **When there's no room to read,** such as `unknown`, `unavailable` or
  `not_home`, Roomer carries on with its normal steps for that person.
- **Home or away still applies.** If a home/away tracker went `not_home` *after*
  the room device last changed, the person is `away`. If the room device changed
  more recently, the room wins. Bluetooth usually sees someone arrive before
  Wi-Fi does, and a room sensor can keep its last room for a while after someone
  leaves. Set a timeout in your Bluetooth tool (for example `away_timeout` on an
  `mqtt_room` sensor, which switches it to `not_home`) so it stops reporting a
  room once the device is gone.
- **GPS trackers only decide home or away.** A phone's GPS tracker reports Home
  Assistant *zones*, so a work zone called `Office` is never read as the office
  room.

## Worked example

Alice and Bob live with their cat, Miso. Their rooms are `office`,
`living_room`, `bedroom` and `kitchen`.

### Room mapping

| Room | Entity | Type Roomer picks |
|---|---|---|
| office | `binary_sensor.office_motion` | motion |
| office | `light.office` | light |
| office | `switch.alice_pc` | computer |
| living_room | `binary_sensor.living_room_motion` | motion |
| living_room | `media_player.living_room_tv` | media |
| living_room | `switch.bob_gaming_pc` | computer |
| living_room | `binary_sensor.living_room_person` | camera |
| bedroom | `light.bedroom` | light |
| bedroom | `binary_sensor.bedroom_door` | door |
| kitchen | `binary_sensor.kitchen_motion` | motion |
| kitchen | `light.kitchen` | light |

### Device ownership

| Person | Devices |
|---|---|
| Alice | `device_tracker.alice_phone`, `switch.alice_pc` |
| Bob | `device_tracker.bob_phone`, `switch.bob_gaming_pc` |
| Miso | *(none)* |

Both PCs appear in **both** tables. The room mapping says where each PC is, and
the ownership mapping says whose it is.

### What Roomer can work out

| Situation | Likely result | Why |
|---|---|---|
| Alice at her desk, Bob out | Alice: `office`. Bob: `away` | Bob's phone says away. Alice's own PC is on in the office |
| Alice at her desk, Bob gaming | Alice: `office`. Bob: `living_room` | Each person's own PC gives them a clue the other doesn't get |
| Both cooking, PCs off | Both: `kitchen` | Kitchen motion and light count for both, which happens to be right |
| Alice napping in the dark bedroom, Bob in the kitchen | Both may show `kitchen` | Nothing ties either person to a room. Only anonymous sensors are active |
| Miso anywhere | A rough guess | Pets only get anonymous clues |

The fourth row shows Roomer's main limit. When the only active sensors are
shared ones, it can't tell who's who. Adding one personal signal per person,
like room-level phone tracking, fixes most of these cases. See
[What you'll need](requirements.md#how-good-are-your-signals) and
[Accuracy & limits](../using/accuracy.md).

## Check the result

Open `sensor.alice_room` in **Settings → Devices & services → Entities**, or in
**Developer tools → States**. Look at these attributes:

- `confidence`: from 0 to 1. For example, `0.82` means 82%.
- `indicators`: the clues Roomer used, such as `computer: alice_pc` or `device: alice_phone_area in office`.
- `source`: where the answer came from. `device_room` means one of their devices reported the room, `device_tracker` means away, `sensor` means an active mapped entity decided it, `sticky` means nothing is active so they are still where they were last seen, and `prior` means only a low-confidence time-of-day guess. The [entities page](../using/entities.md) lists every attribute, including `last_changed_reason` and `room_area_id`.

If a device you expected isn't listed, check that it's mapped to a room and is
currently active.

!!! example "Screenshot needed: sensor-attributes-indicators.png"
    Developer tools → States filtered to sensor.alice_room, showing the confidence and indicators attributes.

## General Settings

| Setting | What it does | Default |
|---|---|---|
| **Poll Interval (seconds)** | How often Roomer guesses again (5–300) | Your setup value, or 10 |
| **LLM Request Timeout (seconds)** | How long to wait for the model before using the fallback rules (5–120) | 30 |
| **Enable Pattern Learning** | Learn habits from confident guesses | On |

## Confidence Weights

This screen has a slider (0–100%) for each type of clue: camera, computer,
media, motion, presence, appliance, light, door, the language model's reasoning
(`llm_reasoning`) and learned habits (`habit`). Raise a weight to make that type count for more.
Most people can leave these alone.

Next: learn about the [entities Roomer creates](../using/entities.md), or start
building [automations](../using/automations.md).

## One entity, several rooms

Some sensors see more than one room. A camera in the kitchen may also watch the
living room. Map such an entity with **Entity Covering Several Rooms** in the
options (not the per-room pickers, though those work too):

| Field | What it does |
|---|---|
| **Entity** | The sensor, for example `binary_sensor.reolink_person` |
| **Rooms it covers** | Every room it can see. Leave empty to remove the entity from all rooms. |
| **What it detects** | `People and animals`, `People only` or `Animals only`. The default works it out from the name (`person`, `human` → people; `animal`, `pet`, `dog`, `cat` → animals). |
| **Split its weight between the rooms** | Off (default): each room gets the full evidence, so a person detection raises both rooms equally. On: the rooms share it, so each counts for less. |

When the entity is active and nothing else decides between its rooms, Roomer keeps
the person in the room they were in before. The other room is listed in the
`candidate_rooms` attribute, and both rooms' occupants sensors and
`binary_sensor.<name>_in_<room>` show them. Other evidence still wins: a TV
playing in the living room settles it for the living room.

A person detection only counts for **people** and an animal detection only for
**pets**. A mapped entity is stored under each of its rooms as
`{entity_id, hint_type, weight, detects}`, so you can also edit that in the
config entry's options. `weight` is a share from 0 to 1 and `detects` is
`person`, `animal` or `any`. Existing single-room mappings are migrated
automatically and behave as before.

## Room areas

**Room Areas** ties each of your rooms to a Home Assistant area. Roomer shows the
area's id in the `room_area_id` attribute of the room sensors, the occupants
sensors and the room binary sensors, so a floor plan or dashboard can place
rooms on areas without guessing from names. A room you leave blank is matched to
an area with the same name (ignoring case, spaces and dashes) when there is one;
otherwise `room_area_id` is `null`. `away` and `unknown` never have an area.
