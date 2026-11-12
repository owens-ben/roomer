# Accuracy & limits

Roomer makes an educated guess from the sensors you already have. With the right sensors it can be very good; with the wrong ones, no amount of AI can rescue it. This page explains, honestly, what it can and can't tell apart, what the `confidence` number really means, and how to improve your results.

## The key idea: "someone" versus "who"

Most smart-home sensors tell you that **someone** is in a room, not **who**:

| Signal | Tells you *someone* is there | Tells you *who* |
|---|---|---|
| Motion / occupancy sensor | ✅ | ❌ |
| Light on | ✅ (weakly) | ❌ |
| TV or speaker playing | ✅ | ❌ |
| Door or window opened | ✅ (weakly) | ❌ |
| Camera "person detected" sensor | ✅ (strongly) | ❌ |
| Phone's device tracker (home / not home) | ❌ which room | ✅ whether that person is home |
| A person's own PC or laptop being on | ✅ | ✅ |
| A per-room presence sensor for a person's phone or watch (e.g. Bluetooth room presence) | ✅ | ✅ |

**Anonymous signals count the same for everyone.** If Alice and Bob are both home and the only thing happening is motion in the kitchen, Roomer has no way to know which of them is there. Both get the same evidence, so both will usually be placed in the kitchen.

**Per-person signals are what make Roomer work.** The more things you can tie to one specific person, such as their own PC or a room-level tracker for their phone, the better Roomer separates people.

### What Roomer is good at

- **One person home:** every signal belongs to that person, so motion, lights and media are all useful.
- **"Is Alice home at all?"** If her phone's device tracker says she's out, her room becomes `away` with a fixed confidence of 0.95, and the AI is skipped for her.
- **"Alice is at her desk":** her PC being on is a strong, personal signal.
- **"Alice is in the kitchen and Bob is in the office":** a phone, watch or tag that reports its room, assigned to each person, places each of them separately, whoever else is home.
- **"Someone is watching TV in the living room":** for the household as a whole.

### What it can't do (yet)

- **Tell two people apart from anonymous sensors alone.** Two people at home with only motion sensors will usually show up in the same room.
- **Split a household between rooms without per-person devices.** If Alice is in the office and Bob in the kitchen, and the only evidence is motion in both rooms, Roomer doesn't know who is where. Each person goes to whichever room has the stronger evidence overall.
- **Track pets reliably.** Pets get all the anonymous signals (minus PCs) and no home/away check. A Bluetooth tag on the collar, assigned to the pet, fixes that.
- **Use camera identification for rooms.** The [`roomer.identify_person`](services-events.md) service can recognise a person from a snapshot, but in the current version that result isn't used to set anyone's room. Camera "person detected" binary sensors **are** used, but they are anonymous, like motion.
- **React instantly.** Roomer re-evaluates on a timer (every 10 seconds by default), and the AI call itself takes time.

## What `confidence` means

Every room sensor has a `confidence` attribute between 0.0 and 1.0. Treat it as a **strength-of-evidence score**: higher means more and stronger signals agree on that room. It is **not** a calibrated probability. A confidence of 0.5 does not mean "right half the time", and a value of 0.4 is often correct.

### How it's calculated

After the AI model makes its guess, a step called the **confidence combiner** gives every room a score:

1. **Each active sensor mapped to a room adds its weight to that room.** The default weights are:

    | Signal type | Default weight |
    |---|---|
    | `camera` (AI person/animal detection) | 0.95 |
    | `computer` (PC/workstation on) | 0.85 |
    | `media` (playing) | 0.80 (0.56 when paused) |
    | `presence` (device tracker in the room list) | 0.70 |
    | `motion` | 0.60 |
    | `appliance` | 0.50 |
    | `door` | 0.40 |
    | `light` | 0.35 |
    | `climate` | 0.20 |

    A sensor counts as "active" when its state is `on`, `home`, `detected`, `playing`, `open` or `occupied`. A media player counts when it is `playing`, `paused` or `on`.

2. **A person's own devices count again, for that person only.** If a device listed under a person's devices (**Configure → Person Device Ownership**) is active, *and* it is also mapped to a room, that room gets an extra boost at the `computer` weight (0.85) for that person. This is how Roomer tells people apart.

3. **The AI's pick adds** its confidence × `llm_reasoning` weight (0.50). The model is asked only for a room name, so its "confidence" is usually a default of 0.7, or 0.6 if it answered loosely. In practice the AI adds about 0.30 to 0.35 to the room it chose.

4. **Learned habits add** the habit's confidence × `habit` weight (0.35) to the room the person is usually in at this time of day, once a habit has been learned.

5. **The room with the highest total wins.** Its total is divided by the sum of the three largest weights (0.95 + 0.85 + 0.80 = 2.60 by default) and capped at 1.0. That is the `confidence` you see.

Because of that last step, you only get a high confidence when several strong signals stack up on the same room:

| Situation (person's room) | Score | Confidence |
|---|---|---|
| AI guess only, no active sensors | 0.35 | **0.13** |
| Motion + AI agree | 0.60 + 0.35 = 0.95 | **0.37** |
| TV playing + AI agree | 0.80 + 0.35 = 1.15 | **0.44** |
| Motion + light + AI agree | 0.60 + 0.35 + 0.35 = 1.30 | **0.50** |
| Their own PC on (mapped as `computer` and owned) + AI agree | 0.85 + 0.85 + 0.35 = 2.05 | **0.79** |
| Device tracker says not home | (AI skipped) | **0.95**, state `away` |

So a correct answer usually sits between 0.3 and 0.6. Keep that in mind before adding `confidence > 0.8` conditions to automations.

!!! note "When the AI server is down"
    If Roomer can't reach the AI model, it falls back to simple rules: an active PC means its room, otherwise a playing media player means its room, otherwise the living room (or your first room). That guess is weak (0.3 to 0.55 before combining), so confidence drops sharply. A sudden fall in confidence across everyone usually means the AI server is unreachable. See [Troubleshooting](troubleshooting.md).

!!! info "For the curious"
    - The combiner is meant to add a +0.1 bonus when several strong signals agree. As written, that bonus effectively never applies in the current version.
    - Habits are learned only from decisions with confidence of 0.7 or more, in two-hour time-of-day slots. In the current version they are kept in memory and start over when Home Assistant restarts.
    - The code is in `custom_components/roomer/habits.py` (`ConfidenceCombiner`). See [Architecture](../contributing/architecture.md).

You can change the weights under **Settings → Devices & services → Roomer → Configure → Confidence Weights**. Each is a percentage, so 85% means 0.85. Roomer reloads itself when you save, so the change takes effect straight away.

## Tips to improve accuracy

**1. Give each person something personal.**
This matters most. Ideas, roughly from best to good:

- **Their own PC or laptop.** Map its power or activity entity to the right room, *and* assign it to the person under **Person Device Ownership**. The ownership boost only applies when the device is also mapped to a room. Because it's mapped to a room, the PC also counts as ordinary evidence for everyone else. The owner simply gets it twice, so Bob can still drift toward Alice's office if nothing else points elsewhere for him. Giving Bob his own personal signal fixes that.
- **Room-level phone tracking.** Bluetooth room-presence tools (for example Bermuda, ESPresense or room-assistant) report which room a phone, watch or tag is in. Assign that entity to its owner under **Person Device Ownership**, and Roomer puts them in the reported room directly, at 0.9 confidence, without asking the AI. The entity doesn't need to be mapped to a room. This is the best thing you can do in a home with more than one person. Details, including what happens when a person's devices disagree, are in [Map your rooms](../getting-started/map-rooms.md#devices-that-report-a-room).

- **A phone device tracker** (the Companion app) for home/away. Assign it under Person Device Ownership so `away` works.

**2. Map sensors to the right rooms, and only the useful ones.**
Each mapped sensor pushes its room for everyone. A hallway motion sensor mapped to the living room, or a light that's always on, quietly drags people to the wrong place. See [Map your rooms](../getting-started/map-rooms.md).

**3. Check the signal type Roomer guessed.**
When you map an entity, Roomer guesses its type from words in the entity ID:

| If the entity ID contains… | It's treated as |
|---|---|
| `motion`, `occupancy` | motion |
| `media_player`, `tv` | media |
| `light.` | light |
| `pc`, `computer`, `desktop` | computer |
| `camera`, `person`, `animal` | camera |
| `door`, `window`, `contact` | door |
| `temperature`, `humidity` | climate |
| `device_tracker` | presence |
| anything else | appliance |

The first match wins, from top to bottom. A smart plug called `switch.desk_plug` counts as an *appliance* (0.50), while `switch.alice_pc` counts as a *computer* (0.85). Renaming an entity ID (and mapping it again) changes how much it counts. Watch out for accidental matches: anything with `person` in its ID is treated as a high-weight camera, and `tv` matches inside words too.

**4. Tune the weights for your home.**
If lights are left on all day in your house, lower the `light` weight. If your motion sensors are very reliable, raise `motion`.

**5. Use the binary sensors with a delay in automations.**
Add a `for:` of 20 to 60 seconds so brief flips don't trigger anything. See [Automations](automations.md).

**6. Pick a capable, fast model.**
A model that answers in a second or two keeps results fresh. If responses take longer than your poll interval, raise the poll interval. See [Troubleshooting](troubleshooting.md).

## When nothing is active

If no mapped entity is active for a person, Roomer does not pretend to know.

- **Still where they were last seen.** If a clue (a sensor, or a device that reports a room, or your
  `roomer.correct_room`) put them in a room in the last three hours, they stay there
  (`source: sticky`). The confidence starts at 50% to 70% and halves every hour. Below 15% it is dropped.
- **Otherwise a prior.** With no recent clue the room is only the AI's and your learned habits' time-of-day guess
  (`source: prior`). Its `indicators` are `["No active clues; time-of-day guess"]` and its confidence never
  goes above 0.25. Don't automate on it.

An active clue always beats both, and a person who goes `away` is forgotten, so they never come back by "sticking".
