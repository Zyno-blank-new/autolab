#!/usr/bin/env bash
set -euo pipefail
AUTOLAB_DEMO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$AUTOLAB_DEMO_ROOT/.venv/bin/python" "$AUTOLAB_DEMO_ROOT/tools/present_demo.py" "$@"
