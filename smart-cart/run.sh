#!/bin/sh

echo "=== Smart Cart Starting ==="

# Read configuration from HA options
CONFIG_PATH=/data/options.json

if [ -f "$CONFIG_PATH" ]; then
    CLAUDE_API_KEY=$(python3 -c "import json; d=json.load(open('$CONFIG_PATH')); print(d.get('claude_api_key',''))")
    DELIVERY_WINDOW=$(python3 -c "import json; d=json.load(open('$CONFIG_PATH')); print(d.get('preferred_delivery_window','morning'))")
    SPLIT_THRESHOLD=$(python3 -c "import json; d=json.load(open('$CONFIG_PATH')); print(d.get('split_threshold',10))")
    export ANTHROPIC_API_KEY="$CLAUDE_API_KEY"
    export DELIVERY_WINDOW="$DELIVERY_WINDOW"
    export SPLIT_THRESHOLD="$SPLIT_THRESHOLD"
    echo "Config loaded from $CONFIG_PATH"
else
    echo "No options.json found, using defaults"
fi

# HA Supervisor sets INGRESS_PATH automatically
# Print it so we can see it in logs
echo "INGRESS_PATH: ${INGRESS_PATH:-not set}"

# Use /data for persistent storage
export DATA_DIR="/data/smart-cart"
mkdir -p "$DATA_DIR"
echo "Data directory: $DATA_DIR"

# Initialise data files
python3 init_data.py

echo "Starting Flask server..."
python3 main.py
