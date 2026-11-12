# Troubleshooting

Find your symptom below and expand it. Each one lists the likely causes and what to check. First, here's how to see *why* Roomer made a decision.

## Looking under the hood

### 1. Read the room sensor's attributes

Go to **Developer Tools → States** and search for `sensor.alice_room` (use your person's name). The attributes on the right tell you what happened on the last update:

| Attribute | What it tells you |
|---|---|
| `indicators` | Which mapped sensors were active (`motion: hallway_motion`, `computer: alice_pc`, …), followed by a summary of the strongest signals and the AI's pick (`LLM: office`). `No signals available` means nothing was active and the AI gave no usable answer. Entries ending in `(fallback)` mean the AI couldn't be reached. |
| `raw_response` | The AI model's exact reply, for example `ROOM: office`. `Device tracker indicates not home` means the person is away by device tracker and the AI was skipped. An error message (or an empty value) together with a low confidence means the AI request failed. |
| `confidence` | 0.0 to 1.0. Around 0.7 to 0.95 when sensors and the AI agree, around 0.5 or lower when evidence is thin or split; see [Accuracy & limits](accuracy.md). A sudden drop for everyone usually means the AI is unreachable. |

!!! note "There is no `source` or `reasoning` attribute"
    Some older docs mention `source`, `reasoning` or `last_updated` attributes. Roomer doesn't expose those in the current version. Use `indicators` and `raw_response` instead.

### 2. Turn on debug logging

Add this to `configuration.yaml` and restart Home Assistant:

```yaml
logger:
  default: warning
  logs:
    custom_components.roomer: debug
```

Then open **Settings → System → Logs** and click **Show raw logs** (or **Load full logs**). Useful lines to look for:

| Log line | Meaning |
|---|---|
| `Ollama query for Alice (person): prompt_len=…` | Roomer is asking the AI about Alice |
| `Ollama response for Alice: 'ROOM: office'` | What the AI answered |
| `Confidence combiner changed Alice from office to kitchen (reason: …)` | The sensors outweighed the AI's pick |
| `Alice is away (device tracker: [...])` | A device tracker made her `away` |
| `Ollama request failed for Alice: …` (warning) | The AI request failed or timed out |
| `Fallback guess for Alice: living_room (30%) - …` | Roomer used its simple backup rules instead of the AI |
| `Finished fetching roomer data in 4.210 seconds` | How long one full update took |

To turn on debug logging without a restart, go to **Settings → Devices & services → Roomer** and choose **Enable debug logging**. Turning it off again downloads the log.

### 3. Look at the decision log

Roomer writes every decision, with the sensor states it saw, to `/config/roomer_events.jsonl`, one JSON object per line. It's handy for spotting patterns over time, such as "every evening Bob ends up in the office".

---

## Common problems

??? question "The room sensor is stuck on `unknown`"

    **Likely causes**

    - None of the sensors mapped to rooms are active, *and* the AI's answer couldn't be matched to one of your rooms. `indicators` shows `No signals available`.
    - No sensors are mapped to rooms at all, so Roomer is relying on the AI alone, which has nothing to go on.
    - Roomer hasn't finished its first update yet. This is normal for a few seconds after a restart, longer if the AI is slow.
    - The AI model answers with a room name that isn't one of yours (for example "lounge" when your room is `living_room`).

    **What to check**

    1. Look at `indicators` and `raw_response` on the room sensor.
    2. Make sure each room has at least one useful sensor mapped: **Settings → Devices & services → Roomer → Configure → Room Entity Mapping**. See [Map your rooms](../getting-started/map-rooms.md).
    3. With debug logging on, check the `Ollama response for …` line. If the model rambles or names rooms that don't exist, try a different model.

    If the state is **`unavailable`** rather than `unknown`, the whole update failed. Look in the logs for `Error fetching LLM presence data`.

??? question "Someone flips back and forth between two rooms"

    **Likely causes**

    - Two rooms have similar evidence, for example a light on in the living room and motion in the kitchen. Small changes tip the balance each update.
    - A sensor that's always on (a light left on, a TV on standby reporting `on`, a busy motion sensor) keeps pulling people toward one room.
    - The AI model's pick changes between updates, and nothing else is strong enough to settle it.
    - In multi-person homes, anonymous signals (motion, lights) are shared by everyone. See [Accuracy & limits](accuracy.md).

    **What to check**

    1. Open the room sensor's **History** and compare it with the `indicators` at each change.
    2. Remove or re-map sensors that are misleading. A hallway sensor mapped to the living room is a classic culprit.
    3. Lower the weight of noisy signal types (often `light`) under **Configure → Confidence Weights**, and save. Roomer reloads itself with the new weights.
    4. Give the person a personal signal, such as their own PC or room-level phone presence, assigned under **Person Device Ownership**.
    5. In automations, add a `for:` delay to triggers so short flips are ignored. See [Automations](automations.md).

??? question "A person always shows as `away`"

    `away` comes only from device trackers assigned to the person under **Configure → Person Device Ownership**. A person is `away` when **none** of their assigned `device_tracker.*` entities say `home`.

    **Likely causes**

    - A tracker is in another zone (`work`, `school`, …), which counts as not home.
    - An old or unused tracker (an old phone, a router tracker that reports `not_home` when the phone sleeps) is assigned and wins.
    - The wrong person's tracker is assigned.

    **What to check**

    1. `raw_response` reads `Device tracker indicates not home`, and `indicators` lists the trackers (`device_tracker: device_tracker.alice_phone`).
    2. Look up each of those trackers in **Developer Tools → States**. Any that should say `home` but don't need fixing at the source (for example, Companion app location permissions).
    3. Remove trackers you don't trust from the person's devices. If at least one tracker says `home`, she's treated as home.

    **The opposite problem, never `away`:** assign a device tracker to the person. Without one, Roomer can't tell they've left.

??? question "A phone or watch that reports a room isn't being used"

    A person whose device is used shows `source: device_room` on their room sensor, and `indicators` reads `device: alice_phone_area in office`. If you see `source: llm` instead, work through these.

    **What to check**

    1. In **Developer Tools → States**, look at the device's entity. Its state should be a room or area name, such as `Office`. If it says `unknown` or `unavailable`, the problem is in your Bluetooth tool, not Roomer.
    2. The entity is assigned to the person (or pet) under **Configure → Person Device Ownership**. Mapping it under Room Entity Mapping is not enough.
    3. The name matches one of your Roomer rooms. Capitals, spaces and dashes don't matter, but `Master Bedroom` does not match a room called `bedroom`. In **Settings → System → Logs**, search for `doesn't match any Roomer room`. The warning names the entity, the value it reported and your rooms.
    4. It isn't a GPS tracker. A phone's GPS `device_tracker` reports zones, which are never read as rooms.

    **The person stays in their last room after leaving:** some tools keep reporting the last room until a timeout. Set one (for example `away_timeout` on an `mqtt_room` sensor), or assign a home/away `device_tracker` too, since `away` wins when it changed after the room did.

??? question "Ollama is unreachable or slow (timeouts)"

    **What you'll see**

    - Everyone's confidence drops, most of all for people with no active sensors (to around 0.15 to 0.3, when the fallback guess is the only evidence).
    - People land in the living room (or your first room), in the room of an active PC, or in the room of a playing media player. `indicators` may contain entries like `PC active (fallback)`.
    - `raw_response` contains an error such as `Cannot connect to host …`, or is empty for a timeout.
    - The logs show `Ollama request failed for …` and `Fallback guess for …`.

    **If it's unreachable**

    1. From another machine, open `http://<ollama-host>:11434/api/tags` in a browser. You should get a JSON list of models.
    2. **Don't use `localhost`** unless Ollama really runs inside the same container as Home Assistant. On Home Assistant OS or in Docker, `localhost` is Home Assistant itself. Use the Ollama machine's IP address, such as `http://192.168.1.50:11434`.
    3. Make sure Ollama listens on the network, not just locally: set `OLLAMA_HOST` on the Ollama machine and restart it. Prefer the machine's LAN address (for example `OLLAMA_HOST=192.168.1.50`) over `0.0.0.0`, which listens on every interface. Ollama has no authentication, so limit port 11434 to Home Assistant with a firewall and never expose it to the Internet.
    4. Make sure the model you picked is pulled: `ollama list` on the Ollama machine. A missing model also shows up as a request error.
    5. The server URL can only be set during setup. To change it, delete the Roomer integration and add it again.

    **If it's slow**

    Each update asks the AI once per person and per pet, one after another. Each request may take up to the **LLM Request Timeout** (default **30 seconds**, adjustable from 5 to 120), and a failed request is retried once after a 2-second pause. With three people and a struggling server, one update can take minutes.

    1. Check the timing in the debug logs (`Finished fetching roomer data in … seconds`).
    2. Raise the timeout if the model is slow but working: **Configure → General Settings → LLM Request Timeout**. Roomer reloads itself when you save.
    3. Raise the **Poll Interval** (default 10 seconds) so updates don't pile up, for example to 30–60 seconds.
    4. Use a smaller, faster model (the default is `llama3.2`), or run Ollama on a machine with a GPU.
    5. The first request after Ollama has unloaded a model is much slower because the model has to load. Keeping it loaded (Ollama's `OLLAMA_KEEP_ALIVE` setting) helps.

??? question "The wrong person is placed in a room"

    **Likely causes**

    - Most sensors are anonymous. Motion in the office counts as evidence for *everyone* who is home, so Roomer can't tell Alice from Bob using motion alone. See [Accuracy & limits](accuracy.md).
    - A personal device is mapped to a room but not assigned to its owner (or is assigned to the wrong person).
    - A personal device is assigned to its owner but not mapped to a room. The ownership boost needs both.

    **What to check**

    1. Compare both people's `indicators`. If they're identical, Roomer has nothing that tells them apart.
    2. Under **Configure → Person Device Ownership**, check each person's devices: their PC, their phone's room presence sensor, and so on.
    3. Make sure those same devices are mapped to the right room under **Room Entity Mapping**.
    4. Add more per-person signals. This is the single biggest improvement for multi-person homes.

??? question "My settings changes don't seem to take effect"

    Roomer reloads itself when you save a **Configure** page, and each page keeps what the other pages saved. If a change still doesn't show up:

    1. Reopen the page and check that it shows the value you saved.
    2. Check the logs for errors from `custom_components.roomer` during the reload.
    3. Rooms, people, pets and the server URL can only be set during setup. To change them, delete the Roomer integration and add it again.

??? question "The dashboard card says \"Custom element doesn't exist: roomer-card\""

    - Check the resource is added as `/local/roomer-card.js` with type **JavaScript module**.
    - Check the file is at `/config/www/roomer-card.js`. If you just created the `www` folder, restart Home Assistant.
    - Clear your browser cache or add `?v=2` to the resource URL.

    See [Dashboard card](dashboard-card.md).

??? question "Calling a Roomer service fails with \"service not found\""

    - Check that the Roomer integration is loaded under **Settings → Devices & services**. Services are registered when Roomer starts.
    - `roomer.request_vision_update` appears in older docs but doesn't exist. Use `roomer.identify_person`.
    - `roomer.get_history` and `roomer.get_patterns` only return data. In a script or automation they need a `response_variable`, or Home Assistant rejects the call.

    See [Services & events](services-events.md) for every service and its fields.

??? question "My `roomer_person_arrived` automation never runs"

    - `roomer_person_arrived` and `roomer_person_left` need the person to be `away` first, which only happens when they have a device tracker assigned under **Configure → Person Device Ownership**. Check that `sensor.<name>_room` actually shows `away` when they're out.
    - Nothing fires at startup. If the person was already home when Home Assistant started, there is no arrival until they leave and come back.
    - Watch **Developer Tools → Events** for `roomer_person_arrived` to see whether it fires and what `entity_name` it carries. If your trigger filters on `event_data`, the name must match exactly, including capitals.

    See [Services & events](services-events.md#arrival-departure-and-room-change-events).

## Still stuck?

Open an issue on [GitHub](https://github.com/owens-ben/roomer/issues) with:

- your Home Assistant version and Roomer version,
- the AI provider and model you use,
- the `indicators`, `raw_response` and `confidence` of the sensor that's wrong,
- a few lines of the debug log around the problem.
