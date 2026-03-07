#!/usr/bin/with-contenv bashio

set -e

ZWAVE_URL="$1"

INTEGRATION_PATH="/config/custom_components/homesecure"
SOURCE_PATH="/app/custom_components/homesecure"

bashio::log.info "Installing HomeSecure integration..."

# Remove old installation if exists
if [ -d "${INTEGRATION_PATH}" ]; then
    bashio::log.info "Removing existing installation..."
    rm -rf "${INTEGRATION_PATH}"
fi

# Create directory and copy integration files
mkdir -p "${INTEGRATION_PATH}"
bashio::log.info "Copying integration files..."
cp -r "${SOURCE_PATH}"/* "${INTEGRATION_PATH}/"
chmod -R 755 "${INTEGRATION_PATH}"

# Write addon config for integration to read Z-Wave URL
cat > "${INTEGRATION_PATH}/.addon_config.json" <<ADDONEOF
{
  "zwave_server_url": "${ZWAVE_URL}"
}
ADDONEOF

bashio::log.info "✓ Integration installed to ${INTEGRATION_PATH}"

# Check if integration is already configured in HA
CONFIGURED=false
if [ -f /config/.storage/core.config_entries ]; then
    if grep -q '"domain": "homesecure"' /config/.storage/core.config_entries 2>/dev/null; then
        CONFIGURED=true
    fi
fi

# Get HA supervisor token for API calls
HA_TOKEN="${SUPERVISOR_TOKEN}"

if [ "$CONFIGURED" = "false" ]; then
    bashio::log.info "Integration not yet configured, sending setup notification..."

    # Fire a persistent notification prompting the user to complete setup
    curl -s -X POST \
        -H "Authorization: Bearer ${HA_TOKEN}" \
        -H "Content-Type: application/json" \
        -d '{
            "notification_id": "homesecure_setup",
            "title": "HomeSecure: Setup Required",
            "message": "HomeSecure is installed! After restarting Home Assistant, go to **Settings → Devices & Services → Add Integration** and search for **HomeSecure** to complete setup."
        }' \
        "http://supervisor/core/api/services/persistent_notification/create" \
        > /dev/null 2>&1 || bashio::log.warning "Could not send setup notification (HA may not be ready yet)"

    bashio::log.info "=========================================="
    bashio::log.info "ACTION REQUIRED:"
    bashio::log.info "1. Restart Home Assistant"
    bashio::log.info "2. Go to Settings → Devices & Services"
    bashio::log.info "3. Search for 'HomeSecure' and complete setup"
    bashio::log.info "=========================================="
else
    bashio::log.info "✓ Integration already configured, skipping setup notification"
fi