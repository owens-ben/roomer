# Roomer Dashboard

A modern dashboard for seeing who is in which room, as reported by the Roomer integration.

![Dashboard Preview](preview.png)

## Features

- 🏠 The house, lit from within: every room is a tile, occupied rooms glow, and each person is a coloured avatar in the room they're in
- 🧠 A sentence first: "Alice is in the office. Max is probably in the living room. Bob is away."
- 👥 Multi-person and pet tracking, each with their own colour
- 📊 Confidence in words (Sure, Likely, Guessing), with the percentage and the clues under "Why Roomer thinks so"
- 📺 Ambient mode for a wall tablet: a big clock and the house, nothing to tap
- 🤖 LLM response viewer
- 📜 Activity timeline
- 🌙 Two looks that follow your system setting: Daylight (light) and Lamplight (dark)
- 📱 Fully responsive design

## Installation Options

### Option 1: Docker (Recommended)

```bash
cd roomer/dashboard
docker compose up -d
```

Access at: `http://YOUR_HOST:3380`

### Option 2: Home Assistant Dashboard

Import `roomer-dashboard.yaml` into Home Assistant:

1. Copy `roomer-dashboard.yaml` to your HA config directory
2. Add to `configuration.yaml`:

```yaml
lovelace:
  mode: yaml
  dashboards:
    roomer-presence:
      mode: yaml
      title: Roomer
      icon: mdi:home-account
      show_in_sidebar: true
      filename: roomer-dashboard.yaml
```

3. Restart Home Assistant

### Option 3: Static File Server

Serve the `index.html` file with any web server (nginx, Apache, Python http.server).

```bash
# Quick test with Python
cd roomer/dashboard
python3 -m http.server 3380
```

## Configuration

On first load, enter your Home Assistant details:

1. **Home Assistant URL**: `http://homeassistant.local:8123` (or your HA IP/hostname)
2. **Long-Lived Access Token**: Generate in HA → Profile → Long-Lived Access Tokens

Settings are saved to browser localStorage.

## Requirements

- Roomer integration installed in Home Assistant
- Home Assistant accessible from the browser
- Valid long-lived access token

## Ambient mode

Click **Ambient mode** after signing in, or open `index.html#ambient` on a wall tablet. You get a large clock, a sentence about where everyone is, and the house with its lit rooms, always in the dark Lamplight look. Press **Esc** or **Exit ambient mode** to go back.

## Customization

### Adding Rooms

Edit the `CONFIG.rooms` array in `index.html`:

```javascript
rooms: ['office', 'living_room', 'bedroom', 'kitchen', 'bathroom', 'entry'],
```

These are the tiles shown on the house even when empty. A room Roomer reports that isn't in the list gets its own tile as soon as someone is in it. People who are `away` aren't a tile: they appear on a line under the house.

### Changing Colors

Modify CSS variables in the `:root` section. Daylight is the default and Lamplight is set for dark mode and ambient mode, so change both blocks:

```css
:root {
    --bg: #F5F0E6;        /* Page background */
    --surface: #FFFDF8;   /* Cards */
    --primary: #2F5C8F;   /* Buttons and links */
    --lit-fill: #FBEBC4;  /* An occupied room */
    --p1: #2F5C8F;        /* Person colours: Blue, Ember, Moss, Lilac */
    --p2: #A4521C;
    --p3: #4C6B30;
    --p4: #6A4A9A;
    /* ... etc */
}
```

Each person gets one of the four colours the first time they appear, and the dashboard remembers it in the browser's localStorage.

## Files

| File | Description |
|------|-------------|
| `index.html` | Standalone web dashboard |
| `roomer-dashboard.yaml` | Home Assistant Lovelace dashboard |
| `docker-compose.yml` | Docker deployment |
| `nginx.conf` | Nginx configuration |

## Integration with Homepage

The Docker container includes Homepage labels for automatic discovery:

- **Group**: AI
- **Name**: Roomer Dashboard
- **Port**: 3380

## Troubleshooting

### "Waiting for Roomer data..."

- Ensure the Roomer integration is configured in Home Assistant
- Check that entities like `sensor.{person_name}_room` exist (e.g., `sensor.alice_room`)
- Verify the integration is polling (check HA logs)

### Connection Failed

- Verify Home Assistant URL is correct
- Check the access token is valid
- Ensure CORS is not blocking requests (HA should allow API access)

### No Room Data

- The integration needs to be configured with persons/pets and rooms
- Go to Settings → Devices & Services → Roomer → Configure

## License

MIT License - Part of the [Roomer](https://github.com/owens-ben/Roomer) project.



