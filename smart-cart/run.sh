#!/bin/sh

# Read configuration from HA options
CONFIG_PATH=/data/options.json

if [ -f "$CONFIG_PATH" ]; then
    CLAUDE_API_KEY=$(python3 -c "import json; d=json.load(open('$CONFIG_PATH')); print(d.get('claude_api_key',''))")
    DELIVERY_WINDOW=$(python3 -c "import json; d=json.load(open('$CONFIG_PATH')); print(d.get('preferred_delivery_window','morning'))")
    SPLIT_THRESHOLD=$(python3 -c "import json; d=json.load(open('$CONFIG_PATH')); print(d.get('split_threshold',10))")

    export ANTHROPIC_API_KEY="$CLAUDE_API_KEY"
    export DELIVERY_WINDOW="$DELIVERY_WINDOW"
    export SPLIT_THRESHOLD="$SPLIT_THRESHOLD"
fi

# Use /data for persistent storage (survives add-on updates)
export DATA_DIR="/data/smart-cart"
mkdir -p "$DATA_DIR"

# Initialise data files if they don't exist
python3 init_data.py

echo "Starting Smart Cart..."
python3 main.py
