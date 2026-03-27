/**
 * HomeSecure Admin Panel v2.0
 * Admin interface — talks directly to the HomeSecure container REST API.
 * No longer uses HA services for user/lock/config operations.
 *
 * Config options:
 *   entity    - alarm_control_panel entity (for state display)
 *   api_url   - Container API URL (default: http://localhost:8099)
 *   api_token - Optional API bearer token
 */

class HomeSecureAdmin extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._authenticated = false;
    this._pin = '';
    this._adminPin = null;  // Store authenticated admin PIN
    this._failedAttempts = 0;
    this._lockedUntil = null;
    this._lockoutKey = 'homesecure_admin_lockout';
    this._currentView = 'auth'; // auth, main, user-list, user-detail, user-add
    this._currentTab = 'users'; // users, devices, security, general
    this._selectedUser = null;
    this._users = [];
    this._editingUser = {};
    this._usersLoaded = false;
    this._lockoutTimer = null;
    this._events = [];
    this._eventTypes = [];
    this._eventStats = null;
    this._eventFilters = {
      eventTypes: [],
      entityId: '',
      userId: null,
      days: 7
    };
    this._eventsLoaded = false;
    this._pendingRequirePin = undefined;  // tracks unsaved toggle state on Security tab
    this._bootstrapActive = false;  // true when no users exist and bootstrap PIN is set
    this._bootstrapChecked = false; // prevent repeated checks
    // Load lockout state from localStorage
    this.loadLockoutState();
  }

  static getConfigElement() {
    return document.createElement('homesecure-admin-editor');
  }

  static getStubConfig() {
    return {
      entity: 'alarm_control_panel.homesecure'
    };
  }

  loadLockoutState() {
    try {
      const stored = localStorage.getItem(this._lockoutKey);
      if (stored) {
        const data = JSON.parse(stored);
        this._lockedUntil = data.lockedUntil ? new Date(data.lockedUntil) : null;
        this._failedAttempts = data.failedAttempts || 0;
        
        // If lockout time has passed, clear it immediately
        if (this._lockedUntil && new Date() >= this._lockedUntil) {
          console.log('Lockout expired on load, clearing');
          this._lockedUntil = null;
          this._failedAttempts = 0;
          this.saveLockoutState();
        }
        
        console.log('Loaded lockout state:', {
          lockedUntil: this._lockedUntil,
          failedAttempts: this._failedAttempts
        });
      }
    } catch (e) {
      console.error('Failed to load lockout state:', e);
    }
  }

  saveLockoutState() {
    try {
      localStorage.setItem(this._lockoutKey, JSON.stringify({
        lockedUntil: this._lockedUntil ? this._lockedUntil.toISOString() : null,
        failedAttempts: this._failedAttempts
      }));
    } catch (e) {
      console.error('Failed to save lockout state:', e);
    }
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error('Please define an entity');
    }
    this.config = config;
    this._apiUrl = (config.api_url || 'http://localhost:8099').replace(/\/$/, '');
    this._apiToken = config.api_token || '';
    this.render();
  }

  set hass(hass) {
    const oldHass = this._hass;
    this._hass = hass;
    
    // Only update entity reference if hass changed
    if (this.config && this.config.entity) {
      this.entity = hass.states[this.config.entity];
    }
    
    // Check bootstrap status once on first load
    if (this.entity && !this._bootstrapChecked) {
      this._bootstrapChecked = true;
      this.checkBootstrap();
    }

    // Only load users once when first authenticated
    if (this.entity && this._authenticated && !this._usersLoaded) {
      this._usersLoaded = true;
      this.loadUsers().catch(err => {
        console.error('Failed to load users:', err);
      });
    }
    
    // Only render when:
    // 1. Not authenticated yet (showing auth screen)
    // 2. Locked out (showing lockout screen)
    // 3. First time hass is set
    if (!this._authenticated || this._lockedUntil || !oldHass) {
      this.render();
    }
  }

  getCardSize() {
    return 6;
  }

  async checkBootstrap() {
    try {
      const data = await this._apiFetch('/api/bootstrap');
      this._bootstrapActive = data.bootstrap_active === true;
      if (this._bootstrapActive) {
        this._bootstrapUser = { name: '', pin: '', confirmPin: '' };
        this.render();
      }
    } catch (e) {
      console.error('Bootstrap check failed:', e);
    }
  }

  renderBootstrap() {
    return `
      <ha-card>
        <div class="admin-container">
          ${this.renderHeader()}
          <div class="admin-body">
            <div class="pin-auth" style="max-width: 480px; margin: 0 auto; padding: 32px 20px;">
              <div class="pin-display" style="margin-bottom: 24px;">
                <div class="pin-label" style="font-size: 20px; margin-bottom: 8px;">🎉 Welcome to HomeSecure</div>
                <div class="pin-sublabel" style="font-size: 14px; line-height: 1.6;">
                  No users exist yet. Check the <strong>addon logs</strong> for your one-time
                  bootstrap PIN, then create your first admin user below.
                </div>
              </div>

              <div class="form-group">
                <label class="form-label">Bootstrap PIN (from addon logs) *</label>
                <input type="password" class="form-input" id="bootstrap-pin"
                       placeholder="Enter bootstrap PIN from logs" maxlength="8">
              </div>

              <div class="form-group">
                <label class="form-label">Your Name *</label>
                <input type="text" class="form-input" id="bootstrap-name"
                       placeholder="e.g. Admin">
              </div>

              <div class="form-group">
                <label class="form-label">Choose your Admin PIN (6–8 digits) *</label>
                <input type="password" class="form-input" id="bootstrap-new-pin"
                       placeholder="6–8 digit PIN you will use to log in" maxlength="8">
              </div>

              <div class="form-group">
                <label class="form-label">Confirm Admin PIN *</label>
                <input type="password" class="form-input" id="bootstrap-confirm-pin"
                       placeholder="Re-enter your PIN" maxlength="8">
              </div>

              <div id="bootstrap-error" style="display:none; color:#ef4444; font-size:13px;
                   margin-bottom: 12px; padding: 10px; background: rgba(239,68,68,0.1);
                   border-radius: 8px;"></div>

              <button class="btn btn-primary" data-action="bootstrap-create"
                      style="width: 100%; margin-top: 8px;">
                Create Admin Account
              </button>
            </div>
          </div>
        </div>
      </ha-card>
    `;
  }

  async loadUsers() {
    try {
      const data = await this._apiFetch('/api/users');
      this._users = (data.users || []).map(u => ({
        ...u,
        is_admin: Boolean(u.is_admin),
        enabled: Boolean(u.enabled !== 0),
        has_separate_lock_pin: Boolean(u.has_separate_lock_pin),
        lock_pin_display: u.has_separate_lock_pin ? '••••••' : '',
        slot_number: u.slot_number || null
      }));
      console.log('Loaded users:', this._users.length);
    } catch (e) {
      console.error('Failed to load users:', e);
      this._users = [];
    }
  }

  render() {
    if (!this.entity) {
      console.warn('HomeSecureAdmin: No entity found');
      return;
    }

    // Check if locked out - reset if time expired
    const now = new Date();
    if (this._lockedUntil && now >= this._lockedUntil) {
      console.log('Lockout expired, resetting');
      this._lockedUntil = null;
      this._failedAttempts = 0;
      this.saveLockoutState();
    }

    try {
      console.log('HomeSecureAdmin: Rendering', { 
        authenticated: this._authenticated, 
        view: this._currentView,
        usersCount: this._users.length,
        failedAttempts: this._failedAttempts,
        lockedUntil: this._lockedUntil
      });
      
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: block;
          }
          ha-card {
            padding: 0;
            overflow: hidden;
            max-height: 90vh;
            display: flex;
            flex-direction: column;
          }
          .admin-container {
            display: flex;
            flex-direction: column;
            height: 100%;
            max-height: 90vh;
          }
          .admin-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            position: relative;
            flex-shrink: 0;
          }
          .header-content {
            display: flex;
            align-items: center;
            justify-content: space-between;
          }
          .header-title {
            display: flex;
            align-items: center;
            gap: 12px;
          }
          .header-title svg {
            width: 28px;
            height: 28px;
          }
          .header-title h2 {
            margin: 0;
            font-size: 22px;
            font-weight: 600;
          }
          .close-btn {
            background: rgba(255, 255, 255, 0.2);
            border: none;
            border-radius: 8px;
            padding: 8px;
            cursor: pointer;
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
          }
          .close-btn:hover {
            background: rgba(255, 255, 255, 0.3);
          }
          .close-btn svg {
            width: 24px;
            height: 24px;
          }
          .tab-bar {
            display: flex;
            background: var(--card-background-color);
            border-bottom: 1px solid var(--divider-color);
            overflow-x: auto;
            flex-shrink: 0;
          }
          .tab {
            flex: 1;
            padding: 16px;
            border: none;
            background: none;
            color: var(--primary-text-color);
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            border-bottom: 3px solid transparent;
            transition: all 0.2s;
            white-space: nowrap;
          }
          .tab:hover {
            background: var(--secondary-background-color);
          }
          .tab.active {
            color: #667eea;
            border-bottom-color: #667eea;
          }
          .admin-body {
            flex: 1;
            overflow-y: auto;
            overflow-x: hidden;
            padding: 20px;
            min-height: 0;
          }
          .pin-auth {
            max-width: 400px;
            margin: 0 auto;
            padding: 40px 20px;
          }
          .pin-auth-landscape {
            max-width: none;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 40px;
            align-items: center;
            padding: 40px;
          }
          @media (max-width: 768px) {
            .pin-auth-landscape {
              grid-template-columns: 1fr;
              gap: 20px;
            }
          }
          .pin-display {
            background: var(--secondary-background-color);
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 24px;
            text-align: center;
          }
          .pin-label {
            font-size: 16px;
            color: var(--primary-text-color);
            margin-bottom: 12px;
            font-weight: 500;
          }
          .pin-sublabel {
            font-size: 12px;
            color: var(--disabled-text-color);
            margin-bottom: 16px;
          }
          .pin-dots {
            font-size: 36px;
            letter-spacing: 12px;
            color: var(--primary-text-color);
            min-height: 50px;
            display: flex;
            align-items: center;
            justify-content: center;
          }
          .pin-counter {
            font-size: 13px;
            color: var(--disabled-text-color);
            margin-top: 12px;
          }
          .attempts-warning {
            color: #ef4444;
            font-size: 13px;
            margin-top: 8px;
            font-weight: 500;
          }
          .keypad {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
            margin-bottom: 16px;
          }
          .key {
            background: var(--secondary-background-color);
            border: 2px solid var(--divider-color);
            border-radius: 12px;
            padding: 20px;
            font-size: 24px;
            font-weight: 600;
            color: var(--primary-text-color);
            cursor: pointer;
            transition: all 0.15s;
          }
          .key:hover {
            transform: scale(1.05);
            border-color: #667eea;
            background: var(--primary-background-color);
          }
          .key:active {
            transform: scale(0.95);
          }
          .key.clear {
            background: #dc2626;
            color: white;
            border-color: #dc2626;
          }
          .key.clear:hover {
            background: #b91c1c;
            border-color: #b91c1c;
          }
          .key.enter {
            background: #16a34a;
            color: white;
            border-color: #16a34a;
          }
          .key.enter:hover {
            background: #15803d;
            border-color: #15803d;
          }
          .key.enter:disabled {
            opacity: 0.5;
            cursor: not-allowed;
          }
          .user-list {
            display: flex;
            flex-direction: column;
            gap: 12px;
          }
          .list-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
          }
          .list-title {
            font-size: 20px;
            font-weight: 600;
            color: var(--primary-text-color);
          }
          .add-btn {
            background: #667eea;
            color: white;
            border: none;
            border-radius: 10px;
            padding: 10px 20px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 8px;
            transition: all 0.2s;
          }
          .add-btn:hover {
            background: #5568d3;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
          }
          .add-btn svg {
            width: 20px;
            height: 20px;
          }
          .user-card {
            background: var(--card-background-color);
            border: 1px solid var(--divider-color);
            border-radius: 12px;
            padding: 16px;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            justify-content: space-between;
          }
          .user-card:hover {
            border-color: #667eea;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
            transform: translateY(-2px);
          }
          .user-info {
            display: flex;
            align-items: center;
            gap: 16px;
            flex: 1;
          }
          .user-avatar {
            width: 48px;
            height: 48px;
            border-radius: 50%;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 20px;
            font-weight: 600;
          }
          .user-details {
            flex: 1;
          }
          .user-name {
            font-size: 16px;
            font-weight: 600;
            color: var(--primary-text-color);
            margin-bottom: 4px;
          }
          .user-meta {
            font-size: 13px;
            color: var(--secondary-text-color);
            display: flex;
            align-items: center;
            gap: 12px;
          }
          .admin-badge {
            background: #fbbf24;
            color: #78350f;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
          }
          .user-arrow {
            color: var(--disabled-text-color);
          }
          .user-arrow svg {
            width: 20px;
            height: 20px;
          }
          .user-detail {
            max-width: 600px;
            margin: 0 auto;
          }
          .back-btn {
            background: none;
            border: none;
            color: #667eea;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 20px;
            padding: 8px;
          }
          .back-btn:hover {
            background: var(--secondary-background-color);
            border-radius: 8px;
          }
          .back-btn svg {
            width: 20px;
            height: 20px;
          }
          .form-group {
            margin-bottom: 20px;
          }
          .form-label {
            display: block;
            font-size: 14px;
            font-weight: 500;
            color: var(--primary-text-color);
            margin-bottom: 8px;
          }
          .form-input {
            width: 100%;
            padding: 12px;
            border: 2px solid var(--divider-color);
            border-radius: 8px;
            background: var(--card-background-color);
            color: var(--primary-text-color);
            font-size: 14px;
            box-sizing: border-box;
          }
          .form-input:focus {
            outline: none;
            border-color: #667eea;
          }
          .form-input.invalid {
            border-color: #ef4444;
            background: rgba(239, 68, 68, 0.05);
          }
          .field-error {
            font-size: 12px;
            color: #ef4444;
            margin-top: 4px;
            display: none;
          }
          .field-error.visible {
            display: block;
          }
          .form-toggle {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px;
            background: var(--secondary-background-color);
            border-radius: 8px;
          }
          .toggle-label {
            font-size: 14px;
            font-weight: 500;
            color: var(--primary-text-color);
          }
          .toggle-switch {
            position: relative;
            width: 48px;
            height: 28px;
            background: var(--divider-color);
            border-radius: 14px;
            cursor: pointer;
            transition: background 0.3s;
          }
          .toggle-switch.active {
            background: #667eea;
          }
          .toggle-knob {
            position: absolute;
            top: 2px;
            left: 2px;
            width: 24px;
            height: 24px;
            background: white;
            border-radius: 50%;
            transition: transform 0.3s;
          }
          .toggle-switch.active .toggle-knob {
            transform: translateX(20px);
          }
          .form-actions {
            display: flex;
            gap: 12px;
            margin-top: 32px;
          }
          .btn {
            flex: 1;
            padding: 14px;
            border: none;
            border-radius: 10px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
          }
          .btn-primary {
            background: #667eea;
            color: white;
          }
          .btn-primary:hover {
            background: #5568d3;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
          }
          .btn-secondary {
            background: var(--secondary-background-color);
            color: var(--primary-text-color);
          }
          .btn-secondary:hover {
            background: var(--divider-color);
          }
          .btn-danger {
            background: #ef4444;
            color: white;
          }
          .btn-danger:hover {
            background: #dc2626;
          }
          .empty-state {
            text-align: center;
            padding: 60px 20px;
          }
          .empty-state svg {
            width: 64px;
            height: 64px;
            color: var(--disabled-text-color);
            margin-bottom: 16px;
          }
          .empty-state-title {
            font-size: 18px;
            font-weight: 600;
            color: var(--primary-text-color);
            margin-bottom: 8px;
          }
          .empty-state-text {
            font-size: 14px;
            color: var(--secondary-text-color);
          }
          .locked-out {
            text-align: center;
            padding: 60px 20px;
          }
          .locked-icon {
            width: 80px;
            height: 80px;
            margin: 0 auto 24px;
            color: #ef4444;
          }
          .locked-title {
            font-size: 24px;
            font-weight: 700;
            color: #ef4444;
            margin-bottom: 12px;
          }
          .locked-text {
            font-size: 16px;
            color: var(--secondary-text-color);
            margin-bottom: 8px;
          }
          .locked-timer {
            font-size: 32px;
            font-weight: 700;
            color: var(--primary-text-color);
            margin: 20px 0;
          }
          .user-actions {
            display: flex;
            align-items: center;
            gap: 12px;
          }
          .disabled-avatar {
            opacity: 0.5;
            background: linear-gradient(135deg, #6b7280 0%, #4b5563 100%);
          }
          .disabled-text {
            opacity: 0.6;
          }
          .disabled-badge {
            background: #ef4444;
            color: white;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
          }
          /* .lock-access-section {
            margin-top: 24px;
            padding: 16px;
            background: var(--secondary-background-color);
            border-radius: 12px;
          }
          .lock-access-title {
            font-size: 14px;
            font-weight: 600;
            color: var(--primary-text-color);
            margin-bottom: 12px;
          }
          .lock-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px;
            background: var(--card-background-color);
            border-radius: 8px;
            margin-bottom: 8px;
          }
          .lock-item-name {
            font-size: 14px;
            color: var(--primary-text-color);
          } */
        </style>
        ${this.renderContent()}
      `;

      this.attachEventListeners();
    } catch (error) {
      console.error('Error rendering admin panel:', error);
      console.error('Stack trace:', error.stack);
      this.shadowRoot.innerHTML = `
        <ha-card>
          <div style="padding: 20px; color: var(--error-color);">
            <h3>Error Loading Admin Panel</h3>
            <p>${error.message}</p>
            <pre style="font-size: 11px; overflow: auto; background: var(--secondary-background-color); padding: 8px; border-radius: 4px; margin-top: 8px;">${error.stack}</pre>
            <button style="padding: 8px 16px; margin-top: 12px; background: var(--primary-color); color: white; border: none; border-radius: 4px; cursor: pointer;" onclick="location.reload()">Reload Page</button>
          </div>
        </ha-card>
      `;
    }
  }

  renderContent() {
    if (this._lockedUntil && new Date() < this._lockedUntil) {
      return this.renderLockedOut();
    }

    if (this._bootstrapActive) {
      return this.renderBootstrap();
    }

    if (!this._authenticated) {
      return this.renderAuth();
    }

    return `
      <ha-card>
        <div class="admin-container">
          ${this.renderHeader()}
          ${this.renderTabs()}
          <div class="admin-body">
            ${this.renderBody()}
          </div>
        </div>
      </ha-card>
    `;
  }

  renderHeader() {
    return `
      <div class="admin-header">
        <div class="header-content">
          <div class="header-title">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
            </svg>
            <h2>Admin Panel</h2>
          </div>
          <button class="close-btn" data-action="close">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>
      </div>
    `;
  }

  renderTabs() {
    const tabs = [
      { id: 'users', label: 'Users' },
      { id: 'events', label: 'Events' },
      { id: 'devices', label: 'Devices' },
      { id: 'security', label: 'Security' },
      { id: 'general', label: 'General' }
    ];

    return `
      <div class="tab-bar">
        ${tabs.map(tab => `
          <button class="tab ${this._currentTab === tab.id ? 'active' : ''}" 
                  data-action="switch-tab" 
                  data-tab="${tab.id}">
            ${tab.label}
          </button>
        `).join('')}
      </div>
    `;
  }

  renderBody() {
    if (this._currentView === 'user-list') {
      return this.renderUserList();
    } else if (this._currentView === 'user-detail') {
      return this.renderUserDetail();
    } else if (this._currentView === 'user-add') {
      return this.renderUserAdd();
    }

    // Default main view based on tab
    switch (this._currentTab) {
      case 'users':
        return this.renderUserList();
      case 'events':
        return this.renderEventsTab();
      case 'devices':
        return this.renderDevicesTab();
      case 'security':
        return this.renderSecurityTab();
      case 'general':
        return this.renderGeneralTab();
      default:
        return this.renderUserList();
    }
  }

  renderAuth() {
    // If locked out, render the lockout screen instead
    if (this._lockedUntil && new Date() < this._lockedUntil) {
      return this.renderLockedOut();
    }
    const maxAttempts = this._config?.max_failed_attempts ?? 5;
    const pinDots = '●'.repeat(this._pin.length) || '●●●●●●';
    const remainingAttempts = maxAttempts - this._failedAttempts;

    return `
      <ha-card>
        <div class="admin-container">
          ${this.renderHeader()}
          <div class="admin-body">
            <div class="pin-auth pin-auth-landscape">
              <div class="pin-display">
                <div class="pin-label">Admin Authentication</div>
                <div class="pin-sublabel">Enter your admin PIN to continue</div>
                <div class="pin-dots">${pinDots}</div>
                <div class="pin-counter">${this._pin.length}/8 digits</div>
                ${this._failedAttempts > 0 ? `
                  <div class="attempts-warning">
                    ⚠️ ${remainingAttempts} attempt${remainingAttempts !== 1 ? 's' : ''} remaining
                    before ${Math.round((this._config?.lockout_duration ?? 300) / 60)}-minute lockout
                  </div>
                ` : ''}
              </div>
              <div class="keypad">
                ${[1,2,3,4,5,6,7,8,9].map(n => `
                  <button class="key" data-action="auth-number" data-value="${n}">${n}</button>
                `).join('')}
                <button class="key clear" data-action="auth-clear">✕</button>
                <button class="key" data-action="auth-number" data-value="0">0</button>
                <button class="key enter" data-action="auth-submit" ${this._pin.length < 6 ? 'disabled' : ''}>✓</button>
              </div>
            </div>
          </div>
        </div>
      </ha-card>
    `;
  }

  renderLockedOut() {
    const now = new Date();
    const timeRemaining = Math.max(0, Math.ceil((this._lockedUntil - now) / 1000));
    const minutes = Math.floor(timeRemaining / 60);
    const seconds = timeRemaining % 60;
    const lockoutMins = Math.round((this._config?.lockout_duration ?? 300) / 60);

    return `
      <ha-card>
        <div class="admin-container">
          ${this.renderHeader()}
          <div class="admin-body">
            <div class="locked-out">
              <svg class="locked-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
              </svg>
              <div class="locked-title">🔒 Access Locked</div>
              <div class="locked-text" style="font-size:15px; margin-bottom: 4px;">
                Too many failed PIN attempts.
              </div>
              <div class="locked-text" style="font-size:13px; color: var(--secondary-text-color); margin-bottom: 20px;">
                You have been locked out for ${lockoutMins} minute${lockoutMins !== 1 ? 's' : ''}.
                Try again when the timer reaches 0:00.
              </div>
              <div class="locked-timer">${minutes}:${seconds.toString().padStart(2, '0')}</div>
              <div style="font-size: 12px; color: var(--disabled-text-color); margin-top: 12px;">
                Lockout duration is configurable in the Security tab.
              </div>
            </div>
          </div>
        </div>
      </ha-card>
    `;
  }

  renderUserList() {
    return `
      <div class="user-list">
        <div class="list-header">
          <div class="list-title">Users</div>
          <button class="add-btn" data-action="add-user">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
            </svg>
            Add User
          </button>
        </div>
        ${this._users.length === 0 ? `
          <div class="empty-state">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"/>
            </svg>
            <div class="empty-state-title">No Users</div>
            <div class="empty-state-text">Add your first user to get started</div>
          </div>
        ` : this._users.map(user => this.renderUserCard(user)).join('')}
      </div>
    `;
  }

  renderUserCard(user) {
    const initials = user.name.split(' ').map(n => n[0]).join('').toUpperCase();
    return `
      <div class="user-card" ${user.enabled ? `data-action="select-user" data-user-id="${user.id}"` : ''}>
        <div class="user-info">
          <div class="user-avatar ${!user.enabled ? 'disabled-avatar' : ''}">${initials}</div>
          <div class="user-details">
            <div class="user-name ${!user.enabled ? 'disabled-text' : ''}">${user.name}</div>
            <div class="user-meta">
              ${user.is_admin ? '<span class="admin-badge">Admin</span>' : ''}
              ${user.slot_number ? `<span>Slot ${user.slot_number}</span>` : ''}
              ${user.phone ? `<span>${user.phone}</span>` : ''}
              ${!user.enabled ? '<span class="disabled-badge">Disabled</span>' : ''}
            </div>
          </div>
        </div>
        <div class="user-actions">
          <div class="form-toggle" data-action="toggle-user-enabled" data-user-id="${user.id}" onclick="event.stopPropagation()">
            <div class="toggle-switch ${user.enabled ? 'active' : ''}" data-field="enabled">
              <div class="toggle-knob"></div>
            </div>
          </div>
          ${user.enabled ? `
            <div class="user-arrow">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
              </svg>
            </div>
          ` : ''}
        </div>
      </div>
    `;
  }

  renderUserDetail() {
    const user = this._selectedUser;
    if (!user) return '';

    // Load lock access from DB (instant, no Z-Wave JS query)
    if (user.slot_number && !user._lockAccess && !user._lockAccessLoading) {
      this.loadUserLockAccess(user.id);
    }

    return `
      <div class="user-detail">
        <button class="back-btn" data-action="back-to-list">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
          </svg>
          Back to Users
        </button>

        <div class="form-group">
          <label class="form-label">Name</label>
          <input type="text" class="form-input" data-field="name" value="${user.name || ''}" placeholder="Enter user name">
        </div>

        <div class="form-group">
          <label class="form-label">Alarm PIN (6-8 digits)</label>
          <input type="password" 
                 class="form-input" 
                 data-field="pin" 
                 value="" 
                 placeholder="Enter new PIN or leave blank to keep current">
          <div style="font-size: 12px; color: var(--secondary-text-color); margin-top: 4px;">
            Used for arming/disarming the alarm system. Enter new PIN to change it.
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">Phone Number</label>
          <input type="tel" class="form-input" data-field="phone" value="${user.phone || ''}" placeholder="+1234567890">
        </div>

        <div class="form-group">
          <label class="form-label">Email</label>
          <input type="email" class="form-input" data-field="email" value="${user.email || ''}" placeholder="user@example.com">
        </div>

        <div class="form-group">
          <div class="form-toggle" data-action="toggle-admin">
            <span class="toggle-label">Administrator</span>
            <div class="toggle-switch ${user.is_admin ? 'active' : ''}" data-field="is_admin">
              <div class="toggle-knob"></div>
            </div>
          </div>
        </div>

        <div class="form-group">
          <div class="form-toggle" data-action="toggle-separate-lock-pin">
            <span class="toggle-label">Separate PIN for Door Locks</span>
            <div class="toggle-switch ${user.has_separate_lock_pin ? 'active' : ''}" data-field="has_separate_lock_pin">
              <div class="toggle-knob"></div>
            </div>
          </div>
          <div style="font-size: 12px; color: var(--secondary-text-color); margin-top: 4px;">
            Enable this if you want different PINs for the alarm vs door locks
          </div>
        </div>

        ${user.has_separate_lock_pin ? `
          <div class="form-group">
            <label class="form-label">Lock PIN (6-8 digits)</label>
            <div style="display: flex; gap: 8px; align-items: center;">
              <input type="${user._showLockPin ? 'text' : 'password'}" 
                     class="form-input" 
                     data-field="lock_pin" 
                     value="${user._retrievedLockPin || ''}" 
                     placeholder="Enter lock PIN or retrieve from lock"
                     style="flex: 1;">
              ${user._retrievedLockPin ? `
                <button class="toggle-pin-btn" data-action="toggle-lock-pin-visibility" 
                        style="padding: 12px; background: var(--secondary-background-color); border: 1px solid var(--divider-color); border-radius: 8px; cursor: pointer; min-width: 48px;">
                  ${user._showLockPin ? '👁️' : '👁️‍🗨️'}
                </button>
              ` : ''}
              <button class="btn btn-secondary" data-action="retrieve-lock-pin" data-user-id="${user.id}"
                      style="padding: 12px 16px; font-size: 13px; white-space: nowrap;"
                      ${user._retrievingLockPin || !user.slot_number ? 'disabled' : ''}>
                ${user._retrievingLockPin ? '⏳ Loading...' : '🔄 Retrieve'}
              </button>
            </div>
            ${user._lockPinRetrieveError ? `
              <div style="color: #ef4444; font-size: 12px; margin-top: 4px;">
                ❌ ${user._lockPinRetrieveError}
              </div>
            ` : ''}
            <div style="font-size: 12px; color: var(--secondary-text-color); margin-top: 4px;">
              ${user._retrievedLockPin ? 'Lock PIN retrieved. Modify or leave as-is.' : 
                'This PIN will work on all enabled door locks. Click Retrieve to load from lock.'}
            </div>
          </div>
        ` : ''}

        ${user.slot_number ? `
          <div style="padding: 12px; background: var(--secondary-background-color); border-radius: 8px; margin-bottom: 16px;">
            <div style="font-size: 12px; color: var(--secondary-text-color); margin-bottom: 4px;">Lock Slot Assignment</div>
            <div style="font-size: 16px; font-weight: 600; color: var(--primary-text-color);">Slot ${user.slot_number}</div>
            <div style="font-size: 11px; color: var(--disabled-text-color); margin-top: 2px;">Assigned across all door locks</div>
          </div>

          <div class="form-group">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
              <label class="form-label" style="margin: 0;">Per-Lock Access Control</label>
              <div style="display: flex; gap: 8px;">
                <button class="btn btn-secondary" data-action="verify-locks" data-user-id="${user.id}" 
                        style="padding: 8px 16px; font-size: 13px;"
                        ${user._verifyingLocks ? 'disabled' : ''}>
                  ${user._verifyingLocks ? '⏳ Verifying...' : '🔍 Verify Status'}
                </button>
                <button class="btn btn-secondary" data-action="sync-to-new-locks" data-user-id="${user.id}" 
                        style="padding: 8px 16px; font-size: 13px;">
                  <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="display: inline; margin-right: 4px;">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
                  </svg>
                  Sync to New
                </button>
              </div>
            </div>
            ${user._verifyMessage ? `
              <div style="padding: 8px 12px; background: ${user._verifySuccess ? '#10b981' : '#ef4444'}20; border-radius: 6px; margin-bottom: 12px; font-size: 12px; color: ${user._verifySuccess ? '#10b981' : '#ef4444'};">
                ${user._verifyMessage}
              </div>
            ` : ''}
            <div style="font-size: 12px; color: var(--disabled-text-color); margin-bottom: 12px;">
              ℹ️ Toggles show intended state from database. Click "Verify Status" to check actual lock state.
            </div>
            ${this.renderLockAccessList(user)}
          </div>
        ` : ''}

        <div class="form-actions">
          <button class="btn btn-secondary" data-action="back-to-list">Cancel</button>
          <button class="btn btn-danger" data-action="delete-user" data-user-id="${user.id}">Delete User</button>
          <button class="btn btn-primary" data-action="save-user" data-user-id="${user.id}">Save Changes</button>
        </div>
      </div>
    `;
  }

  renderLockAccessList(user) {
    // Get locks from container-cached list (populated by loadLocks())
    // Falls back to reading lock.* from HA states if container list not yet loaded
    const allLocks = (this._locks || []).length > 0
      ? this._locks
      : Object.keys(this._hass.states)
          .filter(id => id.startsWith('lock.'))
          .map(id => ({
            entity_id: id,
            name: this._hass.states[id].attributes.friendly_name || id,
            state: this._hass.states[id].state
          }));

    if (allLocks.length === 0) {
      return `<div style="color: var(--secondary-text-color); font-size: 13px; padding: 12px; background: var(--card-background-color); border-radius: 8px;">No locks found in your system.</div>`;
    }

    const lockAccess = user._lockAccess || {};

    return allLocks.map(lock => {
      const access = lockAccess[lock.entity_id] || {};
      const isEnabled = access.enabled || false;
      const isSyncing = user._lockSyncing && user._lockSyncing[lock.entity_id];
      const lastSynced = access.last_synced;
      const lastSuccess = access.last_sync_success !== false;
      const syncError = access.last_sync_error;
      
      // Format timestamp
      const syncTime = lastSynced ? this.getTimeAgo(new Date(lastSynced)) : 'Never';
      
      return `
        <div class="lock-item" style="display: flex; flex-direction: column; gap: 8px; padding: 12px; background: var(--card-background-color); border-radius: 8px; margin-bottom: 8px; border: 1px solid var(--divider-color);">
          <div style="display: flex; align-items: center; justify-content: space-between;">
            <div style="display: flex; align-items: center; gap: 12px; flex: 1;">
              <div style="font-size: 24px;">
                ${lock.state === 'locked' ? '🔒' : '🔓'}
              </div>
              <div style="flex: 1;">
                <div style="font-size: 14px; font-weight: 500; color: var(--primary-text-color);">
                  ${lock.name}
                  ${isSyncing ? ' <span style="font-size: 16px;">⏳</span>' : ''}
                  ${!lastSuccess && lastSynced ? ' <span style="font-size: 16px;">⚠️</span>' : ''}
                </div>
                <div style="font-size: 12px; color: var(--secondary-text-color); margin-top: 2px;">
                  ${lock.entity_id}
                </div>
              </div>
            </div>
            <div class="form-toggle" data-action="toggle-lock-access" data-lock="${lock.entity_id}" ${isSyncing ? 'style="opacity: 0.5; pointer-events: none;"' : ''}>
              <div class="toggle-switch ${isEnabled ? 'active' : ''}" data-field="lock-access">
                <div class="toggle-knob"></div>
              </div>
            </div>
          </div>
          <div style="font-size: 11px; color: var(--disabled-text-color); display: flex; justify-content: space-between;">
            <span>Last synced: ${syncTime}</span>
            ${lastSynced && !lastSuccess ? `<span style="color: #ef4444;">Sync failed: ${syncError || 'Unknown error'}</span>` : 
              lastSynced && lastSuccess ? `<span style="color: #10b981;">✓ Synced successfully</span>` : ''}
          </div>
        </div>
      `;
    }).join('');
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

  async loadUserLockAccess(userId) {
    if (!this._selectedUser || this._selectedUser.id !== userId) return;
    this._selectedUser._lockAccessLoading = true;
    try {
      const data = await this._apiFetch(`/api/locks/users/${userId}`);
      // data.lock_access is an object keyed by entity_id
      if (this._selectedUser && this._selectedUser.id === userId) {
        this._selectedUser._lockAccess = data.lock_access || {};
        this._selectedUser._lockAccessLoading = false;
        this.render();
      }
    } catch (e) {
      console.error('Failed to load lock access:', e);
      if (this._selectedUser && this._selectedUser.id === userId) {
        this._selectedUser._lockAccessLoading = false;
        this._selectedUser._lockAccess = {};
        this.render();
      }
    }
  }

  async loadUserPin(userId) {
    // PINs are bcrypt-hashed in the container database and cannot be retrieved.
    // This method is intentionally a no-op in v2.0.
    console.log('loadUserPin: PIN retrieval not supported (bcrypt hashed)');
    if (this._selectedUser && this._selectedUser.id === userId) {
      this._selectedUser._pinLoading = false;
      this._selectedUser._pinFailed = true;
      this._selectedUser._actualPin = '';
    }
  }

  renderUserAdd() {
    return `
      <div class="user-detail">
        <button class="back-btn" data-action="back-to-list">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
          </svg>
          Back to Users
        </button>

        <div class="form-group">
          <label class="form-label">Name *</label>
          <input type="text" class="form-input" id="name-input" data-field="name" value="${this._editingUser.name || ''}" placeholder="Enter user name">
          <div class="field-error" id="name-error">Name is required</div>
        </div>

        <div class="form-group">
          <label class="form-label">Alarm PIN (6-8 digits) *</label>
          <input type="password" class="form-input" id="pin-input" data-field="pin" value="${this._editingUser.pin || ''}" placeholder="Enter PIN for arming/disarming" minlength="6" maxlength="8">
          <div class="field-error" id="pin-error">PIN must be 6-8 digits</div>
          <div style="font-size: 12px; color: var(--secondary-text-color); margin-top: 4px;">
            This PIN is used for arming/disarming the alarm system
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">Phone Number</label>
          <input type="tel" class="form-input" data-field="phone" value="${this._editingUser.phone || ''}" placeholder="+1234567890">
        </div>

        <div class="form-group">
          <label class="form-label">Email</label>
          <input type="email" class="form-input" data-field="email" value="${this._editingUser.email || ''}" placeholder="user@example.com">
        </div>

        <div class="form-group">
          <div class="form-toggle" data-action="toggle-admin">
            <span class="toggle-label">Administrator</span>
            <div class="toggle-switch ${this._editingUser.is_admin ? 'active' : ''}" data-field="is_admin">
              <div class="toggle-knob"></div>
            </div>
          </div>
        </div>

        <div class="form-group">
          <div class="form-toggle" data-action="toggle-separate-lock-pin">
            <span class="toggle-label">Separate PIN for Door Locks</span>
            <div class="toggle-switch ${this._editingUser.has_separate_lock_pin ? 'active' : ''}" data-field="has_separate_lock_pin">
              <div class="toggle-knob"></div>
            </div>
          </div>
          <div style="font-size: 12px; color: var(--secondary-text-color); margin-top: 4px;">
            Enable this if you want different PINs for the alarm vs door locks
          </div>
        </div>

        ${this._editingUser.has_separate_lock_pin ? `
          <div class="form-group">
            <label class="form-label">Lock PIN (6-8 digits) *</label>
            <input type="password" class="form-input" id="lock-pin-input" data-field="lock_pin" value="${this._editingUser.lock_pin || ''}" placeholder="Enter PIN for all door locks" minlength="6" maxlength="8">
            <div class="field-error" id="lock-pin-error">Lock PIN must be 6-8 digits</div>
            <div style="font-size: 12px; color: var(--secondary-text-color); margin-top: 4px;">
              This PIN will work on all door locks
            </div>
          </div>
        ` : ''}

        <div class="form-actions">
          <button class="btn btn-secondary" data-action="back-to-list">Cancel</button>
          <button class="btn btn-primary" data-action="create-user">Create User</button>
        </div>
      </div>
    `;
  }

  renderEventsTab() {
    // Load events if not already loaded
    if (!this._eventsLoaded) {
      this.loadEvents();
      this.loadEventTypes();
      this.loadEventStats();
      this._eventsLoaded = true;
    }

    return `
      <div style="max-width: 1200px; margin: 0 auto;">
        <h3 style="margin-bottom: 24px; color: var(--primary-text-color);">Event Log</h3>
        
        ${this.renderEventStats()}
        
        <div style="background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: 12px; padding: 20px; margin-bottom: 24px;">
          <h4 style="margin-top: 0; margin-bottom: 16px;">Filters</h4>
          
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px;">
            <div>
              <label class="form-label">Event Type</label>
              <select id="event-type-filter" class="form-input" multiple style="height: 120px;">
                <option value="">All Events</option>
                ${this._eventTypes.map(type => `
                  <option value="${type}" ${this._eventFilters.eventTypes.includes(type) ? 'selected' : ''}>
                    ${this.formatEventType(type)}
                  </option>
                `).join('')}
              </select>
            </div>
            
            <div>
              <label class="form-label">Time Range</label>
              <select id="days-filter" class="form-input">
                <option value="1" ${this._eventFilters.days === 1 ? 'selected' : ''}>Last 24 Hours</option>
                <option value="3" ${this._eventFilters.days === 3 ? 'selected' : ''}>Last 3 Days</option>
                <option value="7" ${this._eventFilters.days === 7 ? 'selected' : ''}>Last 7 Days</option>
                <option value="14" ${this._eventFilters.days === 14 ? 'selected' : ''}>Last 2 Weeks</option>
                <option value="30" ${this._eventFilters.days === 30 ? 'selected' : ''}>Last 30 Days</option>
              </select>
            </div>
            
            <div style="display: flex; align-items: flex-end;">
              <button class="btn btn-primary" data-action="apply-event-filters" style="width: 100%;">
                Apply Filters
              </button>
            </div>
          </div>
        </div>
        
        <div style="background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: 12px; padding: 20px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
            <h4 style="margin: 0;">Recent Events (${this._events.length})</h4>
            <button class="btn btn-secondary" data-action="refresh-events" style="padding: 8px 16px; font-size: 13px;">
              🔄 Refresh
            </button>
          </div>
          
          ${this._events.length === 0 ? this.renderNoEvents() : this.renderEventsList()}
        </div>
      </div>
    `;
  }

  renderEventStats() {
    if (!this._eventStats) {
      return `<div style="margin-bottom: 24px;">Loading statistics...</div>`;
    }

    const stats = this._eventStats;
    const topEvents = Object.entries(stats.by_type || {})
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5);

    return `
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px;">
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border-radius: 12px; padding: 20px;">
          <div style="font-size: 14px; opacity: 0.9; margin-bottom: 8px;">Total Events</div>
          <div style="font-size: 32px; font-weight: 700;">${stats.total_events || 0}</div>
          <div style="font-size: 12px; opacity: 0.8; margin-top: 4px;">Last ${stats.period_days} days</div>
        </div>
        
        ${topEvents.map(([type, count], index) => {
          const colors = [
            ['#10b981', '#059669'],
            ['#3b82f6', '#2563eb'],
            ['#f59e0b', '#d97706'],
            ['#ef4444', '#dc2626'],
            ['#8b5cf6', '#7c3aed']
          ];
          const [color1, color2] = colors[index] || colors[0];
          
          return `
            <div style="background: linear-gradient(135deg, ${color1} 0%, ${color2} 100%); color: white; border-radius: 12px; padding: 20px;">
              <div style="font-size: 14px; opacity: 0.9; margin-bottom: 8px;">${this.formatEventType(type)}</div>
              <div style="font-size: 32px; font-weight: 700;">${count}</div>
              <div style="font-size: 12px; opacity: 0.8; margin-top: 4px;">${((count / stats.total_events) * 100).toFixed(1)}%</div>
            </div>
          `;
        }).join('')}
      </div>
    `;
  }

  renderNoEvents() {
    return `
      <div style="text-align: center; padding: 60px 20px; color: var(--secondary-text-color);">
        <svg width="64" height="64" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="margin: 0 auto 16px; opacity: 0.5;">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
        </svg>
        <div style="font-size: 18px; font-weight: 600; margin-bottom: 8px;">No Events Found</div>
        <div style="font-size: 14px;">Try adjusting your filters or check back later</div>
      </div>
    `;
  }

  renderEventsList() {
    return `
      <div style="max-height: 600px; overflow-y: auto;">
        ${this._events.map(event => this.renderEventItem(event)).join('')}
      </div>
    `;
  }

  renderEventItem(event) {
    const timestamp = new Date(event.timestamp);
    const timeAgo = this.getTimeAgo(timestamp);
    const details = event.details || {};
    
    const eventConfig = {
      'door_locked': { icon: '🔒', color: '#10b981', label: 'Door Locked' },
      'door_unlocked': { icon: '🔓', color: '#f59e0b', label: 'Door Unlocked' },
      'garage_opened': { icon: '⬆️', color: '#ef4444', label: 'Garage Opened' },
      'garage_closed': { icon: '⬇️', color: '#10b981', label: 'Garage Closed' },
      'garage_opening': { icon: '↗️', color: '#f59e0b', label: 'Garage Opening' },
      'garage_closing': { icon: '↘️', color: '#f59e0b', label: 'Garage Closing' },
      'alarm_armed': { icon: '🛡️', color: '#3b82f6', label: 'Alarm Armed' },
      'alarm_disarmed': { icon: '✅', color: '#10b981', label: 'Alarm Disarmed' },
      'alarm_triggered': { icon: '🚨', color: '#ef4444', label: 'Alarm Triggered' },
      'state_change': { icon: '🔄', color: '#6b7280', label: 'State Change' },
      'user_added': { icon: '➕', color: '#10b981', label: 'User Added' },
      'user_deleted': { icon: '➖', color: '#ef4444', label: 'User Deleted' },
    };
    
    const config = eventConfig[event.event_type] || { 
      icon: '📋', 
      color: '#6b7280', 
      label: this.formatEventType(event.event_type) 
    };
    
    const entityName = details.entity_name || event.zone_entity_id || 'Unknown';
    const userName = event.user_name || 'System';
    
    return `
      <div style="display: flex; gap: 16px; padding: 16px; border-bottom: 1px solid var(--divider-color); align-items: flex-start;">
        <div style="font-size: 32px; flex-shrink: 0;">${config.icon}</div>
        
        <div style="flex: 1;">
          <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 4px;">
            <div style="font-size: 15px; font-weight: 600; color: var(--primary-text-color);">
              ${config.label}
            </div>
            <div style="font-size: 12px; color: var(--disabled-text-color);">
              ${timeAgo}
            </div>
          </div>
          
          <div style="font-size: 13px; color: var(--secondary-text-color); margin-bottom: 8px;">
            ${entityName}
            ${event.user_name ? `<span style="color: ${config.color}; font-weight: 500;"> • ${userName}</span>` : ''}
          </div>
          
          ${details.previous_state && details.new_state ? `
            <div style="display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--disabled-text-color);">
              <span style="background: var(--secondary-background-color); padding: 4px 8px; border-radius: 4px;">
                ${details.previous_state}
              </span>
              <span>→</span>
              <span style="background: ${config.color}20; color: ${config.color}; padding: 4px 8px; border-radius: 4px; font-weight: 500;">
                ${details.new_state}
              </span>
            </div>
          ` : ''}
          
          <div style="font-size: 11px; color: var(--disabled-text-color); margin-top: 4px;">
            ${timestamp.toLocaleString()}
          </div>
        </div>
      </div>
    `;
  }

  formatEventType(type) {
    return type
      .split('_')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  }

  async loadEvents() {
    try {
      const params = new URLSearchParams({ limit: 100, days: this._eventFilters.days });
      if (this._eventFilters.eventTypes.length > 0)
        params.set('event_types', this._eventFilters.eventTypes.join(','));
      const data = await this._apiFetch(`/api/logs?${params}`);
      this._events = data.events || data || [];
      this.render();
    } catch (e) {
      console.error('Failed to load events:', e);
      this._events = [];
    }
  }

  async loadEventTypes() {
    try {
      const data = await this._apiFetch('/api/logs?limit=500');
      const events = data.events || data || [];
      this._eventTypes = [...new Set(events.map(e => e.event_type).filter(Boolean))];
    } catch (e) {
      console.error('Failed to load event types:', e);
      this._eventTypes = [];
    }
  }

  async loadEventStats() {
    try {
      const params = new URLSearchParams({ limit: 500, days: this._eventFilters.days });
      const data = await this._apiFetch(`/api/logs?${params}`);
      const events = data.events || data || [];
      // Build stats summary from raw events
      const typeCounts = {};
      events.forEach(e => { typeCounts[e.event_type] = (typeCounts[e.event_type] || 0) + 1; });
      this._eventStats = { total: events.length, by_type: typeCounts };
      this.render();
    } catch (e) {
      console.error('Failed to load event stats:', e);
    }
  }

  async loadLocks() {
    try {
      const data = await this._apiFetch('/api/locks');
      this._locks = (data.locks || []).map(l => ({
        entity_id: l.entity_id,
        name: l.name || l.entity_id,
        state: l.state || 'unknown'
      }));
    } catch (e) {
      console.error('Failed to load locks:', e);
      this._locks = [];
    }
  }

  renderDevicesTab() {
    return `
      <div class="empty-state">
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
        </svg>
        <div class="empty-state-title">Devices Coming Soon</div>
        <div class="empty-state-text">Device management will be available in a future update</div>
      </div>
    `;
  }

  renderSecurityTab() {
    if (!this._config && !this._configLoading) {
      this.loadConfig();
    }
    if (this._configLoading) {
      return `<div style="padding: 40px; text-align: center; color: var(--secondary-text-color);">Loading settings…</div>`;
    }

    const c = this._config || {};
    const maxAttempts   = c.max_failed_attempts ?? 5;
    const lockoutMins   = Math.round((c.lockout_duration ?? 300) / 60);
    const autoAction    = c.alarm_auto_action ?? 'none';
    const requirePin    = Boolean(c.require_pin_to_arm);

    return `
      <div style="max-width: 800px; margin: 0 auto;">
        <h3 style="margin-bottom: 8px; color: var(--primary-text-color);">Security Settings</h3>
        <p style="margin-top: 0; margin-bottom: 28px; font-size: 14px; color: var(--secondary-text-color);">
          These settings control lockout behaviour, alarm response, and arming restrictions.
        </p>

        <!-- ── PIN Lockout ───────────────────────────────────────────── -->
        <div style="background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: 14px; padding: 24px; margin-bottom: 20px;">
          <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 18px;">
            <span style="font-size: 22px;">🔐</span>
            <div>
              <div style="font-size: 16px; font-weight: 600; color: var(--primary-text-color);">PIN Lockout</div>
              <div style="font-size: 13px; color: var(--secondary-text-color);">Limit brute-force attempts on the keypad</div>
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">Failed attempts before lockout</label>
            <div style="display: flex; align-items: center; gap: 12px;">
              <input type="number" id="max-failed-attempts" class="form-input"
                     value="${maxAttempts}" min="3" max="20" style="max-width: 110px;">
              <span style="color: var(--secondary-text-color); font-size: 14px;">attempts</span>
            </div>
            <div style="font-size: 12px; color: var(--secondary-text-color); margin-top: 6px;">
              After this many wrong PINs the keypad locks out for the duration below. Range: 3–20.
            </div>
          </div>

          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label">Lockout duration</label>
            <div style="display: flex; align-items: center; gap: 12px;">
              <input type="number" id="lockout-duration" class="form-input"
                     value="${lockoutMins}" min="1" max="60" style="max-width: 110px;">
              <span style="color: var(--secondary-text-color); font-size: 14px;">minutes</span>
            </div>
            <div style="font-size: 12px; color: var(--secondary-text-color); margin-top: 6px;">
              How long the keypad stays locked after too many failed attempts. Range: 1–60 minutes.
            </div>
          </div>
        </div>

        <!-- ── Post-Alarm Action ─────────────────────────────────────── -->
        <div style="background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: 14px; padding: 24px; margin-bottom: 20px;">
          <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 18px;">
            <span style="font-size: 22px;">🚨</span>
            <div>
              <div style="font-size: 16px; font-weight: 600; color: var(--primary-text-color);">Post-Alarm Behaviour</div>
              <div style="font-size: 13px; color: var(--secondary-text-color);">What happens automatically after the alarm siren duration ends</div>
            </div>
          </div>

          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label">After alarm duration expires</label>
            <div style="display: flex; flex-direction: column; gap: 10px; margin-top: 4px;">
              ${[
                { val: 'none',   icon: '🔴', title: 'Stay triggered',
                  desc: 'Alarm stays active until someone manually disarms it. Best for monitored systems.' },
                { val: 'disarm', icon: '✅', title: 'Auto-disarm',
                  desc: 'System disarms itself after the siren finishes. Convenient for self-monitored homes.' },
                { val: 'rearm',  icon: '🔄', title: 'Auto-rearm',
                  desc: 'System returns to the armed mode it was in before the alarm. Strongest protection.' },
              ].map(opt => `
                <label style="
                  display: flex; align-items: flex-start; gap: 14px; padding: 14px 16px;
                  border: 2px solid ${autoAction === opt.val ? '#667eea' : 'var(--divider-color)'};
                  border-radius: 10px; cursor: pointer;
                  background: ${autoAction === opt.val ? 'rgba(102,126,234,0.06)' : 'transparent'};
                  transition: border-color 0.2s, background 0.2s;
                ">
                  <input type="radio" name="alarm-auto-action" value="${opt.val}"
                         ${autoAction === opt.val ? 'checked' : ''}
                         style="margin-top: 3px; accent-color: #667eea; flex-shrink: 0;">
                  <div>
                    <div style="font-size: 14px; font-weight: 600; color: var(--primary-text-color);">
                      ${opt.icon}&nbsp; ${opt.title}
                    </div>
                    <div style="font-size: 12px; color: var(--secondary-text-color); margin-top: 3px;">
                      ${opt.desc}
                    </div>
                  </div>
                </label>
              `).join('')}
            </div>
            <div style="margin-top: 10px; padding: 10px 14px; background: rgba(245,158,11,0.08);
                        border-left: 3px solid #f59e0b; border-radius: 6px; font-size: 12px;
                        color: var(--secondary-text-color); line-height: 1.5;">
              ⚠️ <strong>Alarm duration</strong> is set in the <em>General</em> tab. This setting
              controls what happens after that duration — not during the siren.
            </div>
          </div>
        </div>

        <!-- ── Arming Restriction ────────────────────────────────────── -->
        <div style="background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: 14px; padding: 24px; margin-bottom: 28px;">
          <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 18px;">
            <span style="font-size: 22px;">🛡️</span>
            <div>
              <div style="font-size: 16px; font-weight: 600; color: var(--primary-text-color);">Arming Restriction</div>
              <div style="font-size: 13px; color: var(--secondary-text-color);">Control whether a PIN is required to arm</div>
            </div>
          </div>

          <div class="form-group" style="margin-bottom: 0;">
            <div class="form-toggle" data-action="toggle-require-pin-to-arm" style="cursor: pointer;">
              <div>
                <div class="toggle-label">Require PIN to arm</div>
                <div style="font-size: 12px; color: var(--secondary-text-color); margin-top: 3px;">
                  When off, anyone can arm without a PIN. When on, a valid user PIN is always required.
                </div>
              </div>
              <div class="toggle-switch ${requirePin ? 'active' : ''}" id="require-pin-toggle" style="flex-shrink: 0; margin-left: 16px;">
                <div class="toggle-knob"></div>
              </div>
            </div>
          </div>
        </div>

        <div style="display: flex; justify-content: flex-end;">
          <button class="btn btn-primary" data-action="save-security-settings"
                  style="min-width: 160px; padding: 14px 24px;">
            Save Security Settings
          </button>
        </div>
      </div>
    `;
  }

  renderGeneralTab() {
    if (!this._config && !this._configLoading) {
      this.loadConfig();
    }
    if (this._configLoading) {
      return `<div style="padding: 40px; text-align: center; color: var(--secondary-text-color);">Loading settings…</div>`;
    }

    const c = this._config || {};
    const entryDelay      = c.entry_delay      ?? 30;
    const exitDelay       = c.exit_delay       ?? 60;
    const alarmDuration   = c.alarm_duration   ?? 300;
    const lockSyncMins    = Math.round((c.lock_sync_interval ?? 3600) / 60);
    const logRetentionDays = c.log_retention_days ?? 90;

    return `
      <div style="max-width: 800px; margin: 0 auto;">
        <h3 style="margin-bottom: 8px; color: var(--primary-text-color);">General Settings</h3>
        <p style="margin-top: 0; margin-bottom: 28px; font-size: 14px; color: var(--secondary-text-color);">
          Alarm timing, lock behaviour, and system maintenance settings.
        </p>

        <!-- ── Alarm Timing ──────────────────────────────────────────── -->
        <div style="background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: 14px; padding: 24px; margin-bottom: 20px;">
          <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 18px;">
            <span style="font-size: 22px;">⏱️</span>
            <div>
              <div style="font-size: 16px; font-weight: 600; color: var(--primary-text-color);">Alarm Timing</div>
              <div style="font-size: 13px; color: var(--secondary-text-color);">Delay and duration values for the alarm state machine</div>
            </div>
          </div>

          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px;">

            <div class="form-group" style="margin-bottom: 0;">
              <label class="form-label">Entry delay</label>
              <div style="display: flex; align-items: center; gap: 10px;">
                <input type="number" id="entry-delay" class="form-input"
                       value="${entryDelay}" min="0" max="300" style="max-width: 110px;">
                <span style="color: var(--secondary-text-color); font-size: 14px;">seconds</span>
              </div>
              <div style="font-size: 12px; color: var(--secondary-text-color); margin-top: 6px;">
                How long you have to disarm after opening an entry zone. 0 = instant trigger.
              </div>
            </div>

            <div class="form-group" style="margin-bottom: 0;">
              <label class="form-label">Exit delay</label>
              <div style="display: flex; align-items: center; gap: 10px;">
                <input type="number" id="exit-delay" class="form-input"
                       value="${exitDelay}" min="0" max="300" style="max-width: 110px;">
                <span style="color: var(--secondary-text-color); font-size: 14px;">seconds</span>
              </div>
              <div style="font-size: 12px; color: var(--secondary-text-color); margin-top: 6px;">
                How long you have to leave after arming away before the system is fully armed.
              </div>
            </div>

            <div class="form-group" style="margin-bottom: 0;">
              <label class="form-label">Alarm siren duration</label>
              <div style="display: flex; align-items: center; gap: 10px;">
                <input type="number" id="alarm-duration" class="form-input"
                       value="${alarmDuration}" min="30" max="3600" style="max-width: 110px;">
                <span style="color: var(--secondary-text-color); font-size: 14px;">seconds</span>
              </div>
              <div style="font-size: 12px; color: var(--secondary-text-color); margin-top: 6px;">
                How long the alarm stays in triggered state before the post-alarm action runs.
                Min 30 s, max 60 min.
              </div>
            </div>

          </div>

          <div style="margin-top: 18px; display: flex; justify-content: flex-end;">
            <button class="btn btn-primary" data-action="save-timing-settings" style="min-width: 160px;">
              Save Timing
            </button>
          </div>
        </div>

        <!-- ── Lock Sync ─────────────────────────────────────────────── -->
        <div style="background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: 14px; padding: 24px; margin-bottom: 20px;">
          <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 18px;">
            <span style="font-size: 22px;">🔒</span>
            <div>
              <div style="font-size: 16px; font-weight: 600; color: var(--primary-text-color);">Lock Sync Interval</div>
              <div style="font-size: 13px; color: var(--secondary-text-color);">How often to verify Z-Wave lock codes against the database</div>
            </div>
          </div>

          <div class="form-group" style="margin-bottom: 4px;">
            <div style="display: flex; align-items: center; gap: 12px;">
              <input type="number" id="lock-sync-interval" class="form-input"
                     value="${lockSyncMins}" min="1" max="1440" style="max-width: 110px;">
              <span style="color: var(--secondary-text-color); font-size: 14px;">minutes</span>
              <button class="btn btn-primary" data-action="save-lock-sync-interval"
                      style="margin-left: auto; min-width: 140px;">
                Save Interval
              </button>
            </div>
            <div style="font-size: 12px; color: var(--secondary-text-color); margin-top: 8px; line-height: 1.6;">
              Shorter (15–30 min) = more accurate, more Z-Wave traffic.
              Longer (2–4 h) = less traffic, may be stale. Battery locks: use longer intervals.
              <br><strong>Current:</strong> ${lockSyncMins} min (${c.lock_sync_interval ?? 3600} s)
            </div>
          </div>
        </div>

        <!-- ── Log Retention ─────────────────────────────────────────── -->
        <div style="background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: 14px; padding: 24px; margin-bottom: 28px;">
          <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 18px;">
            <span style="font-size: 22px;">📋</span>
            <div>
              <div style="font-size: 16px; font-weight: 600; color: var(--primary-text-color);">Event Log Retention</div>
              <div style="font-size: 13px; color: var(--secondary-text-color);">How long to keep event history before pruning</div>
            </div>
          </div>

          <div class="form-group" style="margin-bottom: 4px;">
            <div style="display: flex; align-items: center; gap: 12px;">
              <input type="number" id="log-retention-days" class="form-input"
                     value="${logRetentionDays}" min="7" max="365" style="max-width: 110px;">
              <span style="color: var(--secondary-text-color); font-size: 14px;">days</span>
              <button class="btn btn-primary" data-action="save-log-retention"
                      style="margin-left: auto; min-width: 140px;">
                Save Retention
              </button>
            </div>
            <div style="font-size: 12px; color: var(--secondary-text-color); margin-top: 8px; line-height: 1.6;">
              Events older than this are automatically deleted. A maximum of 10,000 events are always kept
              regardless of age. Range: 7–365 days.
            </div>
          </div>
        </div>

      </div>
    `;
  }

  async loadConfig() {
    this._configLoading = true;
    try {
      const data = await this._apiFetch('/api/config');
      this._config = data.config || data;
      this._configLoading = false;
      this.render();
    } catch (e) {
      console.error('Failed to load config:', e);
      this._configLoading = false;
      this._config = {};
      this.render();
    }
  }

  attachEventListeners() {
    // Bootstrap first-user creation
    this.shadowRoot.querySelectorAll('[data-action="bootstrap-create"]').forEach(el => {
      el.addEventListener('click', async () => {
        const bootstrapPin = this.shadowRoot.getElementById('bootstrap-pin')?.value || '';
        const name         = this.shadowRoot.getElementById('bootstrap-name')?.value.trim() || '';
        const newPin       = this.shadowRoot.getElementById('bootstrap-new-pin')?.value || '';
        const confirmPin   = this.shadowRoot.getElementById('bootstrap-confirm-pin')?.value || '';
        const errorEl      = this.shadowRoot.getElementById('bootstrap-error');

        const showErr = (msg) => {
          errorEl.textContent = msg;
          errorEl.style.display = 'block';
        };

        errorEl.style.display = 'none';

        if (!bootstrapPin) return showErr('Enter the bootstrap PIN from the addon logs.');
        if (!name)         return showErr('Name is required.');
        if (!newPin.match(/^\d{6,8}$/)) return showErr('Admin PIN must be 6–8 digits.');
        if (newPin !== confirmPin)       return showErr('PINs do not match.');

        try {
          const result = await this._apiPost('/api/users', {
            admin_pin: bootstrapPin,
            name:      name,
            pin:       newPin,
            is_admin:  true,
          });
          if (result.success) {
            this._bootstrapActive = false;
            this._adminPin = newPin;
            this._authenticated = true;
            this._usersLoaded = false;
            await this.loadUsers();
            await this.loadLocks();
            this.showNotification('Admin account created! Welcome to HomeSecure.', 'success');
            this.render();
          } else {
            showErr(result.message || 'Failed to create user. Check the bootstrap PIN.');
          }
        } catch (e) {
          showErr('Error: ' + e.message);
        }
      });
    });

    // Auth keypad
    this.shadowRoot.querySelectorAll('[data-action="auth-number"]').forEach(el => {
      el.addEventListener('click', () => {
        if (this._pin.length < 8) {
          this._pin += el.dataset.value;
          this.render();
        }
      });
    });

    this.shadowRoot.querySelectorAll('[data-action="auth-clear"]').forEach(el => {
      el.addEventListener('click', () => {
        this._pin = '';
        this.render();
      });
    });

    this.shadowRoot.querySelectorAll('[data-action="auth-submit"]').forEach(el => {
      el.addEventListener('click', () => {
        if (this._pin.length >= 6) {
          this.authenticateAdmin();
        }
      });
    });

    // Close button
    this.shadowRoot.querySelectorAll('[data-action="close"]').forEach(el => {
      el.addEventListener('click', () => {
        // Reset authentication when closing admin panel
        this._authenticated = false;
        this._pin = '';
        this._currentView = 'auth';
        this.dispatchEvent(new CustomEvent('close-admin'));
      });
    });

    // Tab switching
    this.shadowRoot.querySelectorAll('[data-action="switch-tab"]').forEach(el => {
      el.addEventListener('click', () => {
        this._currentTab = el.dataset.tab;
        this._currentView = 'main';
        this.render();
      });
    });

    // User list actions
    this.shadowRoot.querySelectorAll('[data-action="add-user"]').forEach(el => {
      el.addEventListener('click', () => {
        this._currentView = 'user-add';
        this._editingUser = {
          is_admin: false,
          has_separate_lock_pin: false
        };
        this.render();
      });
    });

    this.shadowRoot.querySelectorAll('[data-action="select-user"]').forEach(el => {
      el.addEventListener('click', () => {
        const userId = parseInt(el.dataset.userId);
        this._selectedUser = this._users.find(u => u.id === userId);
        this._currentView = 'user-detail';
        this.render();
      });
    });

    this.shadowRoot.querySelectorAll('[data-action="back-to-list"]').forEach(el => {
      el.addEventListener('click', () => {
        this._currentView = 'user-list';
        this._selectedUser = null;
        this._editingUser = {};
        this.render();
      });
    });

    // Toggle switches
    this.shadowRoot.querySelectorAll('[data-action="toggle-admin"]').forEach(el => {
      el.addEventListener('click', (e) => {
        const toggle = e.currentTarget.querySelector('.toggle-switch');
        const isActive = toggle.classList.contains('active');
        
        if (this._currentView === 'user-detail') {
          this._selectedUser.is_admin = !isActive;
        } else if (this._currentView === 'user-add') {
          this._editingUser.is_admin = !isActive;
        }
        this.render();
      });
    });

    this.shadowRoot.querySelectorAll('[data-action="toggle-separate-lock-pin"]').forEach(el => {
      el.addEventListener('click', (e) => {
        const toggle = e.currentTarget.querySelector('.toggle-switch');
        const isActive = toggle.classList.contains('active');
        
        if (this._currentView === 'user-detail') {
          this._selectedUser.has_separate_lock_pin = !isActive;
        } else if (this._currentView === 'user-add') {
          this._editingUser.has_separate_lock_pin = !isActive;
        }
        this.render();
      });
    });

    // Save lock sync interval
    this.shadowRoot.querySelectorAll('[data-action="save-lock-sync-interval"]').forEach(el => {
      el.addEventListener('click', async () => {
        const input = this.shadowRoot.getElementById('lock-sync-interval');
        if (!input) return;
        const minutes = parseInt(input.value);
        if (isNaN(minutes) || minutes < 1 || minutes > 1440) {
          this.showNotification('Please enter a value between 1 and 1440 minutes', 'error');
          return;
        }
        const seconds = minutes * 60;
        try {
          await this._apiPost('/api/config', { admin_pin: this._adminPin, lock_sync_interval: seconds });
          if (this._config) this._config.lock_sync_interval = seconds;
          this.showNotification(`Lock sync interval set to ${minutes} minutes`, 'success');
          this.render();
        } catch (e) {
          console.error('Failed to set sync interval:', e);
          this.showNotification('Failed to update sync interval', 'error');
        }
      });
    });

    // ── Save timing settings (entry/exit/alarm duration) ────────────────
    this.shadowRoot.querySelectorAll('[data-action="save-timing-settings"]').forEach(el => {
      el.addEventListener('click', async () => {
        const entryDelay    = parseInt(this.shadowRoot.getElementById('entry-delay')?.value);
        const exitDelay     = parseInt(this.shadowRoot.getElementById('exit-delay')?.value);
        const alarmDuration = parseInt(this.shadowRoot.getElementById('alarm-duration')?.value);

        if (isNaN(entryDelay)    || entryDelay    < 0   || entryDelay    > 300)  return this.showNotification('Entry delay must be 0–300 s', 'error');
        if (isNaN(exitDelay)     || exitDelay     < 0   || exitDelay     > 300)  return this.showNotification('Exit delay must be 0–300 s', 'error');
        if (isNaN(alarmDuration) || alarmDuration < 30  || alarmDuration > 3600) return this.showNotification('Alarm duration must be 30–3600 s', 'error');

        try {
          await this._apiPost('/api/config', {
            admin_pin:      this._adminPin,
            entry_delay:    entryDelay,
            exit_delay:     exitDelay,
            alarm_duration: alarmDuration,
          });
          if (this._config) {
            this._config.entry_delay    = entryDelay;
            this._config.exit_delay     = exitDelay;
            this._config.alarm_duration = alarmDuration;
          }
          this.showNotification('Timing settings saved', 'success');
          this.render();
        } catch (e) {
          console.error('Failed to save timing:', e);
          this.showNotification('Failed to save timing settings', 'error');
        }
      });
    });

    // ── Save log retention ───────────────────────────────────────────────
    this.shadowRoot.querySelectorAll('[data-action="save-log-retention"]').forEach(el => {
      el.addEventListener('click', async () => {
        const input = this.shadowRoot.getElementById('log-retention-days');
        if (!input) return;
        const days = parseInt(input.value);
        if (isNaN(days) || days < 7 || days > 365) {
          return this.showNotification('Retention must be 7–365 days', 'error');
        }
        try {
          await this._apiPost('/api/config', { admin_pin: this._adminPin, log_retention_days: days });
          if (this._config) this._config.log_retention_days = days;
          this.showNotification(`Event log will be kept for ${days} days`, 'success');
          this.render();
        } catch (e) {
          console.error('Failed to save log retention:', e);
          this.showNotification('Failed to save log retention', 'error');
        }
      });
    });

    // ── Save security settings ───────────────────────────────────────────
    this.shadowRoot.querySelectorAll('[data-action="save-security-settings"]').forEach(el => {
      el.addEventListener('click', async () => {
        const maxAttempts  = parseInt(this.shadowRoot.getElementById('max-failed-attempts')?.value);
        const lockoutMins  = parseInt(this.shadowRoot.getElementById('lockout-duration')?.value);
        const autoAction   = this.shadowRoot.querySelector('input[name="alarm-auto-action"]:checked')?.value;
        const requirePin   = Boolean(this._pendingRequirePin !== undefined
                               ? this._pendingRequirePin
                               : this._config?.require_pin_to_arm);

        if (isNaN(maxAttempts) || maxAttempts < 3 || maxAttempts > 20)
          return this.showNotification('Failed attempts must be 3–20', 'error');
        if (isNaN(lockoutMins) || lockoutMins < 1 || lockoutMins > 60)
          return this.showNotification('Lockout duration must be 1–60 minutes', 'error');
        if (!['none', 'disarm', 'rearm'].includes(autoAction))
          return this.showNotification('Please select a post-alarm action', 'error');

        try {
          await this._apiPost('/api/config', {
            admin_pin:            this._adminPin,
            max_failed_attempts:  maxAttempts,
            lockout_duration:     lockoutMins * 60,
            alarm_auto_action:    autoAction,
            require_pin_to_arm:   requirePin ? 1 : 0,
          });
          if (this._config) {
            this._config.max_failed_attempts = maxAttempts;
            this._config.lockout_duration    = lockoutMins * 60;
            this._config.alarm_auto_action   = autoAction;
            this._config.require_pin_to_arm  = requirePin ? 1 : 0;
          }
          this._pendingRequirePin = undefined;
          this.showNotification('Security settings saved', 'success');
          this.render();
        } catch (e) {
          console.error('Failed to save security settings:', e);
          this.showNotification('Failed to save security settings', 'error');
        }
      });
    });

    // ── Toggle: require PIN to arm ───────────────────────────────────────
    this.shadowRoot.querySelectorAll('[data-action="toggle-require-pin-to-arm"]').forEach(el => {
      el.addEventListener('click', () => {
        const toggle = this.shadowRoot.getElementById('require-pin-toggle');
        if (!toggle) return;
        const current = this._pendingRequirePin !== undefined
          ? this._pendingRequirePin
          : Boolean(this._config?.require_pin_to_arm);
        this._pendingRequirePin = !current;
        toggle.classList.toggle('active', this._pendingRequirePin);
        toggle.querySelector('.toggle-knob'); // force repaint handled by CSS
      });
    });

    // Form inputs - track changes WITHOUT re-rendering
    // Attach live PIN validation - called after every render
    this.attachPinValidation();

    this.shadowRoot.querySelectorAll('.form-input').forEach(el => {
      el.addEventListener('input', (e) => {
        const field = e.target.dataset.field;
        const value = e.target.value;
        
        if (this._currentView === 'user-detail' && this._selectedUser) {
          this._selectedUser[field] = value;
        } else if (this._currentView === 'user-add') {
          this._editingUser[field] = value;
        }
        // Don't render on every keystroke!
      });
    });

    // Save/Delete actions
    this.shadowRoot.querySelectorAll('[data-action="save-user"]').forEach(el => {
      el.addEventListener('click', () => {
        this.saveUser();
      });
    });

    this.shadowRoot.querySelectorAll('[data-action="delete-user"]').forEach(el => {
      el.addEventListener('click', () => {
        const userId = parseInt(el.dataset.userId);
        this.deleteUser(userId);
      });
    });

    this.shadowRoot.querySelectorAll('[data-action="create-user"]').forEach(el => {
      el.addEventListener('click', () => {
        this.createUser();
      });
    });

    // Toggle user enabled/disabled
    this.shadowRoot.querySelectorAll('[data-action="toggle-user-enabled"]').forEach(el => {
      el.addEventListener('click', async (e) => {
        e.stopPropagation();
        const userId = parseInt(el.dataset.userId);
        const user = this._users.find(u => u.id === userId);
        
        if (user) {
          try {
            await this._apiPost(`/api/users/${userId}`, {
              admin_pin: this._adminPin,
              enabled: !user.enabled
            });
            user.enabled = !user.enabled;
            this.render();
          } catch (e) {
            console.error('Failed to toggle user:', e);
          }
        }
      });
    });

    // Toggle PIN visibility (existing, but update for _retrievedPin)
    this.shadowRoot.querySelectorAll('[data-action="toggle-pin-visibility"]').forEach(el => {
      el.addEventListener('click', () => {
        if (this._selectedUser) {
          this._selectedUser._showPin = !this._selectedUser._showPin;
          this.render();
        }
      });
    });

    // Toggle Lock PIN visibility
    this.shadowRoot.querySelectorAll('[data-action="toggle-lock-pin-visibility"]').forEach(el => {
      el.addEventListener('click', () => {
        if (this._selectedUser) {
          this._selectedUser._showLockPin = !this._selectedUser._showLockPin;
          this.render();
        }
      });
    });

    // Verify locks button
    this.shadowRoot.querySelectorAll('[data-action="verify-locks"]').forEach(el => {
      el.addEventListener('click', async () => {
        const userId = parseInt(el.dataset.userId);
        
        if (this._selectedUser && this._selectedUser.id === userId) {
          this._selectedUser._verifyingLocks = true;
          this._selectedUser._verifyMessage = null;
          this.render();
          
          try {
            const result = await Promise.race([
              this._apiPost('/api/locks/sync', { admin_pin: this._adminPin, user_id: userId }),
              new Promise((_, reject) => setTimeout(() => reject(new Error('Timeout')), 15000))
            ]);
            
            if (this._selectedUser && this._selectedUser.id === userId) {
              this._selectedUser._verifyingLocks = false;
              
              if (result.success) {
                if (result.differences && result.differences.length > 0) {
                  this._selectedUser._verifyMessage = `✓ Verified. Found ${result.differences.length} difference(s) - database updated to match locks.`;
                  this._selectedUser._verifySuccess = true;
                } else {
                  this._selectedUser._verifyMessage = `✓ Verified. All locks match database (${result.verified_count}/${result.total_locks} checked).`;
                  this._selectedUser._verifySuccess = true;
                }
                
                // Reload lock access to show updated state
                await this.loadUserLockAccess(userId);
              } else {
                this._selectedUser._verifyMessage = `❌ Verification failed: ${result.message}`;
                this._selectedUser._verifySuccess = false;
              }
              
              // Clear message after 5 seconds
              setTimeout(() => {
                if (this._selectedUser && this._selectedUser.id === userId) {
                  this._selectedUser._verifyMessage = null;
                  this.render();
                }
              }, 5000);
              
              this.render();
            }
          } catch (e) {
            console.error('Failed to verify locks:', e);
            if (this._selectedUser && this._selectedUser.id === userId) {
              this._selectedUser._verifyingLocks = false;
              this._selectedUser._verifyMessage = '❌ Failed to verify locks';
              this._selectedUser._verifySuccess = false;
              this.render();
            }
          }
        }
      });
    });

    // Sync to new locks button (existing)
    this.shadowRoot.querySelectorAll('[data-action="sync-to-new-locks"]').forEach(el => {
      el.addEventListener('click', async () => {
        const userId = parseInt(el.dataset.userId);
        
        try {
          await this._apiPost('/api/locks/sync', { admin_pin: this._adminPin, user_id: userId });
          this.showNotification('Syncing to new locks...', 'info');
          setTimeout(() => {
            if (this._selectedUser && this._selectedUser.id === userId) {
              this.loadUserLockAccess(userId);
            }
          }, 3000);
        } catch (e) {
          console.error('Failed to sync to new locks:', e);
          this.showNotification('Failed to sync to new locks', 'error');
        }
      });
    });

    // Toggle lock access (updated for instant DB update)
    this.shadowRoot.querySelectorAll('[data-action="toggle-lock-access"]').forEach(el => {
      el.addEventListener('click', async (e) => {
        const lockEntityId = el.dataset.lock;
        const toggle = e.currentTarget.querySelector('.toggle-switch');
        const isEnabled = toggle.classList.contains('active');
        
        if (this._selectedUser) {
          // Update UI immediately (optimistic update)
          if (!this._selectedUser._lockAccess) {
            this._selectedUser._lockAccess = {};
          }
          if (!this._selectedUser._lockAccess[lockEntityId]) {
            this._selectedUser._lockAccess[lockEntityId] = {};
          }
          this._selectedUser._lockAccess[lockEntityId].enabled = !isEnabled;
          
          // Show syncing indicator
          if (!this._selectedUser._lockSyncing) {
            this._selectedUser._lockSyncing = {};
          }
          this._selectedUser._lockSyncing[lockEntityId] = true;
          
          this.render();
          
          try {
            await this._apiPost(`/api/locks/users/${this._selectedUser.id}/enable`, {
              lock_entity_id: lockEntityId,
              enabled: !isEnabled
            });
            
            // Wait a moment for background sync to complete
            await new Promise(resolve => setTimeout(resolve, 2000));
            
            // Reload lock access to get updated sync status
            await this.loadUserLockAccess(this._selectedUser.id);
            
            // Clear syncing indicator
            if (this._selectedUser._lockSyncing) {
              this._selectedUser._lockSyncing[lockEntityId] = false;
            }
            
            this.showNotification(
              `${!isEnabled ? 'Enabled' : 'Disabled'} access to lock`,
              'success'
            );
          } catch (e) {
            console.error('Failed to set lock access:', e);
            
            // Revert optimistic update on error
            if (this._selectedUser._lockAccess && this._selectedUser._lockAccess[lockEntityId]) {
              this._selectedUser._lockAccess[lockEntityId].enabled = isEnabled;
            }
            
            if (this._selectedUser._lockSyncing) {
              this._selectedUser._lockSyncing[lockEntityId] = false;
            }
            
            this.showNotification('Failed to update lock access', 'error');
            this.render();
          }
        }
      });
    });

    this.shadowRoot.querySelectorAll('[data-action="retrieve-pin"]').forEach(el => {
      el.addEventListener('click', () => {
        // PINs are bcrypt-hashed in v2.0 — cannot be retrieved from the container
        this.showNotification('PIN retrieval is not available — PINs are stored as one-way hashes', 'info');
      });
    });

    // Retrieve LOCK PIN button — reads directly from Z-Wave hardware
    this.shadowRoot.querySelectorAll('[data-action="retrieve-lock-pin"]').forEach(el => {
      el.addEventListener('click', async () => {
        if (!this._selectedUser) return;
        const userId = this._selectedUser.id;

        if (!this._selectedUser.slot_number) {
          this.showNotification('This user has no lock slot assigned yet — save the user first.', 'warning');
          return;
        }

        this._selectedUser._retrievingLockPin = true;
        this._selectedUser._lockPinRetrieveError = null;
        this.render();

        try {
          const data = await this._apiFetch(
            `/api/locks/users/${userId}/pin?admin_pin=${encodeURIComponent(this._adminPin)}`
          );
          if (data.success && data.pin) {
            this._selectedUser._retrievedLockPin = data.pin;
            this._selectedUser._retrievingLockPin = false;
            this.showNotification('Lock PIN retrieved from Z-Wave hardware.', 'success');
          } else {
            this._selectedUser._retrievingLockPin = false;
            this._selectedUser._lockPinRetrieveError =
              data.pin === null
                ? 'No PIN found in lock for this slot. The lock may be offline.'
                : (data.message || 'Could not retrieve PIN.');
          }
        } catch (e) {
          this._selectedUser._retrievingLockPin = false;
          this._selectedUser._lockPinRetrieveError = e.message;
        }
        this.render();
      });
    });

    // Event filters
    this.shadowRoot.querySelectorAll('[data-action="apply-event-filters"]').forEach(el => {
      el.addEventListener('click', () => {
        const typeSelect = this.shadowRoot.getElementById('event-type-filter');
        const daysSelect = this.shadowRoot.getElementById('days-filter');
        
        this._eventFilters.eventTypes = Array.from(typeSelect.selectedOptions)
          .map(opt => opt.value)
          .filter(v => v !== '');
        this._eventFilters.days = parseInt(daysSelect.value);
        
        this._eventsLoaded = false;
        this.render();
      });
    });

    this.shadowRoot.querySelectorAll('[data-action="refresh-events"]').forEach(el => {
      el.addEventListener('click', () => {
        this._eventsLoaded = false;
        this.render();
      });
    });

    // Tick the lockout countdown every second while locked out
    if (this._lockedUntil) {
      if (this._lockoutTimer) clearTimeout(this._lockoutTimer);
      if (new Date() < this._lockedUntil) {
        this._lockoutTimer = setTimeout(() => this.render(), 1000);
      } else {
        // Expired — clear and re-render to restore auth screen
        this._lockedUntil = null;
        this._failedAttempts = 0;
        this.saveLockoutState();
        this.render();
      }
    }
  }

  // ── Container API helpers ────────────────────────────────────────────────

  _authHeaders() {
    const h = { 'Content-Type': 'application/json' };
    if (this._apiToken) h['Authorization'] = `Bearer ${this._apiToken}`;
    return h;
  }

  async _apiFetch(path) {
    const resp = await fetch(this._apiUrl + path, { headers: this._authHeaders() });
    if (!resp.ok) throw new Error(`API ${resp.status}: ${await resp.text()}`);
    return resp.json();
  }

  async _apiPost(path, body) {
    const resp = await fetch(this._apiUrl + path, {
      method: 'POST', headers: this._authHeaders(), body: JSON.stringify(body)
    });
    if (!resp.ok) throw new Error(`API ${resp.status}: ${await resp.text()}`);
    return resp.json();
  }

  async _apiPut(path, body) {
    const resp = await fetch(this._apiUrl + path, {
      method: 'PUT', headers: this._authHeaders(), body: JSON.stringify(body)
    });
    if (!resp.ok) throw new Error(`API ${resp.status}: ${await resp.text()}`);
    return resp.json();
  }

  async _apiDelete(path, body) {
    const resp = await fetch(this._apiUrl + path, {
      method: 'DELETE', headers: this._authHeaders(), body: JSON.stringify(body)
    });
    if (!resp.ok) throw new Error(`API ${resp.status}: ${await resp.text()}`);
    return resp.json();
  }

  disconnectedCallback() {
    // Clean up timer when element is removed
    if (this._lockoutTimer) {
      clearTimeout(this._lockoutTimer);
      this._lockoutTimer = null;
    }
  }

  async authenticateAdmin() {
    try {
      // POST /api/auth validates the PIN without side effects
      const data = await this._apiPost('/api/auth', { pin: this._pin });
      if (!data.success || !data.is_admin) {
        throw new Error(data.error || 'Not an admin');
      }
      // If we get here the PIN is valid and admin
      this._authenticated = true;
      this._usersLoaded = false;
      this._failedAttempts = 0;
      this._lockedUntil = null;
      this._adminPin = this._pin;
      this._pin = '';
      this._currentView = 'user-list';
      this.saveLockoutState();
      await this.loadUsers();
      await this.loadLocks();
      this.render();
    } catch (e) {
      console.error('Authentication error:', e);
      this._failedAttempts++;
      this._pin = '';
      const maxAttempts   = this._config?.max_failed_attempts ?? 5;
      const lockoutSecs   = this._config?.lockout_duration    ?? 300;
      if (this._failedAttempts >= maxAttempts) {
        this._lockedUntil = new Date(Date.now() + lockoutSecs * 1000);
      }
      this.saveLockoutState();
      this.render();
    }
  }

  async saveUser() {
    if (!this._selectedUser) return;
    try {
      const payload = {
        admin_pin: this._adminPin,
        name: this._selectedUser.name,
        phone: this._selectedUser.phone,
        email: this._selectedUser.email,
        is_admin: this._selectedUser.is_admin,
        has_separate_lock_pin: this._selectedUser.has_separate_lock_pin
      };
      if (this._selectedUser.pin) payload.pin = this._selectedUser.pin;
      if (this._selectedUser.has_separate_lock_pin && this._selectedUser.lock_pin)
        payload.lock_pin = this._selectedUser.lock_pin;

      await this._apiPut(`/api/users/${this._selectedUser.id}`, payload);

      const index = this._users.findIndex(u => u.id === this._selectedUser.id);
      if (index !== -1) this._users[index] = {...this._selectedUser};
      this._currentView = 'user-list';
      this._selectedUser = null;
      this.render();
      this.showNotification('User updated successfully', 'success');
    } catch (e) {
      console.error('Failed to save user:', e);
      this.showNotification('Failed to save user', 'error');
    }
  }

  async deleteUser(userId) {
    if (!confirm('Are you sure you want to delete this user?')) return;
    try {
      await this._apiDelete(`/api/users/${userId}`, { admin_pin: this._adminPin });
      this._users = this._users.filter(u => u.id !== userId);
      this._currentView = 'user-list';
      this._selectedUser = null;
      this.render();
      this.showNotification('User deleted successfully', 'success');
    } catch (e) {
      console.error('Failed to delete user:', e);
      this.showNotification('Failed to delete user', 'error');
    }
  }

  attachPinValidation() {
    const addValidation = (inputId, errorId, minLen, maxLen) => {
      const input = this.shadowRoot.getElementById(inputId);
      if (!input) return;
      input.addEventListener('blur', () => {
        const val = input.value;
        this.showFieldError(inputId, errorId, val.length > 0 && (val.length < minLen || val.length > maxLen));
      });
      input.addEventListener('input', () => {
        const val = input.value;
        if (input.classList.contains('invalid') && val.length >= minLen && val.length <= maxLen) {
          input.classList.remove('invalid');
          const err = this.shadowRoot.getElementById(errorId);
          if (err) err.classList.remove('visible');
        }
      });
    };
    addValidation('pin-input', 'pin-error', 6, 8);
    addValidation('lock-pin-input', 'lock-pin-error', 6, 8);
  }

  showFieldError(fieldId, errorId, condition) {
    const field = this.shadowRoot.getElementById(fieldId);
    const error = this.shadowRoot.getElementById(errorId);
    if (field && error) {
      if (condition) {
        field.classList.add('invalid');
        error.classList.add('visible');
      } else {
        field.classList.remove('invalid');
        error.classList.remove('visible');
      }
    }
    return condition;
  }

  clearFieldErrors() {
    this.shadowRoot.querySelectorAll('.form-input.invalid').forEach(el => el.classList.remove('invalid'));
    this.shadowRoot.querySelectorAll('.field-error.visible').forEach(el => el.classList.remove('visible'));
  }

  async createUser() {
    this.clearFieldErrors();
    let hasErrors = false;

    // Validate name
    if (!this._editingUser.name) {
      if (this.showFieldError('name-input', 'name-error', true)) hasErrors = true;
    }

    // Validate alarm PIN
    if (!this._editingUser.pin || this._editingUser.pin.length < 6 || this._editingUser.pin.length > 8) {
      if (this.showFieldError('pin-input', 'pin-error', true)) hasErrors = true;
    }

    // Validate lock PIN if enabled
    if (this._editingUser.has_separate_lock_pin) {
      if (!this._editingUser.lock_pin || this._editingUser.lock_pin.length < 6 || this._editingUser.lock_pin.length > 8) {
        if (this.showFieldError('lock-pin-input', 'lock-pin-error', true)) hasErrors = true;
      }
    }

    if (hasErrors) return;

    try {
      console.log('Creating user with data:', {
        name: this._editingUser.name,
        has_phone: !!this._editingUser.phone,
        has_email: !!this._editingUser.email,
        is_admin: this._editingUser.is_admin,
        has_separate_lock_pin: this._editingUser.has_separate_lock_pin,
        has_lock_pin: !!this._editingUser.lock_pin
      });

      const userData = {
        name: this._editingUser.name,
        pin: this._editingUser.pin,
        // No admin_pin needed - service will use auto-generated PIN
        is_admin: this._editingUser.is_admin || false,
        is_duress: false
      };

      // Add optional fields only if they have values
      if (this._editingUser.phone && this._editingUser.phone.trim()) {
        userData.phone = this._editingUser.phone.trim();
      }
      
      if (this._editingUser.email && this._editingUser.email.trim()) {
        userData.email = this._editingUser.email.trim();
      }
      
      if (this._editingUser.has_separate_lock_pin) {
        userData.has_separate_lock_pin = true;
        if (this._editingUser.lock_pin) {
          userData.lock_pin = this._editingUser.lock_pin;
        }
      } else {
        userData.has_separate_lock_pin = false;
      }

      console.log('Calling add_user service with:', userData);

      await this._apiPost('/api/users', { ...userData, admin_pin: this._adminPin });
      await this.loadUsers();

      // Go back to list
      this._currentView = 'user-list';
      this._editingUser = {};
      this.render();

      this.showNotification('User created successfully', 'success');
    } catch (e) {
      console.error('Failed to create user:', e);
      this.showNotification(`Failed to create user: ${e.message}`, 'error');
    }
  }

  showNotification(message, type = 'info') {
    // Inline toast notification — no HA service round-trip needed
    const existing = this.shadowRoot.querySelector('.toast-notification');
    if (existing) existing.remove();

    const colors = { success: '#10b981', error: '#ef4444', info: '#3b82f6', warning: '#f59e0b' };
    const toast = document.createElement('div');
    toast.className = 'toast-notification';
    toast.style.cssText = `
      position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
      background: ${colors[type] || colors.info}; color: white;
      padding: 12px 20px; border-radius: 8px; font-size: 14px; font-weight: 500;
      box-shadow: 0 4px 12px rgba(0,0,0,0.3); z-index: 9999;
      max-width: 90%; text-align: center; pointer-events: none;
    `;
    toast.textContent = message;
    this.shadowRoot.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
  }
}

customElements.define('homesecure-admin', HomeSecureAdmin);

// Visual Editor for Admin Panel
class HomeSecureAdminEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: 'open' });
    }
    this.render();
  }

  set hass(hass) {
    this._hass = hass;
  }

  render() {
    this.shadowRoot.innerHTML = `
      <style>
        .card-config {
          padding: 16px;
        }
        .option {
          margin-bottom: 16px;
        }
        .option label {
          display: block;
          margin-bottom: 8px;
          font-weight: 500;
          color: var(--primary-text-color);
        }
        .option input,
        .option select {
          width: 100%;
          padding: 8px;
          border: 1px solid var(--divider-color);
          border-radius: 4px;
          background: var(--card-background-color);
          color: var(--primary-text-color);
          font-size: 14px;
          box-sizing: border-box;
        }
        .option input:focus,
        .option select:focus {
          outline: none;
          border-color: #667eea;
        }
        .help-text {
          font-size: 12px;
          color: var(--secondary-text-color);
          margin-top: 4px;
        }
      </style>
      <div class="card-config">
        <div class="option">
          <label for="entity">Alarm Entity (Required)</label>
          <input
            type="text"
            id="entity"
            value="${this._config.entity || ''}"
            placeholder="alarm_control_panel.homesecure"
          />
          <div class="help-text">Select your secure alarm control panel entity</div>
        </div>
      </div>
    `;

    this.shadowRoot.getElementById('entity').addEventListener('input', (e) => {
      this._config = { ...this._config, entity: e.target.value };
      this.dispatchEvent(new CustomEvent('config-changed', {
        detail: { config: this._config },
        bubbles: true,
        composed: true
      }));
    });
  }
}

customElements.define('homesecure-admin-editor', HomeSecureAdminEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'homesecure-admin',
  name: 'HomeSecure Admin Panel',
  description: 'Administrative interface for HomeSecure System',
  preview: true,
  documentationURL: 'https://github.com/mmotrock/homesecure-addon'
});