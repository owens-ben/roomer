/**
 * Roomer Presence Card for Lovelace
 *
 * Shows who is in which room, how sure Roomer is, and why. Two looks:
 * "Daylight" (light) and "Lamplight" (dark).
 *
 *  - A header with the count of people home and out.
 *  - A strip of room tiles. A tile lights up when someone is there with at
 *    least 50% confidence, shows a dashed ghost when Roomer is only guessing,
 *    and stays quiet when the room is empty. Rooms are found automatically
 *    from Roomer's per-room "<room> Occupants" sensors.
 *  - One row per person: their room and how sure Roomer is ("Sure",
 *    "Likely" or "Guessing"). Tap a row to see the percentage and the clues
 *    behind the guess. People who are away show "Out since 6:12 PM".
 *
 * Installation:
 * 1. Copy this file to /config/www/roomer-card.js
 * 2. Add to Lovelace resources:
 *    url: /local/roomer-card.js
 *    type: module
 *
 * Usage:
 * type: custom:roomer-card
 * title: Who's where          # optional
 * theme: auto                 # optional: auto | light | dark
 * entities:
 *   - sensor.ben_room
 *   - entity: sensor.alex_room
 *     person: person.alex     # optional, for the avatar picture
 *     name: Alex              # optional display name
 * show_confidence: true       # "Sure/Likely/Guessing" and the percentage
 * show_indicators: true       # the clues behind each guess
 *
 * Fonts (Bricolage Grotesque, Geist, Geist Mono) load from Google Fonts and
 * fall back to the system font if they can't be reached.
 */

const ROOMER_CARD_VERSION = '0.3.0';
const DEFAULT_TITLE = "Who's where";
const AWAY_STATES = ['away', 'not_home', 'unknown', 'unavailable', ''];
const OUT_STATES = ['away', 'not_home'];
const PERSON_COLOURS = 4; // Blue, Ember, Moss, Lilac, assigned by position in `entities`
const OCCUPANTS_ID = /^sensor\..+_occupants$/;
const MAX_CLUES = 5;
const SOURCE_LABELS = {
  device_room: 'a room-tracking device',
  device_tracker: 'a device tracker',
  llm: 'the language model',
};
const FONT_LINK_ID = 'roomer-card-fonts';
const FONT_HREF =
  'https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700' +
  '&family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500&display=swap';

function ensureFonts() {
  try {
    if (document.getElementById(FONT_LINK_ID)) return;
    if (document.querySelector(`link[href="${FONT_HREF}"]`)) return;
    const link = document.createElement('link');
    link.id = FONT_LINK_ID;
    link.rel = 'stylesheet';
    link.href = FONT_HREF;
    document.head.appendChild(link);
  } catch (e) {
    /* fonts are a nicety; fall back silently */
  }
}

function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Normalise an `entities` entry (string or object) to {entity, person, name}. */
function normaliseEntry(entry) {
  if (typeof entry === 'string') return { entity: entry };
  if (entry && typeof entry === 'object' && typeof entry.entity === 'string') return { ...entry };
  return null;
}

function slugFor(entityId) {
  const objectId = String(entityId).split('.').slice(1).join('.') || String(entityId);
  return objectId.replace(/_room$/, '');
}

function prettyRoom(room) {
  const s = String(room).replace(/_/g, ' ').trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : 'Unknown';
}

/** "Living Room" -> "living_room", the form Roomer's sensors use as their state. */
function roomSlug(value) {
  return String(value ?? '').trim().toLowerCase().replace(/\s+/g, '_');
}

function initials(name) {
  const parts = String(name).trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return '?';
  const letters = parts.length === 1 ? parts[0].slice(0, 1) : parts[0][0] + parts[1][0];
  return letters.toUpperCase();
}

function ago(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

/** Confidence in words, and how many of the three dots are filled. */
function confidenceLevel(conf) {
  if (conf >= 0.8) return { key: 'sure', word: 'Sure', dots: 3 };
  if (conf >= 0.5) return { key: 'likely', word: 'Likely', dots: 2 };
  return { key: 'guess', word: 'Guessing', dots: 1 };
}

function dotsHtml(filled) {
  return [0, 1, 2].map((i) => `<i class="d${i < filled ? '' : ' off'}"></i>`).join('');
}

/** Local time the person left ("6:12 PM"), from the sensor's last_changed. */
function sinceLabel(state) {
  const ts = Date.parse(state.last_changed || state.last_updated || '');
  if (Number.isNaN(ts)) return '';
  return new Date(ts).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

/**
 * Roomer's per-room occupants sensors: `sensor.*_occupants` with `people` and
 * `pets` list attributes. Returns [{id, label, slug}] sorted by name.
 */
function discoverRooms(states) {
  const rooms = [];
  for (const id of Object.keys(states)) {
    if (!OCCUPANTS_ID.test(id)) continue;
    const attrs = (states[id] && states[id].attributes) || {};
    if (!Array.isArray(attrs.people) || !Array.isArray(attrs.pets)) continue;
    const label = String(attrs.friendly_name || '').replace(/\s+occupants$/i, '').trim()
      || prettyRoom(id.slice('sensor.'.length).replace(/_occupants$/, ''));
    const slug = roomSlug(label);
    rooms.push({ id, label: prettyRoom(slug), slug });
  }
  return rooms.sort((a, b) => a.label.localeCompare(b.label));
}

/** One clue: "motion: living_room_motion" -> label "Motion" + mono value. */
function clueHtml(clue) {
  const text = String(clue);
  const m = /^([a-z_ ]+):\s*(.+)$/i.exec(text);
  if (!m) return `<li class="clue"><span class="clue-label">${esc(text)}</span></li>`;
  return `<li class="clue"><span class="clue-label">${esc(prettyRoom(m[1]))}</span>`
    + `<span class="clue-val">${esc(m[2])}</span></li>`;
}

const STYLES = `
  :host { display: block; }
  [hidden] { display: none !important; }
  ha-card.rc {
    /* Daylight */
    --rc-bg: #FFFDF8; --rc-line: #E4DACA; --rc-hair: #EFE7D9;
    --rc-ink: #1C1915; --rc-body: #4A4236; --rc-muted: #6E6556;
    --rc-pill-bg: #EFE7D9; --rc-pill-ink: #4A4236;
    --rc-tile-empty-bg: #F5F0E6; --rc-tile-empty-line: #E4DACA; --rc-tile-empty-ink: #6E6556;
    --rc-tile-lit-bg: #FBEBC4; --rc-tile-lit-line: #EBC977; --rc-tile-lit-ink: #1C1915;
    --rc-tile-ghost-bg: #F8F1E1; --rc-tile-ghost-line: #E2C98E; --rc-tile-ghost-ink: #1C1915;
    --rc-lamp-lit: none; --rc-lamp-ghost: none;
    --rc-dot: #1C1915; --rc-dot-off: #8C8273;
    --rc-away: #4C6B30; --rc-focus: #2F5C8F; --rc-on-person: #FFFFFF;
    --rc-p0: #2F5C8F; --rc-p1: #A4521C; --rc-p2: #4C6B30; --rc-p3: #6A4A9A;
    --rc-p0-rgb: 47,92,143; --rc-p1-rgb: 164,82,28; --rc-p2-rgb: 76,107,48; --rc-p3-rgb: 106,74,154;
    --rc-font-body: 'Geist', var(--paper-font-body1_-_font-family, system-ui), sans-serif;
    --rc-font-display: 'Bricolage Grotesque', 'Geist', var(--paper-font-body1_-_font-family, system-ui), sans-serif;
    --rc-font-mono: 'Geist Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    --ha-card-box-shadow: none;
    --ha-card-background: var(--rc-bg);
    --ha-card-border-radius: 22px;
    --ha-card-border-width: 1px;
    --ha-card-border-color: var(--rc-line);
    display: flex;
    flex-direction: column;
    gap: 18px;
    box-sizing: border-box;
    background: var(--rc-bg);
    border: 1px solid var(--rc-line);
    border-radius: 22px;
    box-shadow: none;
    padding: 22px;
    color: var(--rc-ink);
    font-family: var(--rc-font-body);
    font-size: 14px;
    line-height: 1.4;
  }
  /* Lamplight */
  ha-card.rc.dark {
    --rc-bg: #161412; --rc-line: #2F2B26; --rc-hair: #2A2723;
    --rc-ink: #F4EFE6; --rc-body: #CFC7BA; --rc-muted: #A69E91;
    --rc-pill-bg: #24211D; --rc-pill-ink: #CFC7BA;
    --rc-tile-empty-bg: #1A1815; --rc-tile-empty-line: #2F2B26; --rc-tile-empty-ink: #A69E91;
    --rc-tile-lit-bg: #1A1815; --rc-tile-lit-line: rgba(245,185,74,0.5); --rc-tile-lit-ink: #F4EFE6;
    --rc-tile-ghost-bg: #1A1815; --rc-tile-ghost-line: rgba(245,185,74,0.3); --rc-tile-ghost-ink: #CFC7BA;
    --rc-lamp-lit: radial-gradient(circle at 50% 60%, rgba(245,185,74,0.35), rgba(245,185,74,0.06) 80%);
    --rc-lamp-ghost: radial-gradient(circle at 50% 60%, rgba(245,185,74,0.12), rgba(245,185,74,0.02) 80%);
    --rc-dot: #F4EFE6; --rc-dot-off: #7C7468;
    --rc-away: #A9CF86; --rc-focus: #F5B94A; --rc-on-person: #11100E;
    --rc-p0: #8DB4F0; --rc-p1: #F4A26C; --rc-p2: #A9CF86; --rc-p3: #CDB0F2;
    --rc-p0-rgb: 141,180,240; --rc-p1-rgb: 244,162,108; --rc-p2-rgb: 169,207,134; --rc-p3-rgb: 205,176,242;
  }
  .p0 { --pc: var(--rc-p0); --pc-rgb: var(--rc-p0-rgb); }
  .p1 { --pc: var(--rc-p1); --pc-rgb: var(--rc-p1-rgb); }
  .p2 { --pc: var(--rc-p2); --pc-rgb: var(--rc-p2-rgb); }
  .p3 { --pc: var(--rc-p3); --pc-rgb: var(--rc-p3-rgb); }

  .head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .title {
    margin: 0; min-width: 0; font-family: var(--rc-font-display); font-weight: 700; font-size: 24px;
    line-height: 28px; letter-spacing: -0.025em; color: var(--rc-ink);
  }
  .count {
    flex: none; font-size: 13px; line-height: 17px; padding: 5px 10px; border-radius: 999px;
    background: var(--rc-pill-bg); color: var(--rc-pill-ink); white-space: nowrap;
  }

  /* Room strip */
  .rooms { display: grid; grid-template-columns: repeat(auto-fit, minmax(64px, 1fr)); gap: 6px; }
  .tile {
    position: relative; box-sizing: border-box; height: 58px; min-width: 0; padding: 8px;
    border-radius: 12px; border: 1px solid var(--rc-tile-empty-line);
    background-color: var(--rc-tile-empty-bg);
    display: flex; flex-direction: column; justify-content: space-between; overflow: hidden;
    transition: background-color 600ms ease-out, border-color 600ms ease-out;
  }
  .tile::before, .tile::after {
    content: ''; position: absolute; inset: 0; z-index: 0; pointer-events: none; opacity: 0;
    transition: opacity 600ms ease-out;
  }
  .tile::before { background: var(--rc-lamp-lit); }
  .tile::after { background: var(--rc-lamp-ghost); }
  .tile.lit { background-color: var(--rc-tile-lit-bg); border-color: var(--rc-tile-lit-line); }
  .tile.lit::before { opacity: 1; }
  .tile.ghost {
    background-color: var(--rc-tile-ghost-bg); border-color: var(--rc-tile-ghost-line); border-style: dashed;
  }
  .tile.ghost::after { opacity: 1; }
  .tile-label {
    position: relative; z-index: 1; font-size: 11px; line-height: 1.3; color: var(--rc-tile-empty-ink);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .tile.lit .tile-label { color: var(--rc-tile-lit-ink); }
  .tile.ghost .tile-label { color: var(--rc-tile-ghost-ink); }
  .tile-people { position: relative; z-index: 1; display: flex; flex-wrap: wrap; gap: 3px; }
  .pd { flex: none; box-sizing: border-box; width: 10px; height: 10px; border-radius: 50%; background: var(--pc); }
  .pd.ghost {
    background: transparent; border: 1.5px dashed var(--pc);
    animation: rc-breathe 3s ease-in-out infinite;
  }
  @keyframes rc-breathe { 0%, 100% { opacity: 1; } 50% { opacity: 0.6; } }

  /* People */
  .rows { display: flex; flex-direction: column; }
  .person { border-top: 1px solid var(--rc-hair); }
  .row {
    display: flex; align-items: center; gap: 12px; box-sizing: border-box; width: 100%; min-width: 0;
    min-height: 44px; padding: 10px 0;
  }
  button.row {
    appearance: none; -webkit-appearance: none; margin: 0; border: 0; background: none;
    border-radius: 10px; font: inherit; color: inherit; text-align: left; cursor: pointer;
    -webkit-tap-highlight-color: transparent;
  }
  button.row:focus-visible { outline: 2px solid var(--rc-focus); outline-offset: 2px; }
  .avatar {
    flex: none; box-sizing: border-box; width: 36px; height: 36px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-weight: 600; font-size: 14px; line-height: 1;
    background: var(--pc); color: var(--rc-on-person);
  }
  .avatar.guess { background: transparent; color: var(--pc); border: 2px dashed var(--pc); }
  .avatar.away { background: transparent; color: var(--rc-away); border: 2px solid var(--rc-away); }
  .avatar.unknown { background: transparent; color: var(--rc-muted); border: 2px solid var(--rc-muted); }
  .avatar.pic { background: var(--rc-bg); border: 2px solid var(--pc); }
  .avatar.pic.guess { border-style: dashed; }
  .avatar.pic.away { border-color: var(--rc-away); }
  .avatar.pic.unknown { border-color: var(--rc-muted); }
  .avatar img { display: block; width: 100%; height: 100%; object-fit: cover; border-radius: 50%; }
  ha-card.rc.dark .avatar.sure { box-shadow: 0 0 16px rgba(var(--pc-rgb), 0.5); }
  ha-card.rc.dark .avatar.likely {
    box-shadow: 0 0 0 5px rgba(var(--pc-rgb), 0.14), 0 0 22px rgba(var(--pc-rgb), 0.4);
  }
  .who { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .name {
    font-size: 13px; line-height: 17px; color: var(--rc-muted);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .room {
    font-size: 18px; font-weight: 600; line-height: 23px; color: var(--rc-ink);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .row.out .room, .row.unknown .room { color: var(--rc-body); }
  .conf { flex: none; display: flex; align-items: center; gap: 8px; font-size: 13px; line-height: 17px; color: var(--rc-body); }
  .dots { display: flex; gap: 3px; }
  .d { box-sizing: border-box; width: 6px; height: 6px; border-radius: 50%; background: var(--rc-dot); }
  .d.off { background: transparent; border: 1.5px solid var(--rc-dot-off); }
  .since { flex: none; font-size: 13px; line-height: 17px; color: var(--rc-muted); }
  .missing { font-size: 13px; color: var(--rc-muted); }

  /* Detail panel */
  .detail { display: flex; flex-direction: column; gap: 8px; padding: 4px 0 12px 48px; }
  .verdict { margin: 0; font-family: var(--rc-font-mono); font-size: 12px; color: var(--rc-body); }
  .clues { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
  .clue { display: flex; flex-wrap: wrap; align-items: baseline; gap: 2px 8px; font-size: 13px; color: var(--rc-body); }
  .clue-val { font-family: var(--rc-font-mono); font-size: 11px; color: var(--rc-muted); overflow-wrap: anywhere; }
  .source { margin: 0; font-size: 12px; color: var(--rc-muted); }

  /* Footer */
  .foot-row {
    display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 12px;
    font-size: 12px; line-height: 16px; color: var(--rc-muted);
  }
  .hint { margin-left: auto; }

  @media (prefers-reduced-motion: reduce) {
    .tile, .tile::before, .tile::after { transition: none; }
    .pd.ghost { animation: none; }
  }
`;

class RoomerCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._sig = null;
    this._lastUpdated = null;
    this._open = new Set(); // entity ids whose detail panel is open
    this._el = null;
    this.shadowRoot.addEventListener('click', (ev) => {
      const button = ev.target && ev.target.closest ? ev.target.closest('button[data-entity]') : null;
      if (button) this._toggle(button.dataset.entity);
    });
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  get hass() {
    return this._hass;
  }

  setConfig(config) {
    if (!config || !Array.isArray(config.entities) || !config.entities.length) {
      throw new Error('Please define entities');
    }
    const entries = config.entities.map(normaliseEntry);
    if (entries.some((e) => !e)) {
      throw new Error('Each entry in entities must be an entity ID or an object with an `entity` key');
    }
    const theme = config.theme || 'auto';
    if (!['auto', 'light', 'dark'].includes(theme)) {
      throw new Error('theme must be one of: auto, light, dark');
    }
    this._config = config;
    this._entries = entries;
    this._theme = theme;
    this._sig = null;
    ensureFonts();
    this._render();
  }

  connectedCallback() {
    this._timer = setInterval(() => this._updateFooter(), 15000);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
  }

  _isDark() {
    if (this._theme === 'dark') return true;
    if (this._theme === 'light') return false;
    const themes = this._hass && this._hass.themes;
    if (themes && typeof themes.darkMode === 'boolean') return themes.darkMode;
    return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
  }

  _updateFooter() {
    const foot = this.shadowRoot && this.shadowRoot.querySelector('.foot');
    if (foot && this._lastUpdated) foot.textContent = `Updated ${ago(Date.now() - this._lastUpdated)}`;
  }

  _toggle(entityId) {
    if (this._open.has(entityId)) this._open.delete(entityId);
    else this._open.add(entityId);
    this._render();
  }

  /** Static scaffold, built once so the room tiles persist and can fade between states. */
  _buildSkeleton() {
    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <ha-card class="rc">
        <div class="head"></div>
        <div class="rooms" role="list" aria-label="Rooms" hidden></div>
        <div class="rows"></div>
        <div class="foot-row" hidden></div>
      </ha-card>`;
    const $ = (selector) => this.shadowRoot.querySelector(selector);
    this._el = { card: $('ha-card'), head: $('.head'), rooms: $('.rooms'), rows: $('.rows'), foot: $('.foot-row') };
  }

  /** Update the tile elements in place (keyed by room) so colour changes transition. */
  _patchRooms(tiles) {
    const container = this._el.rooms;
    container.hidden = !tiles.length;
    const existing = new Map();
    Array.from(container.children).forEach((el) => existing.set(el.dataset.room, el));
    let prev = null;
    tiles.forEach((tile) => {
      let el = existing.get(tile.slug);
      existing.delete(tile.slug);
      if (!el) {
        el = document.createElement('div');
        el.dataset.room = tile.slug;
        el.setAttribute('role', 'listitem');
      }
      const className = `tile ${tile.state}`;
      if (el.className !== className) el.className = className;
      if (el._rcHtml !== tile.html) {
        el.innerHTML = tile.html;
        el._rcHtml = tile.html;
      }
      if (el.title !== tile.text) el.title = tile.text;
      if (el.getAttribute('aria-label') !== tile.text) el.setAttribute('aria-label', tile.text);
      const ref = prev ? prev.nextSibling : container.firstChild;
      if (el !== ref) container.insertBefore(el, ref);
      prev = el;
    });
    existing.forEach((el) => el.remove());
  }

  _render() {
    if (!this._hass || !this._config) return;
    const states = this._hass.states || {};
    const cfg = this._config;
    const showConfidence = cfg.show_confidence !== false;
    const showIndicators = cfg.show_indicators !== false;
    const dark = this._isDark();
    const discovered = discoverRooms(states);

    // Skip re-rendering when nothing this card shows has changed.
    const sig = JSON.stringify([
      dark,
      Array.from(this._open).sort(),
      discovered.map((r) => [r.id, r.label]),
      this._entries.map((e) => {
        const s = states[e.entity];
        const personId = e.person || `person.${slugFor(e.entity)}`;
        const p = states[personId];
        return [
          s ? s.state : null,
          s ? s.last_updated : null,
          s ? s.last_changed : null,
          s ? s.attributes : null,
          p ? p.attributes.entity_picture : null,
          p ? p.attributes.friendly_name : null,
        ];
      }),
    ]);
    if (sig === this._sig) {
      this._updateFooter();
      return;
    }
    this._sig = sig;

    let homeCount = 0;
    let outCount = 0;
    let latest = null;
    let anyExpandable = false;
    const occupancy = new Map(); // room slug -> [{colour, name, conf}]

    const rows = this._entries.map((entry, index) => {
      const state = states[entry.entity];
      if (!state) {
        return `<div class="person"><div class="row"><div class="missing">Entity not found: ${esc(entry.entity)}</div></div></div>`;
      }
      const attrs = state.attributes || {};
      const personId = entry.person || `person.${slugFor(entry.entity)}`;
      const person = states[personId];
      const pAttrs = (person && person.attributes) || {};
      const colour = index % PERSON_COLOURS;

      const fallbackName = String(attrs.friendly_name || slugFor(entry.entity).replace(/_/g, ' '))
        .replace(/\s+room$/i, '');
      const name = entry.name || pAttrs.friendly_name || fallbackName;

      const raw = String(state.state ?? '').toLowerCase();
      const out = OUT_STATES.includes(raw);
      const unknown = !out && AWAY_STATES.includes(raw);
      const home = !out && !unknown;
      const conf = Math.min(1, Math.max(0, Number(attrs.confidence) || 0));
      const level = confidenceLevel(conf);
      if (home) homeCount += 1;
      if (out) outCount += 1;
      const roomLabel = out ? 'Out' : unknown ? 'Unknown' : prettyRoom(state.state);

      if (home) {
        const slug = roomSlug(state.state);
        if (!occupancy.has(slug)) occupancy.set(slug, []);
        occupancy.get(slug).push({ colour, name, conf });
      }

      const ts = Date.parse(state.last_updated || state.last_changed || '');
      if (!Number.isNaN(ts) && (latest === null || ts > latest)) latest = ts;

      // Avatar
      const stateClass = out ? 'away' : unknown ? 'unknown' : level.key;
      const pic = pAttrs.entity_picture;
      const avatar = pic
        ? `<span class="avatar p${colour} ${stateClass} pic" aria-hidden="true"><img src="${esc(pic)}" alt=""></span>`
        : `<span class="avatar p${colour} ${stateClass}" aria-hidden="true">${esc(initials(name))}</span>`;

      // Right-hand side
      let right = '';
      if (home && showConfidence) {
        right = `<span class="conf"><span>${level.word}</span><span class="dots" aria-hidden="true">${dotsHtml(level.dots)}</span></span>`;
      } else if (out) {
        const since = sinceLabel(state);
        if (since) right = `<span class="since">since ${esc(since)}</span>`;
      }

      // Detail panel: what Roomer thinks and why
      const verdict = showConfidence && home ? `Roomer is ${level.word.toLowerCase()} · ${Math.round(conf * 100)}%` : '';
      const clues = showIndicators && Array.isArray(attrs.indicators)
        ? attrs.indicators.map((i) => String(i).trim()).filter(Boolean).slice(0, MAX_CLUES)
        : [];
      const source = showIndicators && attrs.source
        ? SOURCE_LABELS[attrs.source] || String(attrs.source).replace(/_/g, ' ')
        : '';
      const expandable = !!verdict || clues.length > 0 || !!source;
      if (expandable) anyExpandable = true;
      const open = expandable && this._open.has(entry.entity);
      const detailId = `rc-detail-${index}`;
      const detail = open
        ? `<div class="detail" id="${detailId}">`
          + (verdict ? `<p class="verdict">${esc(verdict)}</p>` : '')
          + (clues.length ? `<ul class="clues">${clues.map(clueHtml).join('')}</ul>` : '')
          + (source ? `<p class="source">Decided by ${esc(source)}</p>` : '')
          + '</div>'
        : '';

      const rowClass = `row${out ? ' out' : unknown ? ' unknown' : ''}`;
      const inner = `${avatar}<span class="who"><span class="name">${esc(name)}</span>`
        + `<span class="room">${esc(roomLabel)}</span></span>${right}`;
      const rowHtml = expandable
        ? `<button type="button" class="${rowClass}" data-entity="${esc(entry.entity)}" aria-expanded="${open}"`
          + `${open ? ` aria-controls="${detailId}"` : ''}>${inner}</button>`
        : `<div class="${rowClass}">${inner}</div>`;
      return `<div class="person">${rowHtml}${detail}</div>`;
    });

    // Room tiles: every Roomer room, plus any room someone is in that we haven't discovered.
    const tiles = [];
    const seen = new Set();
    const addTile = (slug, label) => {
      if (!slug || seen.has(slug)) return;
      seen.add(slug);
      const occ = occupancy.get(slug) || [];
      const sure = occ.filter((o) => o.conf >= 0.5);
      const guesses = occ.filter((o) => o.conf < 0.5);
      const dots = sure.map((o) => `<i class="pd p${o.colour}"></i>`).join('')
        + guesses.map((o) => `<i class="pd ghost p${o.colour}"></i>`).join('');
      const who = sure.map((o) => o.name).concat(guesses.map((o) => `${o.name} (guess)`));
      tiles.push({
        slug,
        state: sure.length ? 'lit' : guesses.length ? 'ghost' : 'empty',
        html: `<span class="tile-label">${esc(label)}</span>`
          + (dots ? `<span class="tile-people" aria-hidden="true">${dots}</span>` : ''),
        text: `${label}: ${who.length ? who.join(', ') : 'empty'}`,
      });
    };
    discovered.forEach((r) => addTile(r.slug, r.label));
    occupancy.forEach((_, slug) => addTile(slug, prettyRoom(slug)));

    this._lastUpdated = latest;
    const title = cfg.title || DEFAULT_TITLE;
    const countText = `${homeCount} home${outCount ? ` · ${outCount} out` : ''}`;
    const footParts = [
      latest !== null ? `<span class="foot">Updated ${ago(Date.now() - latest)}</span>` : '',
      anyExpandable ? '<span class="hint">Tap anyone for why</span>' : '',
    ].join('');

    // Rewriting the rows drops focus; put it back on the same person afterwards.
    if (!this._el) this._buildSkeleton();
    const active = this.shadowRoot.activeElement;
    const focusId = active && active.dataset && this._el.rows.contains(active) ? active.dataset.entity : null;

    this._el.card.classList.toggle('dark', dark);
    this._el.head.innerHTML = `<h2 class="title">${esc(title)}</h2><span class="count">${countText}</span>`;
    this._patchRooms(tiles);
    this._el.rows.innerHTML = rows.join('');
    this._el.foot.hidden = !footParts;
    this._el.foot.innerHTML = footParts;

    if (focusId) {
      const again = Array.from(this._el.rows.querySelectorAll('button[data-entity]'))
        .find((b) => b.dataset.entity === focusId);
      if (again) again.focus({ preventScroll: true });
    }
  }

  static getConfigElement() {
    return document.createElement('roomer-card-editor');
  }

  static getStubConfig(hass) {
    let entities = ['sensor.example_room'];
    if (hass && hass.states) {
      const found = Object.keys(hass.states)
        .filter((id) => /^sensor\..+_room$/.test(id) && 'entity_type' in (hass.states[id].attributes || {}))
        .slice(0, 3);
      if (found.length) entities = found;
    }
    return {
      title: DEFAULT_TITLE,
      entities,
      show_confidence: true,
      show_indicators: true,
      theme: 'auto',
    };
  }

  getCardSize() {
    return (this._config?.entities?.length || 1) + 1;
  }
}

// Card editor for the GUI. Uses Home Assistant's <ha-form> with plain DOM
// properties and event listeners (no lit template bindings).
const EDITOR_SCHEMA = [
  { name: 'title', selector: { text: {} } },
  { name: 'entities', selector: { entity: { multiple: true, filter: { domain: 'sensor' } } } },
  {
    name: 'theme',
    selector: {
      select: {
        mode: 'dropdown',
        options: [
          { value: 'auto', label: 'Auto (follow Home Assistant)' },
          { value: 'light', label: 'Light' },
          { value: 'dark', label: 'Dark' },
        ],
      },
    },
  },
  { name: 'show_confidence', selector: { boolean: {} } },
  { name: 'show_indicators', selector: { boolean: {} } },
];

const EDITOR_LABELS = {
  title: 'Title',
  entities: 'Room sensors',
  theme: 'Theme',
  show_confidence: 'Show confidence',
  show_indicators: 'Show indicators',
};

class RoomerCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._update();
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  _formData() {
    const c = this._config || {};
    return {
      title: c.title || '',
      entities: (c.entities || []).map(normaliseEntry).filter(Boolean).map((e) => e.entity),
      theme: c.theme || 'auto',
      show_confidence: c.show_confidence !== false,
      show_indicators: c.show_indicators !== false,
    };
  }

  _update() {
    if (!this._config) return;
    if (!this._form) {
      this._form = document.createElement('ha-form');
      this._form.computeLabel = (s) => EDITOR_LABELS[s.name] || s.name;
      this._form.addEventListener('value-changed', (ev) => this._valueChanged(ev.detail.value));
      this.appendChild(this._form);
    }
    this._form.schema = EDITOR_SCHEMA;
    this._form.data = this._formData();
    if (this._hass) this._form.hass = this._hass;
  }

  _valueChanged(value) {
    if (!value) return;
    // Keep per-entity objects (person/name overrides) for entities still selected.
    const previous = new Map(
      (this._config.entities || []).map(normaliseEntry).filter(Boolean).map((e) => [e.entity, e]),
    );
    const entities = (value.entities || []).map((id) => {
      const prev = previous.get(id);
      return prev && Object.keys(prev).length > 1 ? prev : id;
    });
    const config = { ...this._config, ...value, entities };
    if (!config.title) delete config.title;
    if (config.theme === 'auto') delete config.theme;
    this._config = config;
    this.dispatchEvent(new CustomEvent('config-changed', {
      detail: { config },
      bubbles: true,
      composed: true,
    }));
  }
}

if (!customElements.get('roomer-card')) customElements.define('roomer-card', RoomerCard);
if (!customElements.get('roomer-card-editor')) customElements.define('roomer-card-editor', RoomerCardEditor);

// Register with Lovelace
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === 'roomer-card')) {
  window.customCards.push({
    type: 'roomer-card',
    name: 'Roomer Presence Card',
    description: "Who's where: each person's room, how sure Roomer is, and why",
    preview: true,
  });
}

console.info(`%c Roomer Card %c v${ROOMER_CARD_VERSION} `,
  'background: #F5B94A; color: #11100E; padding: 2px 6px; border-radius: 3px 0 0 3px;',
  'background: #4A4033; color: white; padding: 2px 6px; border-radius: 0 3px 3px 0;'
);
