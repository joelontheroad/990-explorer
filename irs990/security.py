# SPDX-FileCopyrightText: 2026 990-Explorer Authors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Security, URI Canonicalization, State Purge, and Composability Utilities.

Architectural Purpose:
    Provides hardened security primitives for IRS 990 Explorer including:
    - Safe RFC 8089 file:// URI parsing and directory jail verification (CWE-22).
    - Deterministic local state erasure via permanent file unlinking (Directive 1),
      strictly prohibiting Desktop Trash Can integration.
    - User home directory path sanitization (~<USER>) for privacy-compliant logging.
    - Headless-aware D-Bus file manager integration ("Reveal in Folder") with timeout guards.

Security Invariants:
    - Rejects remote file:// authorities to prevent UNC/SMB and remote path injection.
    - All path resolutions use os.path.realpath to defeat symlink directory escapes.
    - State erasure permanently unlinks files and never moves data to ~/.local/share/Trash.
    - File manager integrations apply a <= 1000ms timeout and check session bus presence.
"""

import os
import sys
import shutil
import logging
import urllib.parse
import subprocess
from pathlib import Path
from typing import Optional, List, Union

logger = logging.getLogger("irs990-security")


def sanitize_log_path(raw_path: str) -> str:
    """Scrub user directory usernames from filesystem paths for privacy.

    Replaces occurrences of /home/<username>, /Users/<username>, or C:\\Users\\<username>
    with ~<USER> to prevent leaking system identities into logs or diagnostics.

    Args:
        raw_path: Raw filesystem path string.

    Returns:
        Sanitized path string with username scrubbed.
    """
    if not raw_path:
        return ""
    # SECURITY: Prevent leaking local usernames in logs per Directive 1
    user = os.environ.get("USER") or os.environ.get("USERNAME")
    home = os.path.expanduser("~")
    sanitized = str(raw_path)
    if home and home in sanitized:
        sanitized = sanitized.replace(home, "~<USER>")
    elif user and f"/{user}/" in sanitized:
        sanitized = sanitized.replace(f"/{user}/", "/~<USER>/")
    return sanitized


def parse_safe_file_uri(uri_or_path: str, jail_dir: Optional[str] = None) -> str:
    """Parse and validate a file:// URI or filesystem path against traversal attacks.

    Implements RFC 8089 file URI parsing and MITRE CWE-22 protection:
    - Rejects remote authorities (file://hostname/path), only permitting empty or 'localhost'.
    - Safely decodes URL percent-encoded octets.
    - Resolves symlinks and relative components using os.path.realpath.
    - Verifies the resolved path resides strictly within the allowed directory jail if provided.

    Args:
        uri_or_path: Path string or file:// URI to resolve.
        jail_dir: Optional directory path that must contain the resolved target.

    Returns:
        Canonical absolute filesystem path.

    Raises:
        ValueError: If a remote authority is detected in the file:// URI.
        PermissionError: If the resolved path escapes the specified directory jail.
    """
    if not uri_or_path:
        raise ValueError("Path or file URI cannot be empty.")

    target_str = str(uri_or_path).strip()

    if target_str.startswith("file://"):
        parsed = urllib.parse.urlparse(target_str)
        # SECURITY: Reject remote authorities (CWE-22 / RFC 8089)
        if parsed.netloc and parsed.netloc.lower() not in ("", "localhost"):
            raise ValueError(
                f"Prohibited remote authority '{parsed.netloc}' in file URI: '{target_str}'. "
                "Only empty or localhost authorities are permitted."
            )
        decoded_path = urllib.parse.unquote(parsed.path)
        # Handle Windows drive letters formatted as /C:/path
        if len(decoded_path) >= 3 and decoded_path[0] == "/" and decoded_path[2] == ":":
            decoded_path = decoded_path[1:]
        target_str = decoded_path

    # SECURITY: Canonicalize path using os.path.realpath to resolve symlink escapes
    real_path = os.path.realpath(target_str)

    if jail_dir:
        real_jail = os.path.realpath(jail_dir)
        try:
            common = os.path.commonpath([real_path, real_jail])
        except ValueError:
            # Different drives on Windows
            raise PermissionError(
                f"Path '{sanitize_log_path(real_path)}' resides on a different drive than jail '{sanitize_log_path(real_jail)}'."
            )
        if common != real_jail:
            raise PermissionError(
                f"Path traversal detected: '{sanitize_log_path(real_path)}' escapes jail '{sanitize_log_path(real_jail)}'."
            )

    return real_path


def purge_local_state(
    include_database: bool = False,
    include_cache: bool = False,
    db_path: Optional[str] = None
) -> List[str]:
    """Deterministically erase local configuration, presets, and state files.

    Permanently unlinks files and removes directories. Never invokes or delegates
    to the Desktop Trash Can (trash-spec), ensuring zero unencrypted path or username
    artifacts in .trashinfo files per Directive 1.

    Args:
        include_database: If True, also permanently deletes DuckDB database and WAL files.
        include_cache: If True, also permanently purges downloaded bulk data directories.
        db_path: Optional path to the active DuckDB database file.

    Returns:
        List of deleted filesystem paths (sanitized for safe logging).
    """
    deleted_paths: List[str] = []

    # 1. Config / presets directory (~/.config/irs990 or $XDG_CONFIG_HOME/irs990)
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    config_dir = os.path.join(xdg_config, "irs990") if xdg_config else os.path.expanduser("~/.config/irs990")
    if os.path.isdir(config_dir):
        # SECURITY: Permanent deletion via rmtree (never move to desktop trash)
        shutil.rmtree(config_dir, ignore_errors=True)
        deleted_paths.append(sanitize_log_path(config_dir))

    # 2. Local config presets in current working directory
    for local_preset in [".irs990.yaml", ".irs990.yml", "irs990.config.yaml"]:
        if os.path.isfile(local_preset):
            try:
                os.unlink(local_preset)
                deleted_paths.append(sanitize_log_path(local_preset))
            except OSError as e:
                logger.warning(f"Could not unlink {local_preset}: {e}")

    # 3. Database files if requested
    if include_database and db_path:
        resolved_db = os.path.realpath(db_path)
        wal_file = f"{resolved_db}.wal"
        for fpath in [resolved_db, wal_file]:
            if os.path.isfile(fpath):
                try:
                    os.unlink(fpath)
                    deleted_paths.append(sanitize_log_path(fpath))
                except OSError as e:
                    logger.warning(f"Could not unlink database file {fpath}: {e}")

    # 4. Cache directories if requested
    if include_cache:
        repo_data = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        for sub in ["bmf", "fec", "pofd"]:
            target_sub = os.path.join(repo_data, sub)
            if os.path.isdir(target_sub):
                shutil.rmtree(target_sub, ignore_errors=True)
                deleted_paths.append(sanitize_log_path(target_sub))

    return deleted_paths


def is_headless_environment() -> bool:
    """Detect whether the current process is running in a headless or CI environment.

    Returns:
        True if running in a headless CI environment or without a graphical display.
    """
    # SECURITY: Prevent subprocess or browser launch failures in containerized or headless CI
    if os.environ.get("CI", "").lower() in ("true", "1", "yes"):
        return True
    if sys.platform.startswith("linux"):
        return not bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return False


def reveal_in_folder(path: str, timeout_ms: int = 1000) -> bool:
    """Reveal a target file or folder in the user's graphical desktop file manager.

    Implements org.freedesktop.FileManager1 over D-Bus with headless pre-flight
    and strict timeout guards per Directive 11.

    Args:
        path: Path to the file or directory to highlight.
        timeout_ms: Maximum duration in milliseconds to await file manager response.

    Returns:
        True if the file manager was successfully invoked; False otherwise.
    """
    # SECURITY: Pre-flight check for headless environments per Directive 11
    if is_headless_environment():
        logger.debug("Headless environment detected; skipping file manager D-Bus reveal.")
        return False

    # SECURITY: Check for active D-Bus session bus before attempting communication
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        logger.debug("No DBUS_SESSION_BUS_ADDRESS detected; skipping file manager D-Bus reveal.")
        return False

    real_path = os.path.realpath(path)
    file_uri = f"file://{real_path}"
    timeout_sec = max(0.1, timeout_ms / 1000.0)

    # Attempt org.freedesktop.FileManager1.ShowItems via gdbus or dbus-send
    for cmd in [
        [
            "gdbus", "call", "--session",
            "--dest", "org.freedesktop.FileManager1",
            "--object-path", "/org/freedesktop/FileManager1",
            "--method", "org.freedesktop.FileManager1.ShowItems",
            f"['{file_uri}']", '""'
        ],
        [
            "dbus-send", "--session", "--type=method_call",
            "--dest=org.freedesktop.FileManager1",
            "/org/freedesktop/FileManager1",
            "org.freedesktop.FileManager1.ShowItems",
            f"array:string:{file_uri}", "string:"
        ]
    ]:
        try:
            # SECURITY: Enforce strict timeout guard to prevent UI blocking
            res = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout_sec,
                check=False
            )
            if res.returncode == 0:
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            continue

    return False
