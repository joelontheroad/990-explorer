#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Prioritize local virtual environment if available
if [[ -f "${SCRIPT_DIR}/.venv/bin/python" ]]; then
    exec "${SCRIPT_DIR}/.venv/bin/python" "${SCRIPT_DIR}/main.py" "$@"
elif command -v python3 >/dev/null 2>&1; then
    exec python3 "${SCRIPT_DIR}/main.py" "$@"
elif command -v python >/dev/null 2>&1; then
    exec python "${SCRIPT_DIR}/main.py" "$@"
else
    echo "Error: Python 3 runtime not found. Please install python3." >&2
    exit 1
fi
