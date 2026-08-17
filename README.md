<div align="center">

# ⚡ APX — Universal Action Protocol & Capability Fabric

**A deterministic, permissioned capability and action protocol for humans, AI agents, applications, and machines.**

[![License: MPL 2.0](https://img.shields.io/badge/License-MPL_2.0-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11%2B-brightgreen.svg)](pyproject.toml)
[![Protocol: 0.1](https://img.shields.io/badge/Protocol-APX_0.1-orange.svg)](spec/protocol.md)

</div>

---

## Quickstart

### Installation

```bash
# Install via pip
pip install git+https://github.com/JoshDeanPro/apx.git

# Or install locally in editable mode
git clone https://github.com/JoshDeanPro/apx.git
cd apx
pip install -e .
```

### Configuration & First Run

```bash
# 1. Initialize configuration
apx init

# 2. List available actions
apx actions

# 3. Inspect system hardware and capabilities
apx hardware

# 4. View settings and runtime environment
apx settings show
```

---

## The APX Protocol

APX provides a typed, self-describing, and permissioned capability fabric across machines, services, and applications.

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                                    THE APX PROTOCOL                                      │
├──────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                          │
│   1. DISCOVER   ──►  Query registered actions, schemas, and provider capabilities        │
│   2. PREPARE    ──►  Determine preconditions, inputs, costs, and risk profile            │
│   3. AUTHORIZE  ──►  Evaluate scoped policy decisions and required confirmations         │
│   4. EXECUTE    ──►  Deterministic, idempotent action execution                          │
│   5. VERIFY     ──►  Emit immutable, cryptographically verifiable action receipts        │
│                                                                                          │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

- **Deterministic Execution**: Pure standard Python execution without arbitrary heuristics. Validates schema inputs and returns typed outputs.
- **Capability Graph**: Typed `Resources`, `Connections`, `Grants`, and `Policy` rules establish clear security boundaries.
- **Multi-Transport**: Unified action dispatch across the **`apx` CLI**, **MCP (Model Context Protocol)**, **Python SDK**, and **HTTP Server**.

---

## Python SDK

```python
from apx import APX

# Initialize APX engine
apx = APX()

# 1. Query registered actions
actions = apx.actions.list()
print(f"Available actions: {len(actions)}")

# 2. Execute an action
result = apx.run(
    "host.status",
    host="local"
)

if result.ok:
    print("Action output:", result.result)
else:
    print("Action failed:", result.error)
```

---

## Model Context Protocol (MCP) Interoperability

APX provides a native Model Context Protocol (MCP) server over stdio, exposing registered APX actions directly as MCP tools:

```json
{
  "mcpServers": {
    "apx": {
      "command": "apx",
      "args": ["mcp"]
    }
  }
}
```

To run with a custom configuration or actor:

```bash
apx --config /path/to/apx.toml mcp --actor agent:worker:node-1
```

---

## CLI Reference

| Command | Description |
|:---|:---|
| `apx init` | Initialize minimal local APX configuration |
| `apx actions` | List registered actions in the catalog |
| `apx action inspect <name>` | Inspect action schema, parameters, and risk level |
| `apx run <action> [--input ...]` | Execute a registered action |
| `apx mcp` | Launch standard MCP server over stdio |
| `apx serve [--port ...]` | Expose action registry over HTTP provider transport |
| `apx discover` | Perform protocol DISCOVER operation |
| `apx policy explain <actor> <action>` | Explain policy decision for an actor and action |
| `apx grant <issue\|list\|show\|revoke>` | Manage scoped capability grants |
| `apx secret <get\|set\|reveal\|rotate>` | Inspect and manage credentials |
| `apx hardware` | Inspect local compute capacity and accelerators |
| `apx settings <show\|get\|set>` | Manage APX runtime configuration |
| `apx conformance` | Run protocol conformance suite |

---

## Testing

Run the test suite with `pytest`:

```bash
pytest
```

---

## License

APX is licensed under the **Mozilla Public License 2.0 (MPL-2.0)**. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE) for details.

Copyright (c) 2026 JoshDeanPro
