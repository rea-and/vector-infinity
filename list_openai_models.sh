#!/bin/bash
# List all available OpenAI models using the OpenAI API

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Load .env file if it exists
if [ -f "$SCRIPT_DIR/.env" ]; then
    echo "Loading API key from .env file..."
    # Export variables from .env file (handles comments and empty lines)
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

# Check if OPENAI_API_KEY is set
if [ -z "$OPENAI_API_KEY" ]; then
    echo "Error: OPENAI_API_KEY environment variable not set" >&2
    echo "Set it with: export OPENAI_API_KEY=sk-your-key-here" >&2
    echo "Or add it to .env file in the project root" >&2
    exit 1
fi

# Run the Python script
python3 "$SCRIPT_DIR/list_openai_models.py"

