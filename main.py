#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""IRS 990 Ultimate Funding & Relationship Social Graph Explorer.

Architectural Purpose:
    Serves as the root execution entrypoint for the CLI application, ensuring
    automatic virtual environment reactivation and terminal hygiene initialization
    before dispatching execution to the CLI controller.
"""
import sys
import os

try:
    from irs990.cli import setup_terminal_hygiene
    setup_terminal_hygiene()
except Exception:
    pass

if sys.prefix == sys.base_prefix and not os.environ.get("_IRS990_VENV_ACTIVE"):
    venv_python = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "bin", "python")
    if os.path.exists(venv_python):
        os.environ["_IRS990_VENV_ACTIVE"] = "1"
        os.execv(venv_python, [venv_python] + sys.argv)

from irs990.cli import main

if __name__ == "__main__":
    main()
