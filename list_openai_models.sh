#!/bin/bash
# List all available OpenAI models using the OpenAI API

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Load OPENAI_API_KEY from .env file if it exists
if [ -f "$SCRIPT_DIR/.env" ]; then
    echo "Loading API key from .env file..."
    # Parse .env file and extract OPENAI_API_KEY (handles special characters)
    # This method is safer than sourcing the entire .env file
    while IFS='=' read -r key value; do
        # Skip comments and empty lines
        [[ "$key" =~ ^#.*$ ]] && continue
        [[ -z "$key" ]] && continue
        
        # Remove leading/trailing whitespace
        key=$(echo "$key" | xargs)
        value=$(echo "$value" | xargs)
        
        # Only export OPENAI_API_KEY
        if [ "$key" = "OPENAI_API_KEY" ]; then
            export OPENAI_API_KEY="$value"
            break
        fi
    done < "$SCRIPT_DIR/.env"
fi

# Check if OPENAI_API_KEY is set
if [ -z "$OPENAI_API_KEY" ]; then
    echo "Error: OPENAI_API_KEY environment variable not set" >&2
    echo "Set it with: export OPENAI_API_KEY=sk-your-key-here" >&2
    echo "Or add it to .env file in the project root" >&2
    exit 1
fi

# Check for virtual environment and activate it if it exists
if [ -d "$SCRIPT_DIR/venv" ]; then
    echo "Activating virtual environment..."
    source "$SCRIPT_DIR/venv/bin/activate"
elif [ -d "$SCRIPT_DIR/.venv" ]; then
    echo "Activating virtual environment..."
    source "$SCRIPT_DIR/.venv/bin/activate"
fi

# Run the Python script
python3 "$SCRIPT_DIR/list_openai_models.py"

