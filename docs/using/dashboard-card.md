# Dashboard card

Roomer comes with a small Lovelace card, `custom:roomer-card`, titled "Who's where". It lights up the rooms that are occupied, shows each person's room and how sure Roomer is, and opens to the clues behind a guess when you tap their row. There is also a ready-made full dashboard if you want more.

!!! example "Screenshot needed: card-example.png"
    The Roomer card on a dashboard with two people: one in `office` ("Sure" with three dots, and the office tile lit above) and one `away` ("Out since 6:12 PM", a hollow green ring and no confidence).

## Install the card

The card is a single JavaScript file, `www/roomer-card.js` in the Roomer repository. Installing the integration through HACS does **not** install the card, and the integration doesn't serve it itself, so you add it by hand. It only takes a minute.

### 1. Copy the file into `/config/www`

Home Assistant serves anything in your `/config/www/` folder at the URL `/local/`.

1. Download [`roomer-card.js`](https://github.com/owens-ben/roomer/blob/main/www/roomer-card.js) (on GitHub, use the **Download raw file** button).
2. Using the File editor or Studio Code Server add-on, Samba, or SSH, put it at:

    ```text
    /config/www/roomer-card.js
    ```

3. If the `www` folder didn't exist before, **restart Home Assistant** once so it starts serving `/local/`.

### 2. Add it as a dashboard resource

1. Go to **Settings → Dashboards**.
2. Open the **⋮** menu (top right) and choose **Resources**. If you don't see it, turn on **Advanced mode** in your user profile first.
3. Click **Add resource** and enter:
    - **URL:** `/local/roomer-card.js`
    - **Resource type:** JavaScript module
4. Click **Create**, then reload your browser (on the mobile app, pull down to refresh or clear the frontend cache).

If you manage dashboards in YAML, add the resource like this instead:

```yaml
# configuration.yaml
lovelace:
  resources:
    - url: /local/roomer-card.js
      type: module
```

!!! tip "Updating the card"
    Browsers cache this file aggressively. After copying in a new version, change the resource URL to `/local/roomer-card.js?v=2` (and bump the number each time) so every device picks up the change.

To check it loaded, open your browser's developer console. You should see an amber and dark **Roomer Card v0.3.0** banner.

## Add the card to a dashboard

1. Open a dashboard and click the pencil (**Edit dashboard**).
2. Click **Add card**, search for **Roomer Presence Card**, and pick it.
3. Switch to the **code editor** and paste the configuration below, changing the entity IDs to yours.

The visual editor lets you set the title, pick any number of room sensors, choose the theme and turn confidence and indicators on or off. Per-person overrides (`person:` and `name:`, below) are only available in the code editor, and the visual editor keeps them when you change other settings.

```yaml
type: custom:roomer-card
title: Who's where
entities:
  - sensor.alice_room
  - sensor.bob_room
  - sensor.fido_room
show_confidence: true
show_indicators: true
theme: auto
```

Each entry can also be an object, if the person entity doesn't follow the sensor's name or you want a different display name:

```yaml
entities:
  - sensor.alice_room
  - entity: sensor.fido_room
    person: person.fido_the_dog
    name: Fido
```

### Options

| Option | Required | Default | Description |
|---|---|---|---|
| `type` | yes | | Must be `custom:roomer-card` |
| `entities` | yes | | A list of Roomer room sensors (`sensor.<name>_room`). Each entry is a plain entity ID, or an object with `entity` (required), `person` (a `person.` entity to take the picture and name from) and `name` (display name). The card shows an error if this is missing. |
| `title` | no | `Who's where` | The card header |
| `show_confidence` | no | `true` | Shows how sure Roomer is on each row: **Sure** (80% and up, three dots), **Likely** (50% and up, two dots) or **Guessing** (below that, one dot). The percentage appears when you tap the row. Hidden for people who are out. |
| `show_indicators` | no | `true` | Lists the clues behind each guess (up to five) when you tap the row, plus what made the call (a room-tracking device, a device tracker or the language model) |
| `theme` | no | `auto` | `auto` follows Home Assistant's light or dark mode; `light` (Daylight) or `dark` (Lamplight) forces one |

Those are all the options; the card's colours, fonts and layout are fixed.

### What the card shows

- **Header** shows the title and how many people are home and out, for example "3 home · 1 out" (anyone in `away`, `not_home`, `unknown` or `unavailable` is not counted as home).
- **Room strip** shows one small tile per room, taken from Roomer's `sensor.<room>_occupants` sensors. A tile is lit when someone is there and Roomer is at least "Likely". It is a dashed ghost when Roomer is only guessing. The coloured dots are the people in it. If you have no room sensors, the strip shows just the rooms your listed people are in.
- **Colour** goes with each person: Blue, Ember, Moss, then Lilac, by their position in `entities`. Their name is always shown next to it.
- **Name** comes from `name:` if you set it, otherwise the matching person entity's name, otherwise the sensor's friendly name without "Room".
- **Picture**: the card looks for `person.<name>` (for `sensor.alice_room` that is `person.alice`, or the `person:` you set). If that person has a picture, it is shown in a ring in their colour; otherwise the card shows their initials on a coloured circle. In dark mode a "Sure" avatar gets a sharp glow and a "Likely" one a wider, softer halo; a "Guessing" avatar is drawn as a dashed ring.
- **Room** is the sensor's state with underscores turned into spaces, for example "Living room".
- **Confidence** is a word and three dots on the right of each row ("Sure", "Likely", "Guessing").
- **Out**: people who are `away` or `not_home` show a hollow green ring, "Out" and when they left ("since 6:12 PM"), with no confidence. `unknown` and `unavailable` show "Unknown".
- **Tap a row** to see why: the confidence as a percentage, the clues Roomer used and what decided the room. Rows with nothing to show aren't tappable.
- **Footer** says when the most recently updated sensor last changed, for example "Updated 12s ago".
- An entity that doesn't exist shows as `Entity not found: <entity_id>`.

!!! note "Confidence is usually lower than you expect"
    Roomer's `confidence` values often sit between 30% and 60% even when the room is right, so "Guessing" or "Likely" is normal. [Accuracy & limits](accuracy.md) explains why.

## The full Roomer dashboard (YAML)

For a whole dashboard with people, pets, per-room views, confidence and the AI's raw replies, the repository includes [`dashboard/roomer-dashboard.yaml`](https://github.com/owens-ben/roomer/blob/main/dashboard/roomer-dashboard.yaml).

It needs two frontend add-ons from HACS:

- [Mushroom](https://github.com/piitaya/lovelace-mushroom) cards (`custom:mushroom-template-card`, `custom:mushroom-chips-card`)
- [card-mod](https://github.com/thomasloven/lovelace-card-mod) (used for the header styling)

The file uses example names (`alice`, `bob`) and rooms (`office`, `living_room`, `bedroom`, `kitchen`). Do a find-and-replace for your own names and rooms before you use it.

### Option A: paste into a UI dashboard

1. **Settings → Dashboards → Add dashboard → New dashboard from scratch**, give it a name, and open it.
2. Click the pencil, then **⋮ → Raw configuration editor**.
3. Paste the contents of `roomer-dashboard.yaml` and save.

The room tiles link to `/roomer-presence/<view>`. Set the new dashboard's URL to `roomer-presence` when you create it, or edit each `navigation_path` to match your URL.

### Option B: YAML-mode dashboard

1. Copy `roomer-dashboard.yaml` into your `/config` folder.
2. Add this to `configuration.yaml`:

    ```yaml
    lovelace:
      dashboards:
        roomer-presence:
          mode: yaml
          title: Roomer
          icon: mdi:home-account
          show_in_sidebar: true
          filename: roomer-dashboard.yaml
    ```

3. Restart Home Assistant. A **Roomer** entry appears in the sidebar, at `/roomer-presence`.

The dashboard key must stay `roomer-presence`: the room tiles link to views such as `/roomer-presence/office`.

!!! example "Screenshot needed: roomer-dashboard-overview.png"
    The "Presence Overview" view of the YAML dashboard, showing the People section, the Room Status tiles and the Detection Confidence section.

There is also a standalone web dashboard that runs in Docker, outside Home Assistant. See [`dashboard/README.md`](https://github.com/owens-ben/roomer/blob/main/dashboard/README.md) on GitHub.
