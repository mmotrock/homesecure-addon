#!/usr/bin/with-contenv bashio
# Do NOT use set -e — grep returning no match would kill the script

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

# ── Auto-install / update the HA integration ──────────────────────────────
INTEGRATION_SRC="/app/custom_components/homesecure"
INTEGRATION_DST="/config/custom_components/homesecure"
ADDON_VERSION=$(bashio::addon.version 2>/dev/null || grep -m1 '^version:' /app/custom_components/homesecure/../../../config.yaml 2>/dev/null | tr -d '"' | awk '{print $2}' || echo "2.0.0")

_installed_version() {
    local manifest="${INTEGRATION_DST}/manifest.json"
    if [ -f "${manifest}" ]; then
        grep -o '"version": *"[^"]*"' "${manifest}" | grep -o '[0-9][^"]*' | head -1 || true
    fi
}

INSTALLED_VERSION=$(_installed_version || true)

if [ -z "${INSTALLED_VERSION}" ]; then
    # Fresh install — not present yet
    bashio::log.info "Installing HomeSecure integration v${ADDON_VERSION} …"
    mkdir -p "${INTEGRATION_DST}"
    cp -rf "${INTEGRATION_SRC}/." "${INTEGRATION_DST}/"
    bashio::log.info "✓ Integration installed to ${INTEGRATION_DST}"
    bashio::log.warning ""
    bashio::log.warning "╔══════════════════════════════════════════════════════╗"
    bashio::log.warning "║   ACTION REQUIRED — Restart Home Assistant           ║"
    bashio::log.warning "╠══════════════════════════════════════════════════════╣"
    bashio::log.warning "║                                                      ║"
    bashio::log.warning "║  The HomeSecure integration has been installed.      ║"
    bashio::log.warning "║  Please restart Home Assistant, then add it via:     ║"
    bashio::log.warning "║                                                      ║"
    bashio::log.warning "║  Settings → Devices & Services → Add Integration    ║"
    bashio::log.warning "║  Search: HomeSecure                                  ║"
    bashio::log.warning "║  URL:    http://localhost:8099                        ║"
    bashio::log.warning "║                                                      ║"
    bashio::log.warning "╚══════════════════════════════════════════════════════╝"
    bashio::log.warning ""
elif [ "${INSTALLED_VERSION}" != "${ADDON_VERSION}" ]; then
    # Upgrade — version mismatch
    bashio::log.info "Updating HomeSecure integration ${INSTALLED_VERSION} → ${ADDON_VERSION} …"
    cp -rf "${INTEGRATION_SRC}/." "${INTEGRATION_DST}/"
    bashio::log.info "✓ Integration updated to v${ADDON_VERSION}"
    bashio::log.warning "⚠ Restart Home Assistant to apply the integration update."
else
    # Already up to date
    bashio::log.info "✓ Integration v${INSTALLED_VERSION} is up to date"
fi

# ── install Lovelace cards (still lives here) ──────────────────────────────
bashio::log.info "Installing Lovelace cards …"
mkdir -p /config/www/homesecure
cp -f /app/www/homesecure-card.js  /config/www/homesecure/
cp -f /app/www/homesecure-admin.js /config/www/homesecure/
bashio::log.info "✓ Cards installed to /config/www/homesecure/"

if [ -f /config/.storage/lovelace_resources ]; then
    if ! grep -q "homesecure-card.js" /config/.storage/lovelace_resources 2>/dev/null; then
        bashio::log.warning "⚠ Add the cards to Lovelace resources:"
        bashio::log.warning "  /local/homesecure/homesecure-card.js  (JavaScript Module)"
        bashio::log.warning "  /local/homesecure/homesecure-admin.js (JavaScript Module)"
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
exec /opt/venv/bin/python3 /app/main.py
