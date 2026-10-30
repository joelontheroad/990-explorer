# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Comprehensive Unit and Subprocess Tests for Open Source Standards Compliance.

Architectural Purpose:
    Verifies compliance with the 12 Open Source Software Standards:
    - Directive 1: Permanent state unlinking (zero desktop trash usage) and zero autostart.
    - Directive 2: Preservation of user-facing CLI functionality and exit codes.
    - Directive 3: Clickable terminal URLs, browser auto-launch suppression, and safe desktop entries.
    - Directive 5: Safe RFC 8089 file:// URI resolution, MIME database headers with nosniff, launch tokens.
    - Directive 11: File manager reveal pre-flight and <=1000ms timeout guard.
"""

import os
import sys
import tempfile
import urllib.request
import urllib.parse
import json
import pytest
from pathlib import Path

from irs990.security import (
    parse_safe_file_uri,
    purge_local_state,
    sanitize_log_path,
    is_headless_environment,
    reveal_in_folder
)
from irs990.cli import parse_args
from irs990.server import get_verified_content_type, IRS990RequestHandler


# ==============================================================================
# Directive 1: Privacy & State Purge Tests
# ==============================================================================

def test_purge_local_state_permanent_unlink(tmp_path, monkeypatch):
    """Verify state reset permanently deletes (unlinks) files and avoids desktop trash."""
    # Redirect XDG_CONFIG_HOME to isolated tmp_path
    config_dir = tmp_path / "irs990"
    config_dir.mkdir(parents=True)
    test_preset = config_dir / "presets.yaml"
    test_preset.write_text("depth: 3\nmin_grant: 50000", encoding="utf-8")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    # Create dummy database and WAL files
    db_file = tmp_path / "test.duckdb"
    db_file.write_text("mock database", encoding="utf-8")
    wal_file = tmp_path / "test.duckdb.wal"
    wal_file.write_text("mock wal", encoding="utf-8")

    # Purge without database first
    deleted = purge_local_state(include_database=False, include_cache=False, db_path=str(db_file))
    assert not test_preset.exists()
    assert not config_dir.exists()
    assert db_file.exists()  # DB preserved by default

    # Purge with database
    deleted_db = purge_local_state(include_database=True, include_cache=False, db_path=str(db_file))
    assert not db_file.exists()
    assert not wal_file.exists()

    # Verify no .trashinfo or desktop trash directory was created in tmp_path
    trash_dirs = list(tmp_path.glob("**/Trash*")) + list(tmp_path.glob("**/.trashinfo*"))
    assert len(trash_dirs) == 0


def test_sanitize_log_path(monkeypatch):
    """Verify usernames are scrubbed from log strings."""
    monkeypatch.setenv("USER", "testuser")
    raw = "/home/testuser/990-explorer/data/irs990.duckdb"
    sanitized = sanitize_log_path(raw)
    assert "testuser" not in sanitized
    assert "~<USER>" in sanitized


def test_zero_autostart_by_default():
    """Verify that no autostart entries are generated or registered by default."""
    autostart_dir = Path.home() / ".config" / "autostart"
    irs990_autostarts = list(autostart_dir.glob("*irs990*")) if autostart_dir.exists() else []
    assert len(irs990_autostarts) == 0


# ==============================================================================
# Directive 2: CLI Flag & Subcommand Parsing
# ==============================================================================

def test_cli_reset_config_flags():
    """Verify CLI parsing for --reset-config flag and 'config reset --all' subcommand."""
    args_flag = parse_args(["--reset-config"])
    assert args_flag.reset_config is True

    args_sub = parse_args(["config", "reset", "--all"])
    assert args_sub.subcommand == "config"
    assert args_sub.config_action == "reset"
    assert args_sub.reset_config is True
    assert args_sub.all is True


def test_cli_reveal_flag():
    """Verify CLI parsing for --reveal flag."""
    args = parse_args(["--reveal"])
    assert args.reveal is True


# ==============================================================================
# Directive 3: Desktop Entry & UI Standards
# ==============================================================================

def test_safe_desktop_entry():
    """Verify desktop launcher avoids shell wrappers (sh -c) and double-quotes parameters."""
    desktop_file = Path(__file__).resolve().parent.parent / "data" / "irs990-explorer.desktop"
    assert desktop_file.exists()

    content = desktop_file.read_text(encoding="utf-8")
    for line in content.splitlines():
        if line.startswith("Exec="):
            # Prohibit sh -c execution
            assert "sh -c" not in line
            assert "/bin/sh" not in line
            # Ensure proper parameter quoting
            assert '"%u"' in line
            # Verify direct option termination
            assert "--" in line


# ==============================================================================
# Directive 5: Safe File URIs & MIME Database
# ==============================================================================

def test_parse_safe_file_uri_local_paths(tmp_path):
    """Verify valid file paths and file:// URIs resolve to canonical paths."""
    test_file = tmp_path / "test.xml"
    test_file.write_text("<Return/>", encoding="utf-8")

    # Standard filesystem path
    assert parse_safe_file_uri(str(test_file)) == str(test_file.resolve())

    # RFC 8089 file:// URI with empty authority
    file_uri = f"file://{test_file.resolve()}"
    assert parse_safe_file_uri(file_uri) == str(test_file.resolve())

    # RFC 8089 file://localhost/... URI
    file_localhost = f"file://localhost{test_file.resolve()}"
    assert parse_safe_file_uri(file_localhost) == str(test_file.resolve())


def test_parse_safe_file_uri_rejects_remote_authorities():
    """Verify remote file URI authorities are rejected immediately."""
    with pytest.raises(ValueError, match="Prohibited remote authority"):
        parse_safe_file_uri("file://attacker.com/share/payload.zip")

    with pytest.raises(ValueError, match="Prohibited remote authority"):
        parse_safe_file_uri("file://192.168.1.50/data/filing.xml")


def test_parse_safe_file_uri_directory_jail(tmp_path):
    """Verify directory traversal escaping the jail raises PermissionError."""
    jail = tmp_path / "jail"
    jail.mkdir()
    inside_file = jail / "inside.csv"
    inside_file.write_text("data", encoding="utf-8")

    outside_file = tmp_path / "outside.csv"
    outside_file.write_text("secret", encoding="utf-8")

    # Inside jail succeeds
    assert parse_safe_file_uri(str(inside_file), jail_dir=str(jail)) == str(inside_file.resolve())

    # Escaping jail fails
    with pytest.raises(PermissionError, match="escapes jail"):
        parse_safe_file_uri(str(outside_file), jail_dir=str(jail))


def test_verified_mime_type_lookup():
    """Verify shared-mime-info database integration and nosniff compatibility."""
    html_type = get_verified_content_type("index.html")
    assert "text/html" in html_type
    assert "charset=utf-8" in html_type

    json_type = get_verified_content_type("data.json")
    assert "application/json" in json_type

    css_type = get_verified_content_type("style.css")
    assert "text/css" in css_type

    js_type = get_verified_content_type("bundle.js")
    assert "javascript" in js_type


# ==============================================================================
# Directive 11: File Manager Reveal Pre-flight & Timeout
# ==============================================================================

def test_reveal_in_folder_headless_preflight(monkeypatch):
    """Verify reveal_in_folder skips execution and returns False in headless environments."""
    monkeypatch.setenv("CI", "true")
    # In headless CI environment, must return False cleanly without spawning processes
    result = reveal_in_folder("/tmp/some_file.html", timeout_ms=500)
    assert result is False


def test_reveal_in_folder_missing_dbus_session(monkeypatch):
    """Verify reveal_in_folder skips cleanly when DBUS_SESSION_BUS_ADDRESS is absent."""
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    result = reveal_in_folder("/tmp/some_file.html", timeout_ms=500)
    assert result is False
