# Services & events

This page lists every service (called an "action" in newer Home Assistant versions) that Roomer registers, and every event it fires.

You can try any of these from **Developer Tools → Actions** (called **Services** in older versions). Each one has a form, or you can switch to **YAML mode** and paste an example.

## Services

| Service | What it does |
|---|---|
| [`roomer.refresh`](#roomerrefresh) | Runs presence detection right away instead of waiting for the next update |
| [`roomer.correct_room`](#roomercorrect_room) | Tells Roomer where someone really is, so it can learn from it |
| [`roomer.get_history`](#roomerget_history) | Returns someone's recent room changes |
| [`roomer.clear_history`](#roomerclear_history) | Deletes room-change history for one person or everyone |
| [`roomer.get_patterns`](#roomerget_patterns) | Returns routines Roomer has spotted in someone's history |
| [`roomer.identify_person`](#roomeridentify_person) | Takes a camera snapshot and asks a vision model who is in it |
| [`roomer.enable_tracking`](#roomerenable_tracking-roomerdisable_tracking) | Turns on a PTZ camera's auto-tracking switch |
| [`roomer.disable_tracking`](#roomerenable_tracking-roomerdisable_tracking) | Turns off a PTZ camera's auto-tracking switch |
| [`roomer.cleanup_storage`](#roomercleanup_storage) | Trims Roomer's event log file |

!!! note "Getting results back"
    `get_history` and `get_patterns` **only** return data, so you must call them with a `response_variable` in a script or automation (in Developer Tools the response is shown below the form). `identify_person` and `cleanup_storage` can return data too, and they also fire an event with the same result, listed under [Events](#events). The other services return nothing.

### `roomer.refresh`

Runs a presence update now. Useful right after something happens that Roomer should notice quickly, such as a door opening.

| Field | Required | Type | Description |
|---|---|---|---|
| `entity_id` | no | entity ID | Accepted for future use. In the current version every person and pet is refreshed, whatever you pass. |

```yaml
service: roomer.refresh
```

### `roomer.correct_room`

Sets a person's room sensor to the room you give and teaches Roomer's [habit learning](../getting-started/how-it-works.md#5-learn-habits) that this person is in that room at this time of day.

| Field | Required | Type | Default | Description |
|---|---|---|---|---|
| `entity_id` | yes | entity ID | | A Roomer room sensor (`sensor.<name>_room`), such as `sensor.alice_room`. It can have any entity ID: Roomer finds the person or pet from the sensor's registry entry. |
| `room` | yes | text | | One of your configured rooms, or `away` or `unknown`. Case, spaces and dashes are ignored (`Living Room` is `living_room`). |
| `confidence` | no | number 0.0–1.0 | `1.0` | How sure you are. Habits are only learned from values of 0.7 or more. |

The call fails with an error, and changes nothing, when `entity_id` is not a Roomer room sensor or `room` is not a configured room.

```yaml
service: roomer.correct_room
data:
  entity_id: sensor.alice_room
  room: office
```

Things to know:

- **A correction holds while nothing contradicts it.** At the next regular update Roomer recalculates. If no mapped entity is active, the person stays in the room you set (`source: sticky`, confidence fading over time). An active clue elsewhere takes over. The lasting effect is the learned habit, which nudges future guesses at the same time of day.
- **The person's name comes from Roomer's configuration, not from the entity ID.** The sensor's registry entry says whose it is, so `sensor.ben_room_3` or a renamed sensor still teaches the habit to `Ben`. If the entity has no registry entry, Roomer matches `sensor.<name>_room` against your configured names. When Roomer isn't set up at all, it falls back to the old behaviour of turning `sensor.mary_jane_room` into `Mary Jane`.
- The habit is saved to disk straight away.

### `roomer.get_history`

Returns the most recent room changes Roomer has seen for a person.

| Field | Required | Type | Default | Description |
|---|---|---|---|---|
| `entity_name` | yes | text | | The person's configured name, such as `Alice` |
| `limit` | no | integer 1–100 | `20` | How many changes to return, newest last |

```yaml
service: roomer.get_history
data:
  entity_name: Alice
  limit: 5
response_variable: history
```

The response looks like this:

```yaml
transitions:
  - entity_name: Alice
    from_room: bedroom
    to_room: kitchen
    timestamp: "2026-10-21T07:42:10.512345"
    confidence: 0.62
```

How history is recorded:

- A change is recorded every time Roomer moves someone to a different room, including to and from `away`.
- Results of `unknown` are skipped, and so is the first room after Home Assistant starts, since there is nothing to compare it with.
- History is kept in `/config/roomer_history.json`: up to 1000 changes in total and the last 100 per person. It is saved every 10 changes, when Roomer is reloaded and when Home Assistant stops.

### `roomer.clear_history`

Deletes recorded room changes. The file on disk is updated straight away.

| Field | Required | Type | Description |
|---|---|---|---|
| `entity_name` | no | text | Only clear this person's history. Leave it out to clear everyone's. |

```yaml
service: roomer.clear_history
data:
  entity_name: Alice
```

This does not touch learned habits or the event log.

### `roomer.get_patterns`

Looks through a person's [history](#roomerget_history) for simple routines: where they usually go in the morning (06:00–10:59) and in the evening (18:00–22:59).

| Field | Required | Type | Description |
|---|---|---|---|
| `entity_name` | yes | text | The person's configured name |

```yaml
service: roomer.get_patterns
data:
  entity_name: Alice
response_variable: patterns
```

The response looks like this:

```yaml
patterns:
  - type: morning_routine
    description: Usually in kitchen in the morning
    confidence: 0.6
```

`patterns` is empty until there are at least 10 recorded changes for the person, and each routine needs at least 3 changes in its time window. `confidence` is the share of those changes that went to the named room.

### `roomer.identify_person`

Grabs a snapshot from a camera and sends it to a vision model on your Ollama server, together with the names of the people (or pets) you configured, and asks who it is. The answer appears on [`sensor.vision_last_identification`](entities.md), in the [`roomer_vision_identification`](#roomer_vision_identification) event, and in the service response if you ask for one.

| Field | Required | Type | Default | Description |
|---|---|---|---|---|
| `camera_entity_id` | yes | entity ID | | The `camera.*` entity to take a snapshot from |
| `detection_type` | no | `person` or `animal` | `person` | Whether to look for a person (matched against your configured people) or an animal (matched against your pets) |

```yaml
service: roomer.identify_person
data:
  camera_entity_id: camera.living_room
  detection_type: person
response_variable: seen   # optional
```

The response has the same fields as the [event](#roomer_vision_identification), except `camera` and `detection_type`.

How it works:

- The request goes to the **same server URL** you entered when setting up Roomer, so that must be an Ollama server.
- The vision model defaults to `moondream`. Pull it first with `ollama pull moondream`.
- The vision request times out after 60 seconds.
- Vision results do **not** currently change anyone's room sensor; they only update the vision sensor and fire the event.

### `roomer.enable_tracking` / `roomer.disable_tracking`

Turn a PTZ camera's auto-tracking on or off. Roomer simply calls `switch.turn_on` / `switch.turn_off` on an entity named `switch.<camera_name>_auto_tracking`, which is how the Reolink integration names that switch.

| Field | Required | Type | Description |
|---|---|---|---|
| `camera_name` | yes | text | The middle part of the switch's entity ID. For `switch.e1_zoom_auto_tracking`, use `e1_zoom`. |

```yaml
service: roomer.enable_tracking
data:
  camera_name: e1_zoom
```

If your camera's switch has a different name, just call `switch.turn_on` on it directly.

### `roomer.cleanup_storage`

Roomer keeps a log of its decisions in `/config/roomer_events.jsonl`. It trims this file automatically when Home Assistant starts and every 24 hours after that, removing entries older than 30 days and keeping the file under 100 MB. Call this service to clean up right away or with tighter limits.

| Field | Required | Type | Range | Description |
|---|---|---|---|---|
| `retention_days` | no | integer | 1–365 | Delete entries older than this many days |
| `max_file_size_mb` | no | number | 1–1000 | Trim the oldest entries until the file is under this size |

```yaml
service: roomer.cleanup_storage
data:
  retention_days: 7
  max_file_size_mb: 20
```

!!! note
    The values you pass here stay in effect for the automatic daily cleanup too, until Roomer is reloaded or Home Assistant restarts.

When it finishes, it fires [`roomer_storage_cleanup`](#roomer_storage_cleanup). If you ask for a response, you get the same fields plus `success: true`.

## Events

You can watch any of these live in **Developer Tools → Events**: type the event name under "Listen to events" and click **Start listening**.

| Event | Fired when |
|---|---|
| [`roomer_person_arrived`](#roomer_person_arrived) | Someone goes from `away` to a room in the house |
| [`roomer_person_left`](#roomer_person_left) | Someone goes from a room in the house to `away` |
| [`roomer_room_changed`](#roomer_room_changed) | Someone moves from one room in the house to another |
| [`roomer_vision_identification`](#roomer_vision_identification) | `roomer.identify_person` finishes, whether it succeeded or failed |
| [`roomer_storage_cleanup`](#roomer_storage_cleanup) | `roomer.cleanup_storage` finishes |

### Arrival, departure and room-change events

Roomer fires these when a person's or pet's room changes from one update to the next. They follow the same answers as `sensor.<name>_room`, so they are a convenient way to react to anyone without listing every sensor.

- **Nothing fires when Home Assistant starts or Roomer reloads.** The first answer after that only sets a starting point. If Alice is already in the kitchen at startup, you don't get an "arrived" event.
- **`unknown` is ignored.** If Roomer can't decide for one update, it keeps the last known room, so a hiccup doesn't count as leaving and coming back.
- **Arrival and departure need `away`.** A person is only `away` when every device tracker assigned to them says they aren't home (see [Entities](entities.md)). Without a device tracker, you only get `roomer_room_changed`.
- **They fire on every change, including brief ones.** An event trigger has no `for:` option. If you need a room to hold for a while before acting, trigger on the room sensor with `for:` instead (see [Automations](automations.md#before-you-start-avoid-flicker)).

`timestamp` is an ISO-format local time string, and `confidence` is a number from 0.0 to 1.0.

#### `roomer_person_arrived`

| Field | Type | Description |
|---|---|---|
| `entity_name` | text | The configured name, such as `Alice` |
| `room` | text | The room they arrived in |
| `confidence` | number | Roomer's confidence in that room |
| `timestamp` | text | When it happened |

#### `roomer_person_left`

| Field | Type | Description |
|---|---|---|
| `entity_name` | text | The configured name |
| `last_room` | text | The room they were in before leaving |
| `timestamp` | text | When it happened |

#### `roomer_room_changed`

| Field | Type | Description |
|---|---|---|
| `entity_name` | text | The configured name |
| `from_room` | text | The previous room |
| `to_room` | text | The new room |
| `confidence` | number | Roomer's confidence in the new room |
| `timestamp` | text | When it happened |

Example: log every room change to the logbook.

```yaml
alias: "Log Roomer room changes"
mode: queued
trigger:
  - platform: event
    event_type: roomer_room_changed
action:
  - service: logbook.log
    data:
      name: "{{ trigger.event.data.entity_name }}"
      message: >
        moved from {{ trigger.event.data.from_room }}
        to {{ trigger.event.data.to_room }}
```

To react to one person only, add `event_data: {entity_name: Alice}` under the trigger.

### `roomer_vision_identification`

| Field | Type | Description |
|---|---|---|
| `camera` | text | The camera entity used |
| `detection_type` | text | `person` or `animal` |
| `success` | boolean | `true` if the vision model answered, `false` if something failed |
| `identified` | text | The configured person or pet name the model matched, otherwise what it said (for example `unknown` or `cat`). Present only when `success` is `true`. |
| `confidence` | text | `high`, `medium` or `low`, as the model reported it. Present only when `success` is `true`. |
| `description` | text | The model's short description of the image. Present only when `success` is `true`. |
| `raw_response` | text | The model's full reply. Present only when `success` is `true`. |
| `error` | text | What went wrong, such as `Failed to get camera snapshot` or `Vision model timeout`. Present only when `success` is `false`. |

Example: announce who was seen at the front door.

```yaml
alias: "Announce who is at the door"
trigger:
  - platform: event
    event_type: roomer_vision_identification
    event_data:
      camera: camera.front_door
      success: true
condition:
  - condition: template
    value_template: "{{ trigger.event.data.confidence in ['high', 'medium'] }}"
action:
  - service: notify.mobile_app_your_phone
    data:
      message: "{{ trigger.event.data.identified }} is at the front door"
```

### `roomer_storage_cleanup`

| Field | Type | Description |
|---|---|---|
| `deleted_by_time` | integer | Entries removed for being older than the retention period |
| `deleted_by_size` | integer | Entries removed to get under the size limit |
| `total_deleted` | integer | Total entries removed |
| `total_kept` | integer | Entries left in the file |
| `final_size_mb` | number | File size after cleanup, in MB |

## Services you may see mentioned elsewhere

Older documentation mentions `roomer.request_vision_update`. It isn't registered, so calling it fails with a "service not found" error. Use [`roomer.identify_person`](#roomeridentify_person) instead.
