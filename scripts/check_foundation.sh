#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
PYTHON=${PYTHON:-python3}
"$PYTHON" -m pytest
PYTHONPATH=src "$PYTHON" -m bursa_transit
