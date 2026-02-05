# Secure Alarm Badge Card

A beautiful, modern badge-style card for controlling your Secure Alarm System in Home Assistant.

## Features

- **Badge Display**: Large, glowing badge showing current alarm state
- **Smooth Animations**: Badge slides left/up while controls fade in from right/down
- **Responsive Design**: Automatically adapts to landscape and portrait orientations
- **Entry Points**: Optional display of lock/door/window status
- **Admin Access**: Quick access button to admin panel
- **Touch-Optimized**: Large buttons and intuitive keypad for easy interaction

## Installation

1. Copy `secure-alarm-card.js` to `/config/www/secure-alarm-card.js`
2. Add to Lovelace resources:
   - Go to Settings → Dashboards → Resources
   - Click "Add Resource"
   - URL: `/local/secure-alarm-card.js`
   - Resource type: `JavaScript Module`

## Basic Configuration

```yaml
type: custom:secure-alarm-card
entity: alarm_control_panel.secure_alarm
```

## Full Configuration Options

### Required Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `entity` | string | **Required.** Entity ID of your secure alarm control panel (e.g., `alarm_control_panel.secure_alarm`) |

### Optional Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `card_height` | string | `100%` | CSS height value for the card (e.g., `100%`, `600px`, `80vh`) |
| `entry_points` | list | `[]` | List of entry point objects to display (see Entry Points section) |

### Entry Points Configuration

Entry points allow you to display the status of doors, windows, locks, and other sensors directly on the badge card.

#### Entry Point Object Properties

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `name` | string | Yes | Display name for the entry point (e.g., "Front Door") |
| `entity_id` | string | Yes | Entity ID of the lock or sensor (e.g., `lock.front_door`) |
| `type` | string | Yes | Type of entry point: `door`, `window`, `garage`, or `motion` |
| `battery_entity` | string | No | Entity ID of associated battery sensor to display battery level |

#### Entry Point Example

```yaml
type: custom:secure-alarm-card
entity: alarm_control_panel.secure_alarm
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
    battery_entity: sensor.garage_door_battery
  - name: Living Room Window
    entity_id: binary_sensor.living_room_window
    type: window
```

## Complete Example

```yaml
type: custom:secure-alarm-card
entity: alarm_control_panel.secure_alarm
card_height: 600px
entry_points:
  - name: Front Door
    entity_id: lock.front_door
    type: door
    battery_entity: sensor.front_door_battery
  - name: Back Door
    entity_id: lock.back_door
    type: door
    battery_entity: sensor.back_door_battery
  - name: Garage Door
    entity_id: cover.garage_door
    type: garage
    battery_entity: sensor.garage_battery
  - name: Side Window
    entity_id: binary_sensor.side_window
    type: window
  - name: Motion Sensor
    entity_id: binary_sensor.living_room_motion
    type: motion
```

## Visual Editor

This card includes a visual editor accessible from the Home Assistant UI:

1. Add card → Custom: Secure Alarm Badge Card
2. Configure options using the visual interface:
   - Select alarm entity from dropdown
   - Set card height
   - Add/remove entry points
   - Configure each entry point's properties

## Behavior

### Disarmed State
- Click badge → Slides left/up → Arm buttons fade in from right/down
- Choose "Arm Home" or "Arm Away"
- System arms immediately (Arm Home) or after exit delay (Arm Away)

### Armed State
- Click badge → Slides left/up → Keypad fades in from right/down
- Enter PIN (6-8 digits)
- Click checkmark to disarm
- Entry delay gives you time to disarm before triggering

### Entry Points
- Green border: Secure (locked/closed)
- Red border: Unsecure (unlocked/open)
- Shows last changed time
- Shows battery level if configured
- Click to toggle lock/unlock (for locks)

### Admin Button
- Gear icon in top-right corner
- Opens admin panel for user management
- Requires admin PIN authentication
- Re-authentication required each time

## Alarm States

| State | Color | Icon | Description |
|-------|-------|------|-------------|
| Disarmed | Green | Shield | System ready, not monitoring |
| Armed Home | Blue | Home | Perimeter zones active |
| Armed Away | Red | Lock | All zones active |
| Arming | Yellow | Shield Sync | Exit delay in progress |
| Pending | Orange | Shield Alert | Entry delay - disarm now! |
| Triggered | Red | Bell | Alarm is sounding |

## Animations

### Landscape Mode (Desktop/Tablet)
- Badge slides **left** (-30px)
- Controls fade in from **right** (+30px)
- 0.5s duration with smooth easing

### Portrait Mode (Mobile)
- Badge slides **up** (-30px)
- Controls fade in from **below** (+30px)
- 0.5s duration with smooth easing

### Responsive Breakpoint
- Switches at 768px width or portrait orientation
- Automatically adjusts layout and animations

## Styling

The card automatically adapts to your Home Assistant theme:
- `--card-background-color`: Card and badge background
- `--primary-text-color`: Main text color
- `--secondary-text-color`: Subtitle text
- `--disabled-text-color`: Less important text
- `--divider-color`: Borders and separators

## Troubleshooting

### Card Not Showing
- Verify resource is added correctly in Settings → Dashboards → Resources
- Check browser console for errors (F12)
- Clear browser cache (Ctrl+Shift+R or Cmd+Shift+R)

### Visual Editor Not Working
- Ensure you're using the latest version
- Try removing and re-adding the card
- Check that `secure-alarm-card-editor` is defined

### Animations Stuttering
- Check browser performance
- Reduce number of entry points
- Try a simpler card_height value

### Entry Points Not Updating
- Verify entity IDs are correct
- Check entity states in Developer Tools → States
- Ensure entities are available in Home Assistant

## Advanced Customization

### Custom Height for Different Views

**Desktop Dashboard:**
```yaml
type: custom:secure-alarm-card
entity: alarm_control_panel.secure_alarm
card_height: 100%
```

**Mobile Dashboard:**
```yaml
type: custom:secure-alarm-card
entity: alarm_control_panel.secure_alarm
card_height: 80vh
```

**Panel Mode:**
```yaml
type: custom:secure-alarm-card
entity: alarm_control_panel.secure_alarm
card_height: 100vh
```

## Performance Tips

1. **Limit Entry Points**: 3-5 entry points work best
2. **Battery Sensors**: Only add if needed
3. **Card Height**: Use percentage values when possible
4. **Multiple Cards**: Use one card per view for best performance

## Browser Compatibility

- Chrome/Edge: Full support ✓
- Firefox: Full support ✓
- Safari: Full support ✓
- iOS Safari: Full support ✓
- Chrome Mobile: Full support ✓

## Version History

### 1.0.0
- Initial release with badge interface
- Entry point management
- Admin panel integration
- Smooth animations
- Visual editor support

## Support

For issues, feature requests, or contributions:
- GitHub: https://github.com/mmotrock/ha-secure-alarm
- Home Assistant Community: [Link to forum thread]

## License

This card is part of the Secure Alarm System integration for Home Assistant.