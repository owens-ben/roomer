# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Device-based room presence.** A phone, watch or tag entity assigned to a person or pet that reports a room (Bermuda area sensors, ESPresense, room-assistant, or an `area`/`room` attribute) now places them in that room directly, without asking the LLM. Room names are matched ignoring case, spaces and dashes; an unmatched room is logged once as a warning.
- `sensor.{room}_occupants` for each room: the number of people in it, with `people`, `pets`, `confidence` and `sources` attributes.
- `source` attribute on `sensor.{name}_room` (`device_room`, `device_tracker` or `llm`).
- **Ambient mode** in the standalone dashboard, for a wall tablet: a big clock, a sentence about where everyone is, and the house. Open it with the new **Ambient mode** button or `index.html#ambient`; Esc exits.
- The standalone dashboard opens with a sentence ("Alice is in the office. Max is probably in the living room.") and a **Why Roomer thinks so** panel on each person with the percentage and the clues.
- The dashboard card shows a strip of room tiles from the per-room occupants sensors, and opens a person's clues when you tap their row.

### Changed
- **New look across the card and the standalone dashboard**: two lights, Daylight (light) and Lamplight (dark), with Bricolage Grotesque, Geist and Geist Mono. Occupied rooms are lit, and each person has a colour (Blue, Ember, Moss or Lilac) that goes with their name.
- Confidence is now said in three plain words with dots: **Sure** (80% and up), **Likely** (50% and up) and **Guessing**. "Pretty sure" is now "Likely", and the percentage moved one tap down.
- A person who is away shows as "Out since 6:12 PM" on the card, and as a line under the house on the dashboard.
- `show_indicators` on the card now lists the clues (up to five) when you tap a row, instead of a one-line summary under the room.
- The dashboard no longer uses emoji for rooms and people.

### Fixed
- A device tracker whose state is a room name is no longer treated as "not home".

## [0.3.0] - 2026-10-21

The redesign release: a new look across the dashboard card, the standalone dashboard, the docs site and the README.

### Added
- New logo: a house of four rooms, with the occupied rooms lit and a person in each. Includes an SVG favicon.
- Docs site theme with light and dark modes, Bricolage Grotesque headings and DM Sans text.
- README banner that follows the reader's light or dark GitHub theme.
- Dashboard card `theme` option (`auto`, `light` or `dark`). `auto` follows Home Assistant's dark mode.

### Changed
- New colour palette: a warm oat base with Denim as the main colour, olive-sage and marigold accents, and a neutral charcoal dark mode.
- Dashboard card redesigned: a row per person with their room, the strongest clues, and a confidence chip in words and numbers ("Sure · 91%"). Avatars use the person's Home Assistant picture, or initials when there is none. People who are away are shown with a dashed outline.
- Standalone dashboard restyled to match.

## [0.2.0] - 2026-10-21

### Added
- Documentation site (MkDocs Material, deployed to GitHub Pages).
- Services `roomer.refresh`, `roomer.correct_room`, `roomer.get_history`, `roomer.clear_history` and `roomer.get_patterns` are now registered.
- `roomer_room_changed`, `roomer_person_arrived` and `roomer_person_left` events now fire.
- Test suite with pytest and a CI workflow for Python 3.11–3.13.
- `pyproject.toml` and Ruff linting configuration.

### Changed
- The project is now called Roomer (domain `roomer`).
- Docs lead with the problem (who is in which room, from combined weak signals) rather than the LLM. An LLM provider is still required.
- Removed emojis from indicator strings in provider code.

### Fixed
- Learned habits and history are saved when Home Assistant stops, instead of being lost on restart.
- `services.py` imported functions that no longer existed, so the module failed to load.
- Home Assistant 2025.x compatibility: use direct import for `async_track_time_interval` instead of deprecated `hass.helpers.event` access.

## [0.1.0-alpha] - 2025-01-29

### Added
- Initial release
- LLM-based presence detection using Ollama
- Multi-person and pet tracking
- Configurable room-entity mappings via UI
- Person-device ownership mappings (e.g., assign a PC to a person)
- Confidence combining from multiple signal sources:
  - LLM reasoning
  - Sensor indicators (motion, media, computers, cameras)
  - Learned habit patterns
- Fallback chain when LLM is unavailable
- Habit learning system that learns patterns over time (no hardcoded defaults)
- Vision identification service using Ollama vision models
- Event logging for ML training data collection
- Storage cleanup service with configurable retention
- CrewAI provider support (experimental)

### Providers
- **Ollama**: Primary provider, runs locally
- **CrewAI**: Experimental support for Claude-based reasoning

### Entities Created
- `sensor.{name}_room` - Current room for each person/pet
- `binary_sensor.{name}_in_{room}` - Per-room presence binary sensors
- `sensor.vision_last_identification` - Last vision identification result

### Services
- `roomer.identify_person` - Trigger vision identification from a camera
- `roomer.enable_tracking` / `roomer.disable_tracking` - Camera tracking control
- `roomer.cleanup_storage` - Manual storage cleanup

[Unreleased]: https://github.com/owens-ben/roomer/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/owens-ben/roomer/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/owens-ben/roomer/compare/v0.1.0...v0.2.0
[0.1.0-alpha]: https://github.com/owens-ben/roomer/releases/tag/v0.1.0
