#!/usr/bin/env python3
"""List all available OpenAI models."""
import os
import sys

try:
    from openai import OpenAI
except ImportError:
    print("Error: 'openai' module not found", file=sys.stderr)
    print("Install it with: pip install openai", file=sys.stderr)
    print("Or activate your virtual environment and install: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)

def main():
    # Get API key from environment variable
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY environment variable not set", file=sys.stderr)
        print("Set it with: export OPENAI_API_KEY=sk-your-key-here", file=sys.stderr)
        sys.exit(1)
    
    try:
        client = OpenAI(api_key=api_key)
        
        print("Fetching available models from OpenAI API...")
        print("=" * 80)
        
        models = client.models.list()
        
        # Filter and sort models
        model_list = []
        for model in models.data:
            model_id = model.id
            # Filter out deprecated or internal models if desired
            # You can adjust this filter as needed
            if not model_id.startswith("davinci") and not model_id.startswith("curie"):
                model_list.append(model_id)
        
        # Sort models
        model_list.sort()
        
        print(f"\nFound {len(model_list)} models:\n")
        
        # Group by model family
        gpt_models = [m for m in model_list if m.startswith("gpt")]
        other_models = [m for m in model_list if not m.startswith("gpt")]
        
        if gpt_models:
            print("GPT Models:")
            print("-" * 80)
            for model in gpt_models:
                print(f"  • {model}")
            print()
        
        if other_models:
            print("Other Models:")
            print("-" * 80)
            for model in other_models:
                print(f"  • {model}")
            print()
        
        # Show models that are likely compatible with Assistants API
        assistants_compatible = [
            m for m in gpt_models 
            if any(x in m for x in ["gpt-4o", "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo"])
        ]
        
        if assistants_compatible:
            print("=" * 80)
            print("Models likely compatible with Assistants API:")
            print("-" * 80)
            for model in assistants_compatible:
                print(f"  • {model}")
            print()
        
        # Output in format suitable for AVAILABLE_MODELS env var
        print("=" * 80)
        print("For use in AVAILABLE_MODELS environment variable:")
        print("-" * 80)
        print(",".join(assistants_compatible) if assistants_compatible else ",".join(gpt_models[:5]))
        print()
        
    except Exception as e:
        print(f"Error fetching models: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()

