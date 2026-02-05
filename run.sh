#!/usr/bin/with-contenv bashio
set -e

CONFIG_PATH=/data/options.json

# Parse configuration
ADMIN_NAME=$(bashio::config 'admin_name')
ADMIN_PIN=$(bashio::config 'admin_pin')
ZWAVE_URL=$(bashio::config 'zwave_server_url')
LOG_LEVEL=$(bashio::config 'log_level')

bashio::log.info "=========================================="
bashio::log.info "Starting HomeSecure Add-on v1.0.0"
bashio::log.info "=========================================="

# Configure logging
bashio::log.info "Configuring logging (level: ${LOG_LEVEL})..."
/usr/bin/configure-logging.sh "${LOG_LEVEL}"

# Install integration
bashio::log.info "Installing HomeSecure integration..."
/usr/bin/install-integration.sh "${ADMIN_NAME}" "${ADMIN_PIN}" "${ZWAVE_URL}"

# Install Lovelace cards
bashio::log.info "Installing Lovelace cards..."
mkdir -p /config/www
cp -f /app/www/homesecure-card.js /config/www/
cp -f /app/www/homesecure-admin.js /config/www/
bashio::log.info "✓ Cards installed to /config/www/"

# Add to Lovelace resources if not already there
if [ -f /config/.storage/lovelace_resources ]; then
    if ! grep -q "homesecure-card.js" /config/.storage/lovelace_resources 2>/dev/null; then
        bashio::log.warning "⚠ Please add cards to Lovelace resources:"
        bashio::log.warning "  Settings → Dashboards → Resources → Add Resource"
        bashio::log.warning "  URL: /local/homesecure-card.js (JavaScript Module)"
        bashio::log.warning "  URL: /local/homesecure-admin.js (JavaScript Module)"
    fi
fi

# Start log aggregation service
bashio::log.info "Starting log aggregation service..."
python3 /app/log_service.py &
LOG_PID=$!

# Start web interface
bashio::log.info "Starting web interface on port 8099..."
python3 /app/web_interface.py &
WEB_PID=$!

bashio::log.info "=========================================="
bashio::log.info "✓ HomeSecure started successfully!"
bashio::log.info "=========================================="
bashio::log.info ""
bashio::log.info "Next steps:"
bashio::log.info "1. Restart Home Assistant"
bashio::log.info "2. Go to Settings → Devices & Services"
bashio::log.info "3. Click 'Add Integration' and search for 'HomeSecure'"
bashio::log.info "4. Add Lovelace resources (see warnings above)"
bashio::log.info "5. Add HomeSecure card to your dashboard"
bashio::log.info ""
bashio::log.info "Web UI: Supervisor → HomeSecure → Open Web UI"
bashio::log.info "=========================================="

# Wait for processes
wait $LOG_PID $WEB_PID