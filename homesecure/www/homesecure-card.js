/**
 * HomeSecure Badge Card v2.0
 * Custom Lovelace card for HomeSecure System
 *
 * In v2.0 arm/disarm calls go directly to the container REST API.
 * Entry point lock/cover toggles still use HA services (they are native HA entities).
 *
 * Config options:
 *   entity       - alarm_control_panel entity (for state display only)
 *   api_url      - Container API URL (default: http://localhost:8099)
 *   api_token    - Optional API bearer token
 *   card_height  - CSS height (default: 100%)
 *   entry_points - list of entry point objects
 */

/**
 * Detect the best API base URL for the current environment.
 *
 * Priority:
 *  1. Explicit api_url in card config — always wins
 *  2. HA ingress path from window.location (sidebar panel URL)
 *  3. Same hostname as HA + port 8099 (LAN and remote with port exposed)
 */
function _detectApiUrl(configApiUrl) {
  if (configApiUrl) return configApiUrl.replace(/\/$/, '');

  // Check if we're being served through HA ingress sidebar panel
  const ingressMatch = window.location.pathname.match(
    /(\/api\/hassio_ingress\/[^/]+)/
  );
  if (ingressMatch) {
    return window.location.origin + ingressMatch[1];
  }

  // Use same hostname as HA but on port 8099
  // Works on LAN and any reverse proxy that also exposes port 8099
  return `${window.location.protocol}//${window.location.hostname}:8099`;
}

/**
 * Shared debug logger — respects the homesecure_debug localStorage flag.
 * Enable via Admin Panel → General → Debug Mode, or:
 *   localStorage.setItem('homesecure_debug', '1'); location.reload();
 * Disable:
 *   localStorage.removeItem('homesecure_debug'); location.reload();
 */
const _hs = {
  get debug() { return localStorage.getItem('homesecure_debug') === '1'; },
  log:   function(...a) { if (this.debug) console.log('[HomeSecure]', ...a); },
  warn:  function(...a) { if (this.debug) console.warn('[HomeSecure]', ...a); },
  error: function(...a) { console.error('[HomeSecure]', ...a); },
  info:  function(...a) { if (this.debug) console.info('[HomeSecure]', ...a); },
};


class HomeSecureCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._pin = '';
    this._showInterface = false;
    this._showAdmin = false;
    this._showArmPin = false;
    this._armAction  = null;
    this._serverConfig = {};
    this._configLoaded = false;
    this._apiUrl = _detectApiUrl(null);
    this._apiToken = '';
  }

  static getConfigElement() {
    return document.createElement('homesecure-card-editor');
  }

  static getStubConfig() {
    return {
      entity: 'alarm_control_panel.homesecure',
      entry_points: [],
      card_height: '100%'
    };
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error('Please define an entity');
    }
    this.config = {
      card_height: '100%',
      ...config
    };
    this._apiUrl = _detectApiUrl(config.api_url);
    this._apiToken = config.api_token || '';
    this.render();
  }

  set hass(hass) {
    const oldHass = this._hass;
    this._hass = hass;
    this.entity = hass.states[this.config.entity];

    // Load server config once so we know if PIN is required to arm
    if (!oldHass && this._apiUrl) this._loadServerConfig();

    if (this.entity) {
      if (!this._showAdmin) {
        this.render();
      }
    }
  }

  async _loadServerConfig() {
    if (this._configLoaded) return;
    this._configLoaded = true;
    try {
      const headers = this._apiToken ? { Authorization: `Bearer ${this._apiToken}` } : {};
      const resp = await fetch(this._apiUrl + '/api/config', { headers });
      if (resp.ok) {
        const json = await resp.json();
        this._serverConfig = json.config || json || {};
        _hs.log('Server config loaded:', this._serverConfig);
      }
    } catch (e) {
      _hs.warn('Could not load server config:', e);
    }
  }

  getCardSize() {
    return 4;
  }

  // Add this method for proper editor detection
  static get properties() {
    return {
      hass: {},
      config: {}
    };
  }

  render() {
    if (!this.entity) return;

    try {
      const state = this.entity.state;
      const isArmed = !['disarmed', 'arming'].includes(state);

      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: block;
            height: 100%;
          }
          ha-card {
            padding: 0;
            overflow: hidden;
            height: 100%;
            border: 2px solid var(--divider-color) !important;
            border-radius: 12px !important;
          }
        .card-content {
          padding: 16px;
          overflow: hidden;
          height: 100%;
          width: 100%;
          box-sizing: border-box;
        }
        .landscape-container {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: flex-start;
          min-height: 100%;
          height: 100%;
          padding: 0px;
        }
        .badge-container {
          position: relative;
          /* transition: all 0.5s cubic-bezier(0.4, 0, 0.2, 1); */
          opacity: 1;
          width: 100%;
          max-width: 1200px;
          min-height: 400px;
          display: flex;
          flex-direction: column;
          align-items: center;
        }
        .interface-panel {
          display: flex;
          flex-direction: column;
          justify-content: center;
          align-items: center;
          opacity: 1;
          margin-top: 24px;
          width: 100%;
          max-width: 600px;
          z-index: 10;
          position: relative; 
        }
        @keyframes slideInFromBottom {
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }
        .admin-btn {
          position: absolute;
          top: 16px;
          right: 16px;
          width: 48px;
          height: 48px;
          background: rgba(255, 255, 255, 0.95);
          border: 2px solid #667eea;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          z-index: 10;
          transition: all 0.3s;
          box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
        }
        .admin-btn:hover {
          transform: scale(1.1) rotate(90deg);
          box-shadow: 0 6px 16px rgba(102, 126, 234, 0.5);
          background: #667eea;
        }
        .admin-btn:hover svg {
          color: white;
        }
        .admin-btn svg {
          width: 28px;
          height: 28px;
          color: #667eea;
          transition: all 0.3s;
        }
        .glow-outer {
          position: absolute;
          inset: 0;
          border-radius: 9999px;
          filter: blur(40px);
          opacity: 0.2;
        }
        .badge-main {
          position: relative;
          background: var(--card-background-color, #1e293b);
          border-radius: 24px;
          padding: 32px;
          box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
          cursor: pointer;
          margin: 0 auto;
          width: fit-content;
          z-index: 1;
        }
        .badge-icon-container {
          position: relative;
          margin: 0 auto;
        }
        .badge-icon-glow {
          position: absolute;
          inset: 0;
          border-radius: 9999px;
          filter: blur(20px);
          opacity: 0.3;
        }
        .badge-icon {
          position: relative;
          width: 160px;
          height: 160px;
          margin: 0 auto;
          border-radius: 9999px;
          display: flex;
          align-items: center;
          justify-content: center;
          box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
        }
        .badge-icon svg {
          width: 96px;
          height: 96px;
          color: white;
        }
        .status-text {
          text-align: center;
          margin-top: 24px;
        }
        .status-title {
          font-size: 30px;
          font-weight: bold;
          color: var(--primary-text-color);
          margin-bottom: 8px;
        }
        .status-subtitle {
          font-size: 18px;
          color: var(--secondary-text-color);
        }
        .status-changed-by {
          font-size: 14px;
          color: var(--disabled-text-color);
          margin-top: 8px;
        }
        .tap-indicator {
          margin-top: 24px;
          text-align: center;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          font-size: 14px;
          color: var(--disabled-text-color);
        }
        .pulse-dot {
          width: 8px;
          height: 8px;
          background: var(--disabled-text-color);
          border-radius: 9999px;
          animation: pulse 2s infinite;
        }
        .entry-points {
          position: absolute;
          left: 16px;
          top: 0;
          transform: none;
          width: 220px;
          margin-top: 0;
          opacity: 1;
          transition: opacity 0.3s;
          z-index: 5;
        }
        .entry-points-title {
          font-size: 12px;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          color: var(--disabled-text-color);
          margin-bottom: 12px;
        }
        .entry-point {
          padding: 6px 10px; /* Reduced from 10px 16px */
          font-size: 12px; /* Add this */
          margin-bottom: 6px; /* Reduced from 8px */
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 10px 16px;
          border-radius: 9999px;
          cursor: pointer;
          transition: all 0.3s;
          border: 1px solid;
          width: 200px;
        }
        .entry-point:hover {
          opacity: 0.8;
        }
        .entry-point-left {
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .entry-point-icon {
          width: 12px;
          height: 12px;
        }
        .entry-point-name {
          color: var(--primary-text-color);
          font-size: 12px;
          font-weight: 500;
        }
        .entry-point-time {
          color: var(--disabled-text-color);
          font-size: 12px;
          margin-top: 2px;
        }
        .entry-point-right {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .entry-point-battery {
          display: flex;
          align-items: center;
          gap: 4px;
          font-size: 12px;
        }
        .entry-point-status {
          font-size: 12px;
          font-weight: 500;
        }
        .interface-overlay {
          background: var(--card-background-color, #1e293b);
          border-radius: 24px;
          overflow: hidden;
          box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
        }
        .interface-header {
          padding: 24px;
          color: white;
          position: relative;
        }
        .close-btn {
          position: absolute;
          top: 16px;
          right: 16px;
          background: rgba(255, 255, 255, 0.2);
          border: none;
          border-radius: 8px;
          padding: 8px;
          cursor: pointer;
          color: white;
        }
        .close-btn:hover {
          background: rgba(255, 255, 255, 0.3);
        }
        .interface-body {
          padding: 24px;
        }
        .arm-buttons {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 12px;
          width: 100%;
        }
        .arm-button.cancel-btn {
          grid-column: 1 / -1;
          max-width: 300px;
          margin: 0 auto;
          width: 100%;
        }
        .arm-button {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px;
          border-radius: 12px;
          border: none;
          cursor: pointer;
          transition: all 0.15s;
          font-size: 14px;
          color: white;
        }
        .arm-button:hover {
          transform: scale(1.05);
        }
        .arm-button:active {
          transform: scale(0.95);
        }
        .pin-display {
          background: var(--secondary-background-color, #334155);
          border-radius: 16px;
          padding: 16px;
          margin-bottom: 24px;
          text-align: center;
        }
        .pin-label {
          font-size: 14px;
          color: var(--disabled-text-color);
          margin-bottom: 8px;
        }
        .pin-dots {
          font-size: 30px;
          letter-spacing: 8px;
          color: var(--primary-text-color);
          min-height: 40px;
        }
        .pin-counter {
          font-size: 12px;
          color: var(--disabled-text-color);
          margin-top: 8px;
        }
        .keypad {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 12px;
          margin-bottom: 16px;
        }
        .key {
          background: var(--secondary-background-color, #334155);
          border: none;
          border-radius: 16px;
          padding: 24px;
          font-size: 24px;
          font-weight: 600;
          color: var(--primary-text-color);
          cursor: pointer;
          transition: all 0.15s;
        }
        .key:hover {
          transform: scale(1.05);
          box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }
        .key:active {
          transform: scale(0.95);
        }
        .key.clear {
          background: #dc2626;
          color: white;
        }
        .key.enter {
          background: #16a34a;
          color: white;
        }
        .key.enter:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        .green { background: #10b981; color: white; }
        .blue { background: #3b82f6; color: white; }
        .red { background: #ef4444; color: white; }
        .yellow { background: #eab308; color: white; }
        .orange { background: #f97316; color: white; }
        .green-border { border-color: rgba(16, 185, 129, 0.5); background: rgba(16, 185, 129, 0.2); }
        .red-border { border-color: rgba(239, 68, 68, 0.5); background: rgba(239, 68, 68, 0.2); }
        .green-text { color: #10b981; }
        .red-text { color: #ef4444; }
        @media (max-width: 768px), (orientation: portrait) {
          .badge-container {
            flex-direction: column;
            align-items: center;
          }
          
          .entry-points {
            position: relative;
            left: auto;
            top: auto;
            transform: none;
            width: 100%;
            max-width: 400px;
            margin-top: 24px;
            transition: all 0.3s ease;
            order: 3;  /* Entry points last */
          }
          
          .badge-main {
            margin: 0 auto;
            order: 1;  /* Badge first */
          }
          
          .interface-panel {
            order: 2;  /* Arm buttons between badge and entry points */
            margin-top: 24px;
            margin-bottom: 24px;
          }
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      </style>
      ${this._showAdmin ? this.renderAdmin() : (this._showInterface ? this.renderInterface() : this.renderBadge())}
    `;

      this.attachEventListeners();
    } catch (error) {
      _hs.error('Error rendering badge card:', error);
      // Fallback rendering
      this.shadowRoot.innerHTML = `
        <ha-card>
          <div style="padding: 20px; color: var(--error-color);">
            <h3>Error Loading Card</h3>
            <p>${error.message}</p>
            <button style="padding: 8px 16px; margin-top: 12px;" onclick="location.reload()">Refresh Page</button>
          </div>
        </ha-card>
      `;
    }
  }

  renderBadge() {
    const state = this.entity.state;
    const changedBy = this.entity.attributes.changed_by || '';
    const { color, icon, text, description } = this.getStateInfo(state);
    const entryPoints = this.config.entry_points || [];

    return `
      <ha-card style="height: 100%;">
        <div class="card-content" style="height: 100%; padding-top: ${this.config.container_top_padding || '80px'};">
          <div class="badge-container" style="max-width: ${this.config.container_max_width || '1200px'}; align-self: ${this.config.container_alignment || 'center'};">
            <button class="admin-btn" data-action="open-admin" title="Admin Panel">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M12 4v16m8-8H4"/>
              </svg>
            </button>
            <div class="glow-outer ${color}"></div>
            ${entryPoints.length > 0 ? this.renderEntryPoints(entryPoints) : ''}
            <div class="badge-main">
              <div class="badge-icon-container">
                <div class="badge-icon-glow ${color}"></div>
                <div class="badge-icon ${color}">
                  ${icon}
                </div>
              </div>
              <div class="status-text">
                <div class="status-title">${text}</div>
                <div class="status-subtitle">${description}</div>
                ${changedBy ? `<div class="status-changed-by">by ${changedBy}</div>` : ''}
              </div>
              ${!this._showInterface ? `
                <div class="tap-indicator">
                  <div class="pulse-dot"></div>
                  <span>Tap to ${state === 'disarmed' ? 'arm' : 'disarm'}</span>
                </div>
              ` : ''}
            </div>
          </div>
        </div>
      </ha-card>
    `;
  }

  renderAdmin() {
    // Check if homesecure-admin is defined
    if (!customElements.get('homesecure-admin')) {
      _hs.error('homesecure-admin custom element not found');
      return `
        <ha-card>
          <div style="padding: 20px;">
            <h3>Admin Panel Error</h3>
            <p>The admin panel component is not loaded.</p>
            <p style="font-size: 12px; color: var(--secondary-text-color); margin-top: 12px;">
              Make sure homesecure-admin.js is added to your Lovelace resources.
            </p>
            <button style="padding: 8px 16px; margin-top: 12px; background: var(--primary-color); color: white; border: none; border-radius: 4px; cursor: pointer;" data-action="close-admin-error">Close</button>
          </div>
        </ha-card>
      `;
    }

    // Create admin panel element if it doesn't exist
    if (!this._adminPanel) {
      try {
        this._adminPanel = document.createElement('homesecure-admin');
        this._adminPanel.setConfig({ entity: this.config.entity, api_url: this._apiUrl, api_token: this._apiToken });
        this._adminPanel.hass = this._hass;
        this._adminPanel.addEventListener('close-admin', () => {
          this._showAdmin = false;
          this.render();
        });
      } catch (error) {
        _hs.error('Error creating admin panel:', error);
        // Fallback to showing an error message
        return `
          <ha-card>
            <div style="padding: 20px;">
              <h3>Admin Panel Error</h3>
              <p>Unable to load admin panel. Please refresh the page.</p>
              <p style="font-size: 12px; color: var(--error-color); margin-top: 8px;">${error.message}</p>
              <button style="padding: 8px 16px; margin-top: 12px; background: var(--primary-color); color: white; border: none; border-radius: 4px; cursor: pointer;" data-action="close-admin-error">Close</button>
            </div>
          </ha-card>
        `;
      }
    } else {
      try {
        this._adminPanel.hass = this._hass;
      } catch (error) {
        _hs.error('Error updating admin panel hass:', error);
      }
    }
    
    return `<div id="admin-container"></div>`;
  }

  renderEntryPoints(entryPoints) {
    return `
      <div class="entry-points">
        <div class="entry-points-title">Entry Points</div>
        ${entryPoints.map(point => this.renderEntryPoint(point)).join('')}
      </div>
    `;
  }

  renderEntryPoint(point) {
    const entity = this._hass.states[point.entity_id];
    if (!entity) return '';

    const isSecure = ['locked', 'closed'].includes(entity.state);
    const battery = point.battery_entity ? this._hass.states[point.battery_entity]?.state : null;
    const lastChanged = new Date(entity.last_changed);
    const timeAgo = this.getTimeAgo(lastChanged);

    return `
      <div class="entry-point ${isSecure ? 'green-border' : 'red-border'}" data-action="toggle-entry" data-entity="${point.entity_id}" data-garage-type="${point.garage_type || 'toggle'}">
        <div class="entry-point-left">
          <div class="entry-point-icon ${isSecure ? 'green-text' : 'red-text'}">
            ${this.getEntryPointIcon(point.type, entity.state)}
          </div>
          <div>
            <div class="entry-point-name">${point.name}</div>
            <div class="entry-point-time">${timeAgo}</div>
          </div>
        </div>
        <div class="entry-point-right">
          ${battery ? `<div class="entry-point-battery">${this.getBatteryIcon(battery)} ${battery}%</div>` : ''}
          <div class="entry-point-status ${isSecure ? 'green-text' : 'red-text'}">
            ${entity.state.charAt(0).toUpperCase() + entity.state.slice(1)}
          </div>
        </div>
      </div>
    `;
  }

  renderArmPin() {
    const label   = this._armAction === 'arm_away' ? 'Arm Away' : 'Arm Home';
    const pinDots = '●'.repeat(this._pin.length) || '●●●●●●';
    const nums    = [1,2,3,4,5,6,7,8,9]
      .map(n => `<button class="key" data-action="number" data-value="${n}">${n}</button>`)
      .join('');
    return `
      <div class="pin-display">
        <div class="pin-label">Enter PIN to ${label}</div>
        <div class="pin-dots">${pinDots}</div>
        <div class="pin-counter">${this._pin.length}/8 digits</div>
      </div>
      <div class="keypad">
        ${nums}
        <button class="key clear" data-action="clear">✕</button>
        <button class="key" data-action="number" data-value="0">0</button>
        <button class="key enter" data-action="confirm-arm"
                ${this._pin.length < 6 ? 'disabled' : ''}>✓</button>
      </div>`;
  }

  renderInterface() {
    const state = this.entity.state;
    const isArmed = !['disarmed', 'arming'].includes(state);
    const { color, icon, text, description } = this.getStateInfo(state);
    const entryPoints = this.config.entry_points || [];

    const badgeHtml = `
      <button class="admin-btn" data-action="open-admin" title="Admin Panel">
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M12 4v16m8-8H4"/>
        </svg>
      </button>
      <div class="glow-outer ${color}"></div>
      ${entryPoints.length > 0 ? this.renderEntryPoints(entryPoints) : ''}
      <div class="badge-main">
        <div class="badge-icon-container">
          <div class="badge-icon-glow ${color}"></div>
          <div class="badge-icon ${color}">
            ${icon}
          </div>
        </div>
        <div class="status-text">
          <div class="status-title">${text}</div>
          <div class="status-subtitle">${description}</div>
        </div>
      </div>
    `;

    if (!isArmed) {
      const requirePin = !!this._serverConfig.require_pin_to_arm;
      return `
        <ha-card style="height: 100%;">
          <div class="card-content" style="height: 100%; padding-top: ${this.config.container_top_padding || '80px'};">
            <div class="badge-container" style="max-width: ${this.config.container_max_width || '1200px'}; align-self: ${this.config.container_alignment || 'center'};">
              ${badgeHtml}
              <div class="interface-panel">
                ${this._showArmPin ? this.renderArmPin() : `<div class="arm-buttons">`}
                ${this._showArmPin ? '' : `<button class="arm-button blue" data-action="arm-home">
                    <div style="display: flex; align-items: center; gap: 8px;">
                      <svg width="24" height="24" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"/>
                      </svg>
                      <div style="text-align: left;">
                        <div style="font-size: 16px; font-weight: 600;">Arm Home</div>
                        <div style="font-size: 11px; opacity: 0.8;">Perimeter only${requirePin ? ' · PIN required' : ''}</div>
                      </div>
                    </div>
                  </button>
                  <button class="arm-button red" data-action="arm-away">
                    <div style="display: flex; align-items: center; gap: 8px;">
                      <svg width="24" height="24" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
                      </svg>
                      <div style="text-align: left;">
                        <div style="font-size: 16px; font-weight: 600;">Arm Away</div>
                        <div style="font-size: 11px; opacity: 0.8;">All zones + exit delay${requirePin ? ' · PIN required' : ''}</div>
                      </div>
                    </div>
                  </button>
                  <button class="arm-button cancel-btn" style="background: #6b7280; color: white;" data-action="close">
                    <div style="display: flex; align-items: center; gap: 8px;">
                      <svg width="24" height="24" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                      </svg>
                      <div style="text-align: left;">
                        <div style="font-size: 16px; font-weight: 600;">Cancel</div>
                      </div>
                    </div>
                  </button>
                </div>`}
              </div>
            </div>
          </div>
        </ha-card>
      `;
    } else {
      return `
        <ha-card style="height: 100%;">
          <div class="card-content" style="height: 100%; padding-top: 80px;">
            <div class="landscape-container">
              ${badgeHtml}
              <div class="interface-panel">
                ${this.renderKeypadOnly()}
              </div>
            </div>
          </div>
        </ha-card>
      `;
    }
  }

  renderKeypadOnly() {
    const pinDots = '●'.repeat(this._pin.length) || '●●●●●●';
    return `
      <div class="pin-display">
        <div class="pin-label">Enter PIN to Disarm</div>
        <div class="pin-dots">${pinDots}</div>
        <div class="pin-counter">${this._pin.length}/8 digits</div>
      </div>
      <div class="keypad">
        ${[1,2,3,4,5,6,7,8,9].map(n => `<button class="key" data-action="number" data-value="${n}">${n}</button>`).join('')}
        <button class="key clear" data-action="clear">✕</button>
        <button class="key" data-action="number" data-value="0">0</button>
        <button class="key enter" data-action="disarm" ${this._pin.length < 6 ? 'disabled' : ''}>✓</button>
      </div>
    `;
  }

  updatePinDisplay() {
    // Update only the PIN display without re-rendering entire card
    const pinDotsEl = this.shadowRoot.querySelector('.pin-dots');
    const pinCounterEl = this.shadowRoot.querySelector('.pin-counter');
    // Handle both disarm and confirm-arm enter buttons
    const enterBtn = this.shadowRoot.querySelector('[data-action="disarm"]')
                  || this.shadowRoot.querySelector('[data-action="confirm-arm"]');
    
    if (pinDotsEl) {
      const pinDots = '●'.repeat(this._pin.length) || '●●●●●●';
      pinDotsEl.textContent = pinDots;
    }
    
    if (pinCounterEl) {
      pinCounterEl.textContent = `${this._pin.length}/8 digits`;
    }
    
    if (enterBtn) {
      if (this._pin.length < 6) {
        enterBtn.disabled = true;
      } else {
        enterBtn.disabled = false;
      }
    }
  }

  getStateInfo(state) {
    const states = {
      disarmed: { color: 'green', text: 'Disarmed', description: 'System Ready' },
      armed_home: { color: 'blue', text: 'Armed Home', description: 'Perimeter Secured' },
      armed_away: { color: 'red', text: 'Armed Away', description: 'Fully Armed' },
      arming: { color: 'yellow', text: 'Arming', description: 'Exit Delay' },
      pending: { color: 'orange', text: 'Entry Delay', description: 'Disarm Now' },
      triggered: { color: 'red', text: 'TRIGGERED!', description: 'Alarm Active' },
    };

    const info = states[state] || states.disarmed;
    info.icon = this.getIcon(state);
    return info;
  }

  getIcon(state) {
    const icons = {
      disarmed: '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.618 5.984A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016zM12 9v2m0 4h.01"/></svg>',
      armed_home: '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"/></svg>',
      armed_away: '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/></svg>',
      triggered: '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>',
    };
    return icons[state] || icons.disarmed;
  }

  getEntryPointIcon(type, state) {
    if (type === 'door') {
      return state === 'locked' 
        ? '<svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/></svg>'
        : '<svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 11V7a4 4 0 118 0m-4 8v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2z"/></svg>';
    } else if (type === 'garage') {
      return state === 'closed'
        ? '<svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12h18M3 6h18M3 18h18"/></svg>'
        : '<svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 10l7-7m0 0l7 7m-7-7v18"/></svg>';
    } else {
      return state === 'closed'
        ? '<svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"/></svg>'
        : '<svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 10l7-7m0 0l7 7m-7-7v18"/></svg>';
    }
  }

  getBatteryIcon(level) {
    const batteryLevel = parseInt(level);
    return `<svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7V3H8v4m8 0H8m8 0v10a2 2 0 01-2 2H10a2 2 0 01-2-2V7"/></svg>`;
  }

  getTimeAgo(date) {
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);
    
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    return `${diffDays}d ago`;
  }

  attachEventListeners() {
    // Badge click (main area, not admin button)
    const badgeMain = this.shadowRoot.querySelector('.badge-main');
    if (badgeMain) {
      badgeMain.addEventListener('click', () => {
        this._showInterface = true;
        this.render();
      });
    }

    // Admin button
    this.shadowRoot.querySelectorAll('[data-action="open-admin"]').forEach(el => {
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        try {
          this._showAdmin = true;
          this.render();
          // Mount the admin panel
          const container = this.shadowRoot.querySelector('#admin-container');
          if (container && this._adminPanel) {
            container.appendChild(this._adminPanel);
          }
        } catch (error) {
          _hs.error('Error opening admin panel:', error);
          this._showAdmin = false;
          this.render();
        }
      });
    });

    // Close admin error button
    this.shadowRoot.querySelectorAll('[data-action="close-admin-error"]').forEach(el => {
      el.addEventListener('click', () => {
        this._showAdmin = false;
        this.render();
      });
    });

    // Close button
    // Step 9: close resets arm PIN state too
    this.shadowRoot.querySelectorAll('[data-action="close"]').forEach(el => {
      el.addEventListener('click', () => {
        this._showInterface = false;
        this._showArmPin    = false;
        this._armAction     = null;
        this._pin           = '';
        this.render();
      });
    });

    // Keypad — shared by disarm, arm PIN
    this.shadowRoot.querySelectorAll('[data-action="number"]').forEach(el => {
      el.addEventListener('click', () => {
        if (this._pin.length < 8) {
          this._pin += el.dataset.value;
          this.updatePinDisplay();
        }
      });
    });

    this.shadowRoot.querySelectorAll('[data-action="clear"]').forEach(el => {
      el.addEventListener('click', () => {
        this._pin = '';
        this.updatePinDisplay();
      });
    });

    // Steps 6 & 7: arm buttons — show PIN keypad if required, else arm directly
    this.shadowRoot.querySelectorAll('[data-action="arm-home"]').forEach(el => {
      el.addEventListener('click', () => {
        if (this._serverConfig.require_pin_to_arm) {
          this._showArmPin = true;
          this._armAction  = 'arm_home';
          this._pin        = '';
          this.render();
        } else {
          this._apiCall('/api/arm_home', {}).catch(e => _hs.error('arm_home failed:', e));
          this._showInterface = false;
          setTimeout(() => this.render(), 300);
        }
      });
    });

    this.shadowRoot.querySelectorAll('[data-action="arm-away"]').forEach(el => {
      el.addEventListener('click', () => {
        if (this._serverConfig.require_pin_to_arm) {
          this._showArmPin = true;
          this._armAction  = 'arm_away';
          this._pin        = '';
          this.render();
        } else {
          this._apiCall('/api/arm_away', {}).catch(e => _hs.error('arm_away failed:', e));
          this._showInterface = false;
          setTimeout(() => this.render(), 300);
        }
      });
    });

    // Step 8: confirm-arm — send PIN to arm endpoint
    this.shadowRoot.querySelectorAll('[data-action="confirm-arm"]').forEach(el => {
      el.addEventListener('click', () => {
        if (this._pin.length >= 6) {
          const pin    = this._pin;
          const action = this._armAction || 'arm_home';
          this._pin        = '';
          this._showArmPin = false;
          this._armAction  = null;
          this._showInterface = false;
          this._apiCall(`/api/${action}`, { pin })
            .catch(e => _hs.error('arm with PIN failed:', e));
          setTimeout(() => this.render(), 300);
        }
      });
    });

    this.shadowRoot.querySelectorAll('[data-action="disarm"]').forEach(el => {
      el.addEventListener('click', () => {
        if (this._pin.length >= 6) {
          const pin = this._pin;
          this._pin = '';
          this._showInterface = false;
          this._apiCall('/api/disarm', { pin }).catch(e => _hs.error('disarm failed:', e));
          setTimeout(() => this.render(), 300);
        }
      });
    });

    // Entry point toggles
    this.shadowRoot.querySelectorAll('[data-action="toggle-entry"]').forEach(el => {
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        const entityId = el.dataset.entity;
        const garageType = el.dataset.garageType || 'toggle';
        const entity = this._hass.states[entityId];
        if (entity) {
          const domain = entityId.split('.')[0];
          
          // Handle garage doors based on their type
          if (domain === 'cover' && entityId.includes('garage')) {
            if (garageType === 'button') {
              // For button-type garage doors, always call toggle
              this.callService(domain, 'toggle', { entity_id: entityId });
            } else {
              // For toggle-type garage doors, call open or close based on state
              const service = entity.state === 'open' ? 'close_cover' : 'open_cover';
              this.callService(domain, service, { entity_id: entityId });
            }
          } else {
            // For locks and other devices, use lock/unlock
            const service = entity.state === 'locked' ? 'unlock' : 'lock';
            this.callService(domain, service, { entity_id: entityId });
          }
        }
      });
    });
  }

  async _apiCall(path, body) {
    const headers = { 'Content-Type': 'application/json' };
    if (this._apiToken) headers['Authorization'] = `Bearer ${this._apiToken}`;
    const resp = await fetch(this._apiUrl + path, {
      method: 'POST',
      headers,
      body: JSON.stringify(body)
    });
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`API error ${resp.status}: ${text}`);
    }
    return resp.json();
  }

  callService(domain, service, data) {
    // Used only for native HA entity toggles (lock/cover entry points)
    this._hass.callService(domain, service, data);
  }
}

customElements.define('homesecure-card', HomeSecureCard);

// Visual Editor for Badge Card

class HomeSecureCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { entry_points: [], card_height: '100%', ...config };
    if (!this.shadowRoot) {
      this.attachShadow({ mode: 'open' });
    }
    this.render();
  }

  set hass(hass) {
    const oldHass = this._hass;
    this._hass = hass;
    const oldEntity = this.entity;
    this.entity = hass.states[this.config?.entity];
    
    if (this.entity && !this._showAdmin) {
      // Only render if the entity actually changed
      if (!oldEntity || oldEntity.state !== this.entity.state || 
          oldEntity.last_changed !== this.entity.last_changed) {
        this.render();
      }
    }
  }

  render() {
    if (!this._hass || !this._config) return;

    const entities = Object.keys(this._hass.states)
      .filter(e => e.startsWith('alarm_control_panel.'))
      .sort();

    const allEntities = Object.keys(this._hass.states).sort();

    this.shadowRoot.innerHTML = `
      <style>
        .card-config {
          padding: 16px;
        }
        .option {
          margin-bottom: 20px;
        }
        .option label {
          display: block;
          margin-bottom: 8px;
          font-weight: 500;
          color: var(--primary-text-color);
        }
        .option select,
        .option input {
          width: 100%;
          padding: 8px;
          border: 1px solid var(--divider-color);
          border-radius: 4px;
          background: var(--card-background-color);
          color: var(--primary-text-color);
          font-size: 14px;
          box-sizing: border-box;
        }
        .option select:focus,
        .option input:focus {
          outline: none;
          border-color: #667eea;
        }
        .help-text {
          font-size: 12px;
          color: var(--secondary-text-color);
          margin-top: 4px;
        }
        .entry-points {
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          padding: 16px;
          margin-top: 12px;
        }
        .entry-points-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
        }
        .entry-points-title {
          font-weight: 600;
          color: var(--primary-text-color);
        }
        .add-entry-btn {
          background: #667eea;
          color: white;
          border: none;
          border-radius: 6px;
          padding: 6px 12px;
          font-size: 13px;
          cursor: pointer;
        }
        .add-entry-btn:hover {
          background: #5568d3;
        }
        .entry-point-config {
          background: var(--secondary-background-color);
          border-radius: 6px;
          padding: 12px;
          margin-bottom: 12px;
          position: relative;
        }
        .remove-entry-btn {
          position: absolute;
          top: 8px;
          right: 8px;
          background: #ef4444;
          color: white;
          border: none;
          border-radius: 4px;
          padding: 4px 8px;
          font-size: 11px;
          cursor: pointer;
        }
        .remove-entry-btn:hover {
          background: #dc2626;
        }
        .entry-field {
          margin-bottom: 12px;
        }
        .entry-field label {
          display: block;
          font-size: 12px;
          font-weight: 500;
          margin-bottom: 4px;
          color: var(--primary-text-color);
        }
        .entry-field input,
        .entry-field select {
          width: 100%;
          padding: 6px;
          border: 1px solid var(--divider-color);
          border-radius: 4px;
          background: var(--card-background-color);
          color: var(--primary-text-color);
          font-size: 13px;
          box-sizing: border-box;
        }
      </style>
      <div class="card-config">
        <div class="option">
          <label for="entity">Alarm Entity (Required)</label>
          <select id="entity">
            <option value="">Select entity...</option>
            ${entities.map(e => `
              <option value="${e}" ${this._config.entity === e ? 'selected' : ''}>
                ${e}
              </option>
            `).join('')}
          </select>
          <div class="help-text">Select your secure alarm control panel entity</div>
        </div>

        <div class="option">
          <label for="card_height">Card Height</label>
          <input 
            type="text" 
            id="card_height" 
            value="${this._config.card_height || '100%'}"
            placeholder="100%, 500px, 80vh, etc."
          />
          <div class="help-text">Set card height (CSS value like 100%, 600px, 80vh)</div>
        </div>

        <div class="option">
          <label for="container_top_padding">Top Padding</label>
          <input 
            type="text" 
            id="container_top_padding" 
            value="${this._config.container_top_padding || '80px'}"
            placeholder="80px, 5%, 10vh, etc."
          />
          <div class="help-text">Space from top of card to content (default: 80px)</div>
        </div>

        <div class="option">
          <label for="container_alignment">Horizontal Alignment</label>
          <select id="container_alignment">
            <option value="center" ${(this._config.container_alignment || 'center') === 'center' ? 'selected' : ''}>Center</option>
            <option value="flex-start" ${this._config.container_alignment === 'flex-start' ? 'selected' : ''}>Left</option>
            <option value="flex-end" ${this._config.container_alignment === 'flex-end' ? 'selected' : ''}>Right</option>
          </select>
          <div class="help-text">Horizontal position of badge container</div>
        </div>

        <div class="option">
          <label for="container_max_width">Container Max Width</label>
          <input 
            type="text" 
            id="container_max_width" 
            value="${this._config.container_max_width || '1200px'}"
            placeholder="1200px, 90%, etc."
          />
          <div class="help-text">Maximum width of badge container (default: 1200px)</div>
        </div>  

        <div class="option">
          <label>Entry Points (Optional)</label>
          <div class="help-text" style="margin-bottom: 8px;">
            Add locks and sensors to display on the badge
          </div>
          <div class="entry-points">
            <div class="entry-points-header">
              <span class="entry-points-title">
                ${this._config.entry_points.length} Entry Point${this._config.entry_points.length !== 1 ? 's' : ''}
              </span>
              <button class="add-entry-btn" id="add-entry">+ Add</button>
            </div>
            <div id="entry-points-list">
              ${this._config.entry_points.map((ep, idx) => this.renderEntryPoint(ep, idx, allEntities)).join('')}
            </div>
          </div>
        </div>
      </div>
    `;

    this.attachEditorListeners(allEntities);
  }

  renderEntryPoint(entryPoint, index, allEntities) {
    const showGarageType = entryPoint.type === 'garage';
    return `
      <div class="entry-point-config" data-index="${index}">
        <button class="remove-entry-btn" data-action="remove" data-index="${index}">Remove</button>
        
        <div class="entry-field">
          <label>Name</label>
          <input type="text" 
                 data-field="name" 
                 data-index="${index}"
                 value="${entryPoint.name || ''}"
                 placeholder="Front Door">
        </div>

        <div class="entry-field">
          <label>Entity ID</label>
          <select data-field="entity_id" data-index="${index}">
            <option value="">Select entity...</option>
            ${allEntities.map(e => `
              <option value="${e}" ${entryPoint.entity_id === e ? 'selected' : ''}>
                ${e}
              </option>
            `).join('')}
          </select>
        </div>

        <div class="entry-field">
          <label>Type</label>
          <select data-field="type" data-index="${index}">
            <option value="door" ${entryPoint.type === 'door' ? 'selected' : ''}>Door</option>
            <option value="window" ${entryPoint.type === 'window' ? 'selected' : ''}>Window</option>
            <option value="garage" ${entryPoint.type === 'garage' ? 'selected' : ''}>Garage</option>
            <option value="motion" ${entryPoint.type === 'motion' ? 'selected' : ''}>Motion</option>
          </select>
        </div>

        ${showGarageType ? `
          <div class="entry-field" data-garage-type-field="${index}">
            <label>Garage Door Control Type</label>
            <select data-field="garage_type" data-index="${index}">
              <option value="toggle" ${(entryPoint.garage_type === 'toggle' || !entryPoint.garage_type) ? 'selected' : ''}>Toggle (Open/Close separately)</option>
              <option value="button" ${entryPoint.garage_type === 'button' ? 'selected' : ''}>Button (Single button toggle)</option>
            </select>
            <div class="help-text">Select "Button" for garage doors that use a single button to open and close</div>
          </div>
        ` : ''}

        <div class="entry-field">
          <label>Battery Entity (Optional)</label>
          <select data-field="battery_entity" data-index="${index}">
            <option value="">None</option>
            ${allEntities.filter(e => e.includes('battery')).map(e => `
              <option value="${e}" ${entryPoint.battery_entity === e ? 'selected' : ''}>
                ${e}
              </option>
            `).join('')}
          </select>
        </div>
      </div>
    `;
  }

  attachEditorListeners(allEntities) {
    // Entity selector
    const entitySelect = this.shadowRoot.getElementById('entity');
    if (entitySelect) {
      entitySelect.addEventListener('change', (e) => {
        this._config = { ...this._config, entity: e.target.value };
        this.configChanged();
      });
    }

    // Card height
    const heightInput = this.shadowRoot.getElementById('card_height');
    if (heightInput) {
      heightInput.addEventListener('input', (e) => {
        this._config = { ...this._config, card_height: e.target.value };
        this.configChanged();
      });
    }

    // Container top padding
    const topPaddingInput = this.shadowRoot.getElementById('container_top_padding');
    if (topPaddingInput) {
      topPaddingInput.addEventListener('input', (e) => {
        this._config = { ...this._config, container_top_padding: e.target.value };
        this.configChanged();
      });
    }

    // Container alignment
    const alignmentSelect = this.shadowRoot.getElementById('container_alignment');
    if (alignmentSelect) {
      alignmentSelect.addEventListener('change', (e) => {
        this._config = { ...this._config, container_alignment: e.target.value };
        this.configChanged();
      });
    }

    // Container max width
    const maxWidthInput = this.shadowRoot.getElementById('container_max_width');
    if (maxWidthInput) {
      maxWidthInput.addEventListener('input', (e) => {
        this._config = { ...this._config, container_max_width: e.target.value };
        this.configChanged();
      });
    }

    // Add entry point
    const addBtn = this.shadowRoot.getElementById('add-entry');
    if (addBtn) {
      addBtn.addEventListener('click', () => {
        this._config.entry_points = [
          ...this._config.entry_points,
          { name: '', entity_id: '', type: 'door', garage_type: 'toggle', battery_entity: '' }
        ];
        this.configChanged();
        this.render();
      });
    }

    // Remove entry point
    this.shadowRoot.querySelectorAll('[data-action="remove"]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const index = parseInt(e.target.dataset.index);
        this._config.entry_points = this._config.entry_points.filter((_, i) => i !== index);
        this.configChanged();
        this.render();
      });
    });

    // Entry point field changes
    this.shadowRoot.querySelectorAll('[data-field]').forEach(input => {
      input.addEventListener('change', (e) => {
        const index = parseInt(e.target.dataset.index);
        const field = e.target.dataset.field;
        this._config.entry_points[index][field] = e.target.value;
        
        // If type changes to/from garage, re-render to show/hide garage_type field
        if (field === 'type') {
          // Initialize garage_type if switching to garage
          if (e.target.value === 'garage' && !this._config.entry_points[index].garage_type) {
            this._config.entry_points[index].garage_type = 'toggle';
          }
          this.render();
        }
        
        this.configChanged();
      });
    });
  }

  configChanged() {
    this.dispatchEvent(new CustomEvent('config-changed', {
      detail: { config: this._config },
      bubbles: true,
      composed: true
    }));
  }
}

customElements.define('homesecure-card-editor', HomeSecureCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'homesecure-card',
  name: 'HomeSecure Badge Card',
  description: 'Badge-style alarm control with admin panel and entry point management',
  preview: true,
  documentationURL: 'https://github.com/mmotrock/homesecure-addon'
});