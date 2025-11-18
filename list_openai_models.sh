#!/bin/bash
# List all available OpenAI models using the OpenAI API

# Check if OPENAI_API_KEY is set
if [ -z "$OPENAI_API_KEY" ]; then
    echo "Error: OPENAI_API_KEY environment variable not set" >&2
    echo "Set it with: export OPENAI_API_KEY=sk-your-key-here" >&2
    echo "Or load from .env file: source .env" >&2
    exit 1
fi

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Run the Python script
python3 "$SCRIPT_DIR/list_openai_models.py"

