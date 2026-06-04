#!/bin/bash
# Usage: source activate-env.sh [env_name]
BASE_DIR="/Users/sgawde/work/py-shared-env"
TARGET_ENV=$1

if [ -z "$TARGET_ENV" ]; then
    echo "Usage: source activate-env.sh [poc|dev|test|prod]"
    return 1 2>/dev/null || exit 1
fi

ENV_PATH="$BASE_DIR/$TARGET_ENV"

if [ ! -d "$ENV_PATH" ]; then
    echo "Error: Shared environment '$TARGET_ENV' not found at $ENV_PATH"
    return 1 2>/dev/null || exit 1
fi

source "$ENV_PATH/bin/activate"
echo "Activated shared environment: $TARGET_ENV"
