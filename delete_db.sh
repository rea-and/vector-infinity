#!/bin/bash
# Script to delete all database files for Vector Infinity

set -e

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Load config to get database path
if [ -f "config.py" ]; then
    # Extract DATABASE_PATH from config.py
    DATABASE_PATH=$(python3 -c "import config; print(config.DATABASE_PATH)" 2>/dev/null || echo "")
else
    echo "Error: config.py not found"
    exit 1
fi

# If DATABASE_PATH is empty, use default
if [ -z "$DATABASE_PATH" ]; then
    DATABASE_PATH="$SCRIPT_DIR/data/vector_infinity.db"
fi

# Convert to absolute path
if [[ ! "$DATABASE_PATH" = /* ]]; then
    DATABASE_PATH="$SCRIPT_DIR/$DATABASE_PATH"
fi

# Find all database files
DB_FILES=()

# Main database file
if [ -f "$DATABASE_PATH" ]; then
    DB_FILES+=("$DATABASE_PATH")
fi

# Also check for common database file patterns
if [ -d "$SCRIPT_DIR/data" ]; then
    while IFS= read -r -d '' file; do
        DB_FILES+=("$file")
    done < <(find "$SCRIPT_DIR/data" -name "*.db" -type f -print0 2>/dev/null || true)
    
    while IFS= read -r -d '' file; do
        DB_FILES+=("$file")
    done < <(find "$SCRIPT_DIR/data" -name "*.db-shm" -type f -print0 2>/dev/null || true)
    
    while IFS= read -r -d '' file; do
        DB_FILES+=("$file")
    done < <(find "$SCRIPT_DIR/data" -name "*.db-wal" -type f -print0 2>/dev/null || true)
fi

# Remove duplicates
IFS=$'\n' DB_FILES=($(printf '%s\n' "${DB_FILES[@]}" | sort -u))

if [ ${#DB_FILES[@]} -eq 0 ]; then
    echo "No database files found to delete."
    exit 0
fi

echo "========================================="
echo "Vector Infinity - Delete Database Files"
echo "========================================="
echo ""
echo "The following database files will be deleted:"
echo ""
for file in "${DB_FILES[@]}"; do
    if [ -f "$file" ]; then
        SIZE=$(du -h "$file" | cut -f1)
        echo "  - $file ($SIZE)"
    fi
done
echo ""

# Ask for confirmation
read -p "Are you sure you want to delete all database files? (yes/no): " -r
echo

if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    echo "Cancelled. No files were deleted."
    exit 0
fi

# Delete files
DELETED=0
FAILED=0

for file in "${DB_FILES[@]}"; do
    if [ -f "$file" ]; then
        if rm -f "$file"; then
            echo "✓ Deleted: $file"
            ((DELETED++))
        else
            echo "✗ Failed to delete: $file"
            ((FAILED++))
        fi
    fi
done

echo ""
echo "========================================="
if [ $FAILED -eq 0 ]; then
    echo "✓ Successfully deleted $DELETED database file(s)"
else
    echo "⚠️  Deleted $DELETED file(s), $FAILED failed"
    exit 1
fi
echo "========================================="
echo ""
echo "Note: The database will be recreated automatically on next application startup."

