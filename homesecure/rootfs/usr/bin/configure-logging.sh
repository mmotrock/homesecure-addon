#!/usr/bin/with-contenv bashio

set -e

LOG_LEVEL="${1:-info}"
LOG_DIR="/var/log/homesecure"
HA_CONFIG="/config"

bashio::log.info "Configuring HomeSecure logging (level: ${LOG_LEVEL})..."

# Create log directory
mkdir -p "${LOG_DIR}"

# Configure Home Assistant to include HomeSecure logs
LOGGER_CONFIG="${HA_CONFIG}/configuration.yaml"

# Check if configuration.yaml exists
if [ ! -f "${LOGGER_CONFIG}" ]; then
    bashio::log.warning "configuration.yaml not found, creating..."
    touch "${LOGGER_CONFIG}"
fi

# Function to safely add or update logger configuration
configure_logger() {
    local config_file="$1"
    local log_level="$2"
    
    # Check if logger section exists
    if ! grep -q "^logger:" "${config_file}" 2>/dev/null; then
        bashio::log.info "Adding logger configuration to configuration.yaml..."
        cat >> "${config_file}" <<EOF

# HomeSecure Logging Configuration
logger:
  default: warning
  logs:
    custom_components.homesecure: ${log_level}
    custom_components.homesecure.alarm_coordinator: ${log_level}
    custom_components.homesecure.lock_manager: ${log_level}
    custom_components.homesecure.database: ${log_level}
EOF
    else
        bashio::log.info "Logger configuration already exists"
        
        # Check if our logs section exists
        if grep -q "custom_components.homesecure:" "${config_file}"; then
            bashio::log.info "Updating HomeSecure log level to ${log_level}..."
            # Update existing HomeSecure log levels
            sed -i "s/custom_components\.homesecure:.*$/custom_components.homesecure: ${log_level}/g" "${config_file}"
            sed -i "s/custom_components\.homesecure\.alarm_coordinator:.*$/custom_components.homesecure.alarm_coordinator: ${log_level}/g" "${config_file}"
            sed -i "s/custom_components\.homesecure\.lock_manager:.*$/custom_components.homesecure.lock_manager: ${log_level}/g" "${config_file}"
            sed -i "s/custom_components\.homesecure\.database:.*$/custom_components.homesecure.database: ${log_level}/g" "${config_file}"
        else
            # Add HomeSecure logging to existing logger section
            bashio::log.info "Adding HomeSecure to existing logger configuration..."
            
            # Find the logger: line and add our logs section after it
            # This is tricky with sed, so we'll use a different approach
            if grep -q "^  logs:" "${config_file}"; then
                # logs section exists, add to it
                sed -i "/^  logs:/a\\    custom_components.homesecure: ${log_level}\\n    custom_components.homesecure.alarm_coordinator: ${log_level}\\n    custom_components.homesecure.lock_manager: ${log_level}\\n    custom_components.homesecure.database: ${log_level}" "${config_file}"
            else
                # logs section doesn't exist, create it under logger
                sed -i "/^logger:/a\\  logs:\\n    custom_components.homesecure: ${log_level}\\n    custom_components.homesecure.alarm_coordinator: ${log_level}\\n    custom_components.homesecure.lock_manager: ${log_level}\\n    custom_components.homesecure.database: ${log_level}" "${config_file}"
            fi
        fi
    fi
}

# Apply logger configuration
configure_logger "${LOGGER_CONFIG}" "${LOG_LEVEL}"

# Create log rotation configuration
cat > /etc/logrotate.d/homesecure <<EOF
${LOG_DIR}/*.log {
    daily
    rotate 7
    compress
    delaycompress
    notifempty
    create 0644 root root
    sharedscripts
    postrotate
        # Signal processes to reopen log files
        killall -HUP python3 2>/dev/null || true
    endscript
}
EOF

bashio::log.info "✓ Logging configured successfully"
bashio::log.info "  Log level: ${LOG_LEVEL}"
bashio::log.info "  Log directory: ${LOG_DIR}/homesecure.log"
bashio::log.info "  HA logs: Settings → System → Logs (filter: homesecure)"