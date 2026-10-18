# Rule: Software Engineering Standards for Local Utilities

> Applied automatically to all code authoring, refactoring, and project generation tasks.

You MUST adhere to the 12 Software Engineering Standards defined in `STANDARDS.md` and `AGENTS.md`:

1. **Privacy**: Zero telemetry; 100% local data residency; scrub usernames (`~<USER>`) from logs; provide `--reset-config`.
2. **Licensing**: GNU AGPL-3.0-or-later; SPDX headers on all files; single-source versioning; AGPLv3 Section 13 source link in Web UI and CLI.
3. **UI / CLI**: POSIX/GNU flags (`-h`, `-v`, `-q`, `--verbose`, `--config`, `--json`, `--no-browser`); `stdout` for data, `stderr` for logs; honor `NO_COLOR`; clickable terminal URLs (OSC 8); automatic browser opening for web servers; WCAG 2.1 AA accessible local web UI with ZERO external CDNs.
4. **Configuration**: XDG base directory conformance; YAML presets with comments; Pydantic/Zod schema validation; 5-tier precedence hierarchy.
5. **Cybersecurity**: Local web server binds strictly to `127.0.0.1`; generate ephemeral startup launch token; strict W3C CSP & security headers; MITRE CWE Top 25 (safe `yaml.safe_load`, canonicalize paths to prevent traversal, parameterized arguments to prevent command injection); POSIX `0700` directory and `0600` file permissions; NIST CSPRNG (`secrets` / `crypto.randomBytes`).
6. **Supply Chain**: Pinned GitHub Action SHAs; dependency audit; secret scanning; SLSA provenance & SHA-256 checksums; SBOM generation.
7. **Testing**: Subprocess CLI tests for exit codes and stream separation; isolated temporary directory fixtures (`tmp_path`).
8. **Logging & Errors**: Standard exit codes (`0`, `1`, `2`, `130`); concise error messages without stack traces unless `--debug` is active.
9. **Portability**: Explicit `encoding="utf-8"` on all file I/O; ISO 8601 UTC timestamps; `pathlib.Path` / `node:path`; Git LF line endings.
10. **Performance & Process**: Fast startup (<200ms); lazy imports for web servers/heavy modules; streaming file I/O; graceful `SIGINT`/`SIGTERM` handling (exit `130`).
11. **Composability**: Support `-` for stdin piping; `--json` flag for machine-readable output.
12. **Documentation**: Standard 6-part `README.md`; `SECURITY.md` private disclosure policy; structured docstrings (Google Style / JSDoc); lean typing without redundancy; "why, not what" comment discipline; strict comment preservation.
