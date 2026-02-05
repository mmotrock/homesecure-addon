#!/usr/bin/with-contenv bashio

set -e

ADMIN_NAME="$1"
ADMIN_PIN="$2"
ZWAVE_URL="$3"

INTEGRATION_PATH="/config/custom_components/homesecure"
SOURCE_PATH="/app/custom_components/homesecure"

bashio::log.info "Installing HomeSecure integration..."

# Remove old installation if exists
if [ -d "${INTEGRATION_PATH}" ]; then
    bashio::log.info "Removing existing installation..."
    rm -rf "${INTEGRATION_PATH}"
fi

# Create directory
mkdir -p "${INTEGRATION_PATH}"

# Copy all integration files
bashio::log.info "Copying integration files..."
cp -r "${SOURCE_PATH}"/* "${INTEGRATION_PATH}/"

# Set permissions
chmod -R 755 "${INTEGRATION_PATH}"

# Create initial config entry data (for future auto-configuration)
bashio::log.info "Preparing integration configuration..."
cat > "${INTEGRATION_PATH}/.install_data.json" <<EOF
{
  "admin_name": "${ADMIN_NAME}",
  "admin_pin": "${ADMIN_PIN}",
  "zwave_server_url": "${ZWAVE_URL}"
}
EOF

bashio::log.info "✓ Integration installed to ${INTEGRATION_PATH}"
bashio::log.info ""
bashio::log.info "Integration will be available after Home Assistant restart"
bashio::log.info "Configure via: Settings → Devices & Services → Add Integration → HomeSecure"