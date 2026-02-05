ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.19
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8

# Install requirements
RUN apk add --no-cache \
    python3 \
    py3-pip \
    sqlite \
    nginx \
    jq \
    bash

# Install Python packages
RUN pip3 install --no-cache-dir --break-system-packages \
    bcrypt \
    zwave-js-server-python \
    aiohttp \
    pyyaml

# Copy root filesystem
COPY rootfs /

# Make scripts executable
RUN chmod a+x /usr/bin/install-integration.sh && \
    chmod a+x /usr/bin/configure-logging.sh

# Setup directories
RUN mkdir -p /var/log/homesecure && \
    mkdir -p /app/custom_components && \
    mkdir -p /app/www

WORKDIR /app

# Copy add-on files
COPY run.sh /app/
COPY custom_components/ /app/custom_components/
COPY www/ /app/www/
COPY log_service.py /app/
COPY web_interface.py /app/

RUN chmod a+x /app/run.sh

CMD ["/app/run.sh"]