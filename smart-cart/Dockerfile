ARG BUILD_FROM
FROM $BUILD_FROM

# Install Python and dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    py3-requests \
    py3-flask \
    gcc \
    musl-dev \
    python3-dev \
    libffi-dev

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Copy application files
COPY . .

# Create data directory
RUN mkdir -p /data

# Make run script executable
RUN chmod +x run.sh

CMD ["/bin/sh", "run.sh"]
