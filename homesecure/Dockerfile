ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.19
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# System deps — nginx removed (api_server.py is its own HTTP server)
# cargo/gcc/musl-dev still needed to compile bcrypt wheels on Alpine
RUN apk add --no-cache \
    python3 \
    py3-pip \
    sqlite \
    jq \
    bash \
    gcc \
    musl-dev \
    libffi-dev \
    python3-dev \
    cargo \
    openssl-dev

# Python packages for the container service
# bcrypt + zwave-js-server-python stay here (moved OUT of the HA integration)
RUN python3 -m venv $VIRTUAL_ENV && \
    pip install --no-cache-dir \
        bcrypt \
        zwave-js-server-python \
        aiohttp \
        pyyaml

# Scripts
COPY rootfs /
RUN chmod a+x /usr/bin/configure-logging.sh

# App directories
RUN mkdir -p /app/www /data

WORKDIR /app

# Container service files (root-level Python — the actual HomeSecure process)
COPY main.py             /app/
COPY api_server.py       /app/
COPY alarm_coordinator.py /app/
COPY lock_manager.py     /app/
COPY database.py         /app/
COPY migrate.py          /app/

# Integration files (copied to /config/custom_components at runtime by run.sh)
COPY custom_components/ /app/custom_components/

# Lovelace cards (copied to /config/www at runtime by run.sh)
COPY www/ /app/www/

# run.sh — place where s6-overlay expects it so bashio and with-contenv work
RUN mkdir -p /etc/services.d/homesecure
COPY run.sh /etc/services.d/homesecure/run
RUN chmod a+x /etc/services.d/homesecure/run
