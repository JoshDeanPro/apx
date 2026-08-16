<div align="center">

# ⚡ APX — Universal Action Protocol & Capability Fabric

**A deterministic, permissioned capability and action protocol for humans, AI agents, applications, and machines.**

[![License: MPL 2.0](https://img.shields.io/badge/License-MPL_2.0-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11%2B-brightgreen.svg)](pyproject.toml)
[![Protocol: 0.1](https://img.shields.io/badge/Protocol-APX_0.1-orange.svg)](spec/protocol.md)
[![Docs](https://img.shields.io/badge/Docs-openpower.dev%2Fapx-indigo.svg)](https://openpower.dev/apx)

</div>

---

## 🚀 Quickstart (Copy & Paste)

Get up and running with APX in seconds:

### Install in 1 Line

```bash
# macOS, Linux, WSL
curl -fsSL https://openpower.dev/install | sh
```

```powershell
# Windows PowerShell
irm https://openpower.dev/install.ps1 | iex
```

### Or Install via Python / Git

```bash
# Direct pip install
pip install git+https://github.com/JoshDeanPro/apx.git

# Or clone from source (development checkout)
git clone https://github.com/JoshDeanPro/apx.git
cd apx
pip install -e .
cp apx.example.toml apx.toml
```

### Verify & Run Your First Actions

```bash
# 1. Self-diagnosis and health check
apx doctor

# 2. Inspect configured hosts
apx hosts

# 3. Read host status (safe, read-only action)
apx status workstation

# 4. Discover the entire live action catalog
apx actions

# 5. Launch the interactive TUI
apx
```

---

## 🧠 What is APX? (The Protocol Explained)

AI models have intelligence, but letting them run arbitrary raw shell commands or scrape brittle endpoints is insecure and fragile. **APX** turns capabilities across computers, applications, devices, and cloud services into a **single, typed, self-describing, and permissioned Action Fabric**.

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                                    THE APX PROTOCOL                                      │
├──────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                          │
│   1. DISCOVER   ──►  An agent queries what actions actually exist and their schemas      │
│   2. PREPARE    ──►  Calculates side effects, costs, and state preconditions             │
│   3. AUTHORIZE  ──►  Scoped policy evaluation (or explicit human confirmation)           │
│   4. EXECUTE    ──►  Idempotent single execution via deterministic Python engine         │
│   5. VERIFY     ──►  Generates a structured, immutable receipt of the completed action   │
│                                                                                          │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

- **Deterministic Execution Plane**: Runs purely on Python's standard library with zero AI provider dependencies. The engine does not guess or hallucinate parameters; it executes validated actions against real resources.
- **Zero-Trust Capability Graph**: Machines, databases, services, and APIs are registered as typed `Resources`. Every operation is governed by explicit `Policy`.
- **Universal Interface**: One shared action dispatch path serves the **`apx` CLI**, **MCP (Model Context Protocol)**, **Python SDK**, **Voice**, and **HTTP endpoints**.

---

## 🎨 Visual Protocol Architecture

```
                                  CALLERS & AGENTS
     ┌───────────────────┬───────────────────┬───────────────────┬───────────────────┐
     │     Human CLI     │    AI via MCP     │    Python SDK     │    HTTP Server    │
     │    `apx run ...`  │   `apx mcp`       │  `from apx import`│   `apx serve`     │
     └─────────┬─────────┴─────────┬─────────┴─────────┬─────────┴─────────┬─────────┘
               │                   │                   │                   │
               └───────────────────┼───────────────────┴───────────────────┘
                                   ▼
 ═══════════════════════════════════════════════════════════════════════════════════════════
                               APX EXECUTION ENGINE
 ═══════════════════════════════════════════════════════════════════════════════════════════
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
     ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
     │ Action Registry │  │  Policy Engine  │  │ Capability Graph│
     │ • Input Schemas │  │ • Allow / Deny  │  │ • Discovery     │
     │ • Risk Metadata │  │ • Scoped Tokens │  │ • Relationships │
     └────────┬────────┘  └────────┬────────┘  └────────┬────────┘
              │                    │                    │
              └────────────────────┼────────────────────┘
                                   ▼
 ───────────────────────────────────────────────────────────────────────────────────────────
                               TRANSPORTS & BRIDGES
 ───────────────────────────────────────────────────────────────────────────────────────────
        │                  │                  │                  │                  │
        ▼                  ▼                  ▼                  ▼                  ▼
  ┌───────────┐      ┌───────────┐      ┌───────────┐      ┌───────────┐      ┌───────────┐
  │   Local   │      │    SSH    │      │ HTTP API  │      │ MCP Stdio │      │  Plugins  │
  │ Subprocess│      │ Remote    │      │ Verified  │      │ External  │      │ Python    │
  │ Transport │      │ Nodes     │      │ HTTPS     │      │ Tools     │      │ Extensions│
  └─────┬─────┘      └─────┬─────┘      └─────┬─────┘      └─────┬─────┘      └─────┬─────┘
        │                  │                  │                  │                  │
        └──────────────────┼──────────────────┼──────────────────┼──────────────────┘
                           ▼                  ▼
               ┌────────────────────────────────────────┐
               │         TARGET MACHINES & APIS         │
               │   • Hosts & Nodes    • Databases       │
               │   • System Services  • Cloud Providers │
               │   • Smart Devices    • Local Apps      │
               └────────────────────────────────────────┘
```

---

## 🔄 The 5-Step Action Lifecycle

Every state change in APX follows a deterministic, 5-phase lifecycle:

```
  ┌────────────┐       ┌────────────┐       ┌────────────┐       ┌────────────┐       ┌────────────┐
  │ 1. DISCOVER│  ──►  │ 2. PREPARE │  ──►  │3. AUTHORIZE│  ──►  │ 4. EXECUTE │  ──►  │ 5. RECEIPT │
  └────────────┘       └────────────┘       └────────────┘       └────────────┘       └────────────┘
     Ask what             Preview the          Verify actor          Run exactly          Structured
    actions exist         consequences        permissions &          once with an        verifiable proof
    and what they         and baseline         confirmation          idempotency          of result &
       require               state                token                  key              new state
```

1. **`Discover`**: Caller inspects available `ActionDefinition` records, parameter types, and risk levels (`read_only`, `destructive`).
2. **`Prepare`**: Generates an execution plan, snapshots current authoritative state version, and computes impact.
3. **`Authorize`**: Evaluates policy against the `Actor` and `AuthContext`. Destructive operations require explicit confirmation.
4. **`Execute`**: Dispatches single execution through the resource transport using the idempotency key.
5. **`Verify & Receipt`**: Returns an immutable, signed `ActionReceipt` containing output, timing, and state mutations.

---

## 🛠️ Complete CLI Command Suite

```text
Discovery & Inspection:
  apx hosts                                # List configured machine Nodes
  apx inspect HOST                         # Deep probe of a host's capabilities & services
  apx actions                              # Inspect the entire live Action catalog
  apx resources                            # List all known system & cloud resources
  apx relationships                        # View relationships between projects and machines
  apx doctor                               # Comprehensive diagnosis of fleet, config & credentials

Execution & Control:
  apx status HOST                          # Read uptime, load, disk, and failed services
  apx services HOST                        # List running and enabled system services
  apx service status HOST SERVICE          # Check individual service status
  apx service restart HOST SERVICE --yes   # Restart a service safely
  apx logs HOST [SERVICE] --lines 100      # Tail filtered logs
  apx run ACTION --input '{"k":"v"}'       # Execute any registered action by name

Fleet Management & Sync:
  apx copy SRC_HOST SRC DST_HOST DST       # Copy files between any two nodes via scp
  apx sync SRC_HOST SRC DST_HOST DST       # Dry-run or apply rsync synchronization
  apx update                               # Fast, verified self-update of the APX installation
  apx push HOST                            # Build and push APX wheel to remote node over SSH

Scaffolding & Extensibility:
  apx create plugin NAME                   # Scaffold an installable Python plugin
  apx create action resource.verb          # Scaffold a new typed action
  apx create adapter NAME                  # Scaffold a custom transport adapter
  apx mcp                                  # Run standard MCP server over stdio for Claude/Codex
```

---

## 🐍 Python SDK Usage

Integrate APX directly into any Python program or agent runtime:

```python
from apx import APX

# Initialize with configuration
apx = APX("apx.toml")

# 1. Safe, read-only status query
status = apx.run("host.status", host="workstation")
print(f"Host online: {status.result['reachable']}")

# 2. Mutating action with policy and input validation
result = apx.run(
    "service.restart",
    host="vps",
    service="caddy",
    confirm=True
)

if result.ok:
    print(f"Service restarted successfully: {result.result}")
else:
    print(f"Action failed: {result.error}")
```

---

## 🔌 Model Context Protocol (MCP) Integration

Connect APX to **Claude Code**, **Codex**, **Cursor**, or any MCP-compatible AI client:

```json
{
  "mcpServers": {
    "apx": {
      "command": "apx",
      "args": ["--config", "/path/to/apx.toml", "mcp"]
    }
  }
}
```

APX exposes its registered actions as native, validated MCP tools (`host_status`, `service_restart`, `file_copy`, `project_inspect`, etc.) with zero glue code.

---

## 🔄 Self-Update Engine (`apx update` & `apx push`)

Keeping fleets in sync without broken dependencies is a first-class guarantee:

```
  DEVELOPMENT CHECKOUT                           INSTALLED RUNTIME (VENV/WHEEL)
  ┌──────────────────────────────┐              ┌──────────────────────────────┐
  │  `apx update`                │              │  `apx update`                │
  │  • Verifies clean working git│              │  • Upgrades from configured  │
  │  • Runs `git pull --ff-only` │              │    wheel / source location   │
  │  • Never rewrites local work │              │  • Re-verifies metadata      │
  └──────────────┬───────────────┘              └──────────────┬───────────────┘
                 │                                             │
                 └──────────────────────┬──────────────────────┘
                                        ▼
                           ┌───────────────────────────┐
                           │    FLEET PROPAGATION      │
                           │  `apx push remote-node`   │
                           │  • Builds local wheel     │
                           │  • Transfers over SSH/SCP │
                           │  • Updates remote runtime │
                           └───────────────────────────┘
```

- **`apx update` (Local)**:
  - On a development checkout: performs a clean `--ff-only` git pull. If the tree is dirty or diverged, it refuses to overwrite your work.
  - On an installed environment: upgrades the package cleanly from the configured source without calling untrusted third-party services.
- **`apx push HOST` (Fleet)**:
  - Builds an installable APX wheel from the current source tree and deploys it across configured SSH nodes automatically.

---

## 🌐 APX vs OpenPower

| Feature | **APX (This Repository)** | **OpenPower (openpower.dev)** |
|:---|:---|:---|
| **Nature** | Pure open-source framework & action protocol | Optional web dashboard & hosted services |
| **Dependencies** | Python standard library + 3 core packages | Web browser, Next.js dashboard, optional hosted account |
| **Requirements** | Zero account, zero telemetry, works 100% offline | Optional device linking (`apx link`) |
| **Architecture** | Direct local execution & SSH peer transport | Talks to local `apx serve` over loopback |
| **License** | Mozilla Public License 2.0 (MPL-2.0) | Proprietary / Commercial extensions |

APX operates completely independently. It imports nothing from OpenPower and requires no central account.

---

## 🛡️ Project Stewardship, AI Policy & Contributing

### Leadership & Maintainers

APX is stewarded under the **Founder-Steward** model:
- **Founder & Project Steward**: **Ethan Gegos** (Original author and sole project steward).
- **Current Contributors / Maintainers**: Ethan Gegos is the sole author and active maintainer at this time. There are no other maintainers or active contributors currently.

### Strict Human Authorship & Zero AI Credit Policy

- **No AI Attribution**: AI models, assistants, or LLMs are not authors, copyright holders, or contributors of record. No credit or co-authorship is given to AI tools in commit logs, notices, or release rosters.
- **Human Responsibility**: Any human submitting a pull request is 100% responsible for the correctness, security, licensing, and behavior of their submission. See [`AI_POLICY.md`](AI_POLICY.md).

### Contributing & Branch Protection

We welcome community pull requests, bug fixes, custom providers, and plugins!

1. Fork the repo and create your feature branch.
2. Ensure all tests pass (`pytest`).
3. Submit a Pull Request on GitHub.
4. **Steward Review**: The `main` branch is protected. No pull requests are merged automatically. Every change requires manual review and approval by the Project Steward (**Ethan Gegos**).

See [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`GOVERNANCE.md`](GOVERNANCE.md) for full details.

---

## 📄 License & Notice

APX is licensed under the **Mozilla Public License 2.0 (MPL-2.0)**. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE) for details.

Copyright (c) 2026 Ethan Gegos.
