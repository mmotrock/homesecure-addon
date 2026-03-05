ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.19
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install system requirements + build deps needed to compile Python packages
RUN apk add --no-cache \
    python3 \
    py3-pip \
    sqlite \
    nginx \
    jq \
    bash \
    gcc \
    musl-dev \
    libffi-dev \
    python3-dev \
    cargo \
    openssl-dev

# Create virtual environment and install Python packages inside it
RUN python3 -m venv $VIRTUAL_ENV && \
    pip install --no-cache-dir \
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