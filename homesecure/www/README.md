# HomeSecure Badge Card

A badge-style card for controlling your HomeSecure alarm system in Home Assistant.

![Version](https://img.shields.io/badge/version-2.1.0-blue)

## Installation

The add-on copies the card files to `/config/www/` automatically on startup. Register them as Lovelace resources:

1. Go to **Settings** → **Dashboards** → **Resources**
2. Click **Add Resource**
3. Add `/local/homesecure-card.js` — type: **JavaScript Module**
4. Add `/local/homesecure-admin.js` — type: **JavaScript Module**
5. Reload your browser

## Basic Configuration

```yaml
type: custom:homesecure-card
entity: alarm_control_panel.homesecure
```

## Full Configuration Options

### Required

| Parameter | Type | Description |
|-----------|------|-------------|
| `entity` | string | Alarm control panel entity ID |

### Optional

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `api_url` | string | `http://localhost:8099` | Container API URL |
| `api_token` | string | _(none)_ | API bearer token (if configured in add-on) |
| `card_height` | string | `100%` | CSS height value |
| `entry_points` | list | `[]` | Entry points to display (see below) |

> **Note on `api_url`:** In most setups the default works. If your HA instance and the HomeSecure add-on are on different hosts, set this to the container's actual address.

### Entry Points Configuration

| Property | Required | Description |
|----------|----------|-------------|
| `name` | Yes | Display label (e.g. "Front Door") |
| `entity_id` | Yes | HA entity ID of the lock or sensor |
| `type` | Yes | `door`, `window`, `garage`, or `motion` |
| `garage_type` | No | `toggle` (default) or `button` for single-button garage doors |
| `battery_entity` | No | Battery sensor entity to show battery level |

## Example

```yaml
type: custom:homesecure-card
entity: alarm_control_panel.homesecure
api_url: http://localhost:8099
card_height: 600px
entry_points:
  - name: Front Door
    entity_id: lock.front_door
    type: door
    battery_entity: sensor.front_door_battery
  - name: Back Door
    entity_id: lock.back_door
    type: door
  - name: Garage Door
    entity_id: cover.garage_door
    type: garage
    garage_type: toggle
    battery_entity: sensor.garage_battery
  - name: Side Window
    entity_id: binary_sensor.side_window
    type: window
```

## Behavior

### Alarm State

| State | Color | Description |
|-------|-------|-------------|
| Disarmed | Green | System ready |
| Armed Home | Blue | Perimeter zones active |
| Armed Away | Red | All zones active |
| Arming | Yellow | Exit delay in progress |
| Pending | Orange | Entry delay — disarm now |
| Triggered | Red | Alarm sounding |

### Arming

Tap the badge → arm buttons appear → tap **Arm Home** or **Arm Away**.

The arm command goes directly to the HomeSecure container API (`POST /api/arm_home` or `POST /api/arm_away`). The HA alarm entity updates via the WebSocket subscription in the integration.

### Disarming

Tap the badge → keypad appears → enter your PIN (6–8 digits) → tap ✓.

The disarm command posts your PIN to `POST /api/disarm` on the container. If the PIN is wrong, the container rejects it and the alarm stays armed.

### Entry Points

- **Green border** — secure (locked / closed)
- **Red border** — unsecure (unlocked / open)
- Shows last changed time and battery level (if configured)
- Clicking toggles the entity via HA services (lock/unlock for locks, open/close for covers)

### Admin Panel

The ⊕ button in the top-right corner opens the admin panel card. See [ADMIN_README.md](ADMIN_README.md) for full details.

## Visual Editor

The card includes a built-in visual editor accessible from the Lovelace card picker UI. You can configure all options including entry points without writing YAML.

## Layout & Animations

### Landscape (desktop/tablet)
- Badge with entry points shown side-by-side
- Controls slide in from the right

### Portrait (mobile)
- Stacked layout: badge → controls → entry points
- Controls slide in from below

## Styling

The card respects your HA theme variables:
- `--card-background-color`
- `--primary-text-color`
- `--secondary-text-color`
- `--disabled-text-color`
- `--divider-color`

## Troubleshooting

**Card not showing:** Verify resources are registered in Settings → Dashboards → Resources. Clear browser cache (Ctrl+Shift+R).

**Arm/disarm not working:** Check the add-on is running. Open browser dev tools and look for fetch errors to `localhost:8099`. Verify `api_url` and `api_token` in card config match the add-on settings.

**Entry points not updating:** Verify entity IDs in Developer Tools → States. Entry points read from HA state so they update in real time.

**Admin panel won't open:** Make sure `homesecure-admin.js` is also added as a Lovelace resource.

## Browser Compatibility

Chrome/Edge, Firefox, Safari, iOS Safari, Chrome Mobile — all fully supported.

## License

Part of the HomeSecure System for Home Assistant. MIT License.
