<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/owens-ben/roomer/main/docs/assets/banner-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/owens-ben/roomer/main/docs/assets/banner-light.svg">
    <img src="https://raw.githubusercontent.com/owens-ben/roomer/main/docs/assets/banner-light.svg" alt="Roomer — know who's in which room" width="100%">
  </picture>
</h1>

<p align="center">
  <a href="https://github.com/hacs/integration"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg" alt="HACS Custom"></a>
  <a href="https://github.com/owens-ben/roomer/releases"><img src="https://img.shields.io/github/v/release/owens-ben/roomer?include_prereleases" alt="GitHub release"></a>
  <a href="https://owens-ben.github.io/roomer/"><img src="https://img.shields.io/badge/docs-owens--ben.github.io%2Froomer-3E5C82.svg" alt="Docs"></a>
  <a href="https://www.home-assistant.io/"><img src="https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue.svg" alt="Home Assistant 2024.1+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License"></a>
</p>

**Your home already knows a room is occupied. Roomer tells it *who*.**

Roomer is a Home Assistant integration that gives every person (and pet) in your household a sensor that says which room they're in. It doesn't need new hardware. It combines the clues you already have: phones, PCs, TVs, motion, lights, doors. Each guess comes with a confidence level and the reasons behind it.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/owens-ben/roomer/main/docs/assets/screenshots/card-dark.png">
    <img src="https://raw.githubusercontent.com/owens-ben/roomer/main/docs/assets/screenshots/card-light.png" alt="The Roomer dashboard card: Alice in the office (Sure), Max in the living room (Likely), Bob out since 6:12 PM; the occupied rooms are lit" width="420">
  </picture>
</p>

> **Alpha.** It works, but expect rough edges. Read [Is it right for your home?](#is-it-right-for-your-home) before you install.

---

## Why "who" matters

Occupancy sensors made rooms smart. They didn't make them *personal*. "Someone is in the office" can't:

- put on **Alice's** focus lighting, rather than whatever the last person liked
- send "you've been at your desk for three hours" to the person who's actually at the desk
- play an announcement only on the speaker in the room **Bob** is in
- start the bedtime routine when the kids, not the dog, are in their room
- tell you the dog is in the kitchen and nobody else is home

With Roomer, each of these becomes an ordinary automation trigger.

## What you get

For each person and pet you set up:

| Entity | Example | Use it for |
|---|---|---|
| `sensor.<name>_room` | `sensor.alice_room` → `office` | Dashboards, templates, "where is everyone?" |
| `binary_sensor.<name>_in_<room>` | `binary_sensor.alice_in_office` → `on` | The simplest automation trigger there is |
| Attributes | `confidence`, `indicators` (the clues it used) | Acting only when Roomer is fairly sure, and seeing *why* it guessed |

You also get:
- **Events:** `roomer_room_changed`, `roomer_person_arrived`, `roomer_person_left`
- **Services** to refresh, correct a wrong guess, or read movement history
- **Starter blueprints**
- **The dashboard card** shown above

```yaml
# Alice's focus lighting, only when Roomer is fairly sure it's her
triggers:
  - trigger: state
    entity_id: binary_sensor.alice_in_office
    to: "on"
conditions:
  - condition: numeric_state
    entity_id: binary_sensor.alice_in_office
    attribute: confidence
    above: 0.5
actions:
  - action: scene.turn_on
    target:
      entity_id: scene.office_alice_focus
```

## How it decides

No single sensor answers "who". Together they usually can, the same way you'd guess yourself:

```
Motion in the office            → someone is there
+ Alice's PC is on              → probably Alice
+ Alice's phone is home         → she's in the house
+ Bob's phone is away           → it isn't Bob
─────────────────────────────────────────────────
sensor.alice_room = office      with a confidence and the clues it used
```

On every update (every 10 seconds by default), for each person, Roomer:

1. **Checks presence first.** If a person's phone says they're away, they're `away`. That's quick and reliable.
2. **Gathers the clues** from the sensors you mapped to each room, and from the devices you tied to that person.
3. **Weighs them** with a language model running on your own network ([Ollama](https://ollama.com) by default), then blends the answer with the raw sensor evidence and with **habits it has learned** about your household.
4. **Falls back to simple rules** if the model is offline, so the sensors keep updating instead of going blank.

Everything stays on your network. There's no cloud service and no account.

### How it fits with what you already run

Roomer is a **layer on top** of your existing presence tools, not a replacement:

| You already have… | It tells you… | Roomer adds… |
|---|---|---|
| Phone GPS / Wi-Fi trackers | home or away | which *room*, once they're home |
| Motion, mmWave, occupancy sensors | a room is occupied | *who* is occupying it |
| A personal PC, TV or media player | a device is in use | who is using it, and where |
| BLE room tracking (Bermuda, ESPresense) | which area a *device* is in | one answer per person that also uses all your other signals |

## Is it right for your home?

**Roomer works well if** most people in your home have at least one signal that's *theirs*: a phone, a personal computer, a TV they always use, or room-level BLE tracking.

**It can't do magic.** Know these before you install:

- **Anonymous sensors alone can't tell people apart.** If two people are home and the only clue is motion in the kitchen, Roomer will guess, and it will tell you it's guessing.
- **It needs a language model server.** Setup expects Ollama (or a CrewAI endpoint). A small model like `llama3.2` runs on an ordinary desktop. If the server goes down later, Roomer keeps working with simpler rules.
- **Confidence scores currently run low.** They're rough estimates, not probabilities, and recalibrating them is on the roadmap. For now, treat 0.5 as "fairly sure".
- **BLE area sensors need a small template.** Bermuda and ESPresense report a room *name*, which Roomer doesn't read yet. Wrap them in a template binary sensor per room ([how](https://owens-ben.github.io/roomer/getting-started/requirements/#how-good-are-your-signals)).

[Accuracy & limits](https://owens-ben.github.io/roomer/using/accuracy/) goes into more detail.

## Quick start

1. **Run a model.** Install [Ollama](https://ollama.com) on any machine on your network, then run `ollama pull llama3.2`.
2. **Install Roomer.** In HACS, open **⋮ → Custom repositories** and add `https://github.com/owens-ben/roomer` with category *Integration*. Download **Roomer**, then restart Home Assistant.
3. **Set it up.** Go to **Settings → Devices & services → Add integration → Roomer**.
   - Name your rooms and people.
   - Map a few sensors to each room.
   - Tie each person's devices to them.

The first guesses appear on the next update. The docs have the full walkthrough: [Install](https://owens-ben.github.io/roomer/getting-started/install/) · [First setup](https://owens-ben.github.io/roomer/getting-started/first-setup/) · [Map your rooms](https://owens-ben.github.io/roomer/getting-started/map-rooms/).

## Documentation

**[owens-ben.github.io/roomer](https://owens-ben.github.io/roomer/)**:
- [How it works](https://owens-ben.github.io/roomer/getting-started/how-it-works/)
- [Entities](https://owens-ben.github.io/roomer/using/entities/)
- [Automations & blueprints](https://owens-ben.github.io/roomer/using/automations/)
- [Dashboard card](https://owens-ben.github.io/roomer/using/dashboard-card/)
- [Troubleshooting](https://owens-ben.github.io/roomer/using/troubleshooting/)

## Contributing

Issues and pull requests are welcome, especially reports from real homes. When Roomer guesses wrong, its `indicators` attribute shows the clues it used. Include it in your issue.

Start with the [architecture overview](https://owens-ben.github.io/roomer/contributing/architecture/) and [dev setup](https://owens-ben.github.io/roomer/contributing/dev-setup/). Changes are listed in the [changelog](CHANGELOG.md).

## Acknowledgments

- [Ollama](https://ollama.com), for making local language models practical
- [Area Occupancy Detection](https://github.com/Hankanman/Area-Occupancy-Detection), for inspiration on room-level presence

## License

MIT. See [LICENSE](LICENSE).
