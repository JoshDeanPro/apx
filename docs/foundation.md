# APX Foundation and Dependency Policy

APX installs capability, not a developer workstation. Its foundation is intentionally divided into three levels and described in `apx.foundation.COMPONENTS`.

## Core Python dependencies

| Dependency | Purpose | Why required |
|---|---|---|
| `httpx==0.28.1` | Shared pooled HTTPS client | Replaces separate `urllib` implementations with consistent verified TLS, proxy/environment support, streaming limits, timeouts, redirect policy, errors, and idempotency-aware retries. |
| `jsonschema==4.26.0` | Draft 2020-12 validation | Action and Provider schemas are interoperability and security boundaries. A mature validator avoids an incomplete custom implementation. |
| `platformdirs==4.11.2` | Correct OS paths | Correctly locates user config, state, data, and logs on macOS, Linux, and other Python platforms without hand-maintained path guesses. |

APX does not require Pydantic, a CLI framework, terminal rendering, `cryptography`, or `psutil`. Dataclasses remain the transport-neutral model representation. APX does not currently perform signatures itself, so adding cryptography would provide no used capability. The existing bounded discovery probe is smaller than a permanent system-inspection dependency.

Required packages must be mature, actively maintained, portable, security-conscious, broadly adopted, narrowly scoped, and remove meaningful custom or security-sensitive code. Packages are not added for string handling, JSON encoding, timestamps, UUIDs, basic subprocess calls, retries, or filesystem walking.

Production installation applies reviewed constraints to transitive dependencies. Release wheels and constraint files are described by SHA-256 in manifests; downloads require verified HTTPS.

This follows the isolation guidance in the [Python Packaging specification for externally managed environments](https://packaging.python.org/en/latest/specifications/externally-managed-environments/) and borrows the isolated-tool pattern documented by [`uv tool install`](https://docs.astral.sh/uv/guides/tools/). APX does not require uv at runtime. The installer uses the standard library `venv` available on the host, keeping bootstrap auditable and avoiding a second package manager when it is unnecessary.

The [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) is deliberately not an APX Core dependency: APX’s existing stdio MCP adapter is small and protocol-scoped. Applications that need the full MCP framework may install it separately. Modern isolated-install patterns allow users to invoke stable commands while runtime details remain isolated.

## System capabilities

- Foundation: Python 3.11+ and working CA trust/TLS.
- Recommended: Git, OpenSSH, and curl.
- Optional boosters: rsync for optimized synchronization and ripgrep for fast search.

APX detects existing capabilities before use. It never initializes Git repositories, generates SSH keys, changes `sshd`, opens ports, weakens host verification, or disables TLS verification. Missing rsync does not break APX; `file.copy` remains available. Missing ripgrep falls back to native discovery. The installer does not automatically install operating-system packages.

Docker, Podman, Node.js, databases, web servers, Kubernetes, Terraform, Ansible, observability stacks, FFmpeg, model runtimes, and browser automation are discoverable resources—not foundation dependencies.

## Shared primitives

- `apx.http.HTTPClient`: verified HTTPS, pooled connections, bounded responses, safe redirects, environment proxies, a standard `APX/<version>` user agent, and retries only for safe/idempotent calls.
- `apx.process.run`: argument arrays, `shell=False`, timeout, bounded stdout/stderr, working directory, controlled environment injection, and structured results.
- `apx.files`: normalized paths, bounded reads, advisory locks, `fsync`, permission control, and atomic replace.
- `apx.observability`: human or JSON logs containing request/action/provider/status/timing identifiers but no action payloads or secrets.
- `apx.foundation`: one capability and health source consumed by clients.

SQLite remains available in the Python standard library. Atomic locked writes solve durability requirements without introducing an external database or migration burden.
