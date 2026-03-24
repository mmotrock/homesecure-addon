#!/usr/bin/with-contenv bashio
set -e

# ── read addon options ─────────────────────────────────────────────────────
ZWAVE_URL=$(bashio::config 'zwave_server_url')
LOG_LEVEL=$(bashio::config 'log_level')
API_TOKEN=$(bashio::config 'api_token' 2>/dev/null || echo "")

bashio::log.info "======================================================="
bashio::log.info " HomeSecure Container  v2.0.0"
bashio::log.info "======================================================="
bashio::log.info " Z-Wave JS : ${ZWAVE_URL}"
bashio::log.info " Log level : ${LOG_LEVEL}"
bashio::log.info "======================================================="

# ── Integration install notice ─────────────────────────────────────────────
# In v2.0 the add-on no longer auto-installs the HA integration.
# Print a clear notice on every startup until the integration is detected.
if [ ! -f "/config/custom_components/homesecure/__init__.py" ]; then
    bashio::log.warning ""
    bashio::log.warning "╔══════════════════════════════════════════════════════╗"
    bashio::log.warning "║   ACTION REQUIRED — Integration not installed        ║"
    bashio::log.warning "╠══════════════════════════════════════════════════════╣"
    bashio::log.warning "║                                                      ║"
    bashio::log.warning "║  The HomeSecure HA integration must be installed     ║"
    bashio::log.warning "║  manually.  Copy the custom_components/homesecure/   ║"
    bashio::log.warning "║  folder from the add-on repository to:               ║"
    bashio::log.warning "║                                                      ║"
    bashio::log.warning "║    /config/custom_components/homesecure/             ║"
    bashio::log.warning "║                                                      ║"
    bashio::log.warning "║  Then restart Home Assistant and add the integration ║"
    bashio::log.warning "║  via Settings → Devices & Services → Add Integration ║"
    bashio::log.warning "║  Search: HomeSecure                                  ║"
    bashio::log.warning "║  URL:    http://localhost:8099                        ║"
    bashio::log.warning "║                                                      ║"
    bashio::log.warning "║  The container API is running and ready.             ║"
    bashio::log.warning "╚══════════════════════════════════════════════════════╝"
    bashio::log.warning ""
else
    bashio::log.info "✓ Integration detected at /config/custom_components/homesecure/"
fi

# ── install Lovelace cards (still lives here) ──────────────────────────────
bashio::log.info "Installing Lovelace cards …"
mkdir -p /config/www
cp -f /app/www/homesecure-card.js  /config/www/
cp -f /app/www/homesecure-admin.js /config/www/
bashio::log.info "✓ Cards installed to /config/www/"

if [ -f /config/.storage/lovelace_resources ]; then
    if ! grep -q "homesecure-card.js" /config/.storage/lovelace_resources 2>/dev/null; then
        bashio::log.warning "⚠ Add the cards to Lovelace resources:"
        bashio::log.warning "  /local/homesecure-card.js  (JavaScript Module)"
        bashio::log.warning "  /local/homesecure-admin.js (JavaScript Module)"
    fi
fi

# ── environment for the Python services ───────────────────────────────────
export DB_PATH="/data/homesecure.db"
export ZWAVE_URL="${ZWAVE_URL}"
export LOG_LEVEL="${LOG_LEVEL}"
export API_HOST="0.0.0.0"
export API_PORT="8099"
[ -n "${API_TOKEN}" ] && export HOMESECURE_API_TOKEN="${API_TOKEN}"

# ── start the HomeSecure container service ─────────────────────────────────
bashio::log.info "Starting HomeSecure container service …"
cd /app
exec python3 main.py
