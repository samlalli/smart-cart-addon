ARG BUILD_FROM=python:3.12-alpine
FROM $BUILD_FROM

# Install dependencies
RUN apk add --no-cache gcc musl-dev libffi-dev

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Create data directory
RUN mkdir -p /data

# Make run script executable
RUN chmod +x run.sh

CMD ["/bin/sh", "run.sh"]
