# OpenPower architecture: APX vs LocalCloud

OpenPower contains two distinct layers that must remain independently usable.

## APX

APX is the protocol and action fabric. It owns:

- action request/result/receipt schemas
- capability and resource descriptions
- policy, grants, identity and authorization semantics
- provider discovery and conformance
- transports/adapters
- MCP and HTTP protocol exposure
- the Python API used to register and invoke Actions

APX must not require the LocalCloud runtime, the interactive TUI, a fleet, a
credential vault, or the openpower.dev website.

The public `apx` command is therefore protocol-oriented. Running `apx` with no
arguments prints help; it does not launch a product UI.

## OpenPower LocalCloud

LocalCloud is the operational runtime built on APX. It owns:

- the interactive/local OpenPower environment
- host and fleet orchestration
- host-sovereign credential/state storage
- local runtime and machine operations
- LocalCloud mesh state and failover behavior

Its Python namespace is `openpower.localcloud` and its command is `localcloud`.

```python
from openpower.localcloud import LocalCloud

cloud = LocalCloud("/etc/openpower/localcloud.toml")
result = cloud.run("service.status", actor="human:owner", host="mac", service="example")
```

## Compatibility window

During the 0.8 transition:

- `from localcloud import LocalCloud` re-exports `openpower.localcloud.LocalCloud`
- `apx.localcloud` re-exports the LocalCloud vault functions for old callers
- operational CLI commands can temporarily pass through the legacy APX command
  implementation when invoked from `localcloud`

These are one-way compatibility shims. New LocalCloud code must not be added to
`apx.*`.

## State migration

LocalCloud state moves from `~/.apx/localcloud` to
`~/.openpower/localcloud`. The runtime performs a one-time same-filesystem rename
when the new location does not yet exist. If the rename is not possible, the
legacy directory is left untouched rather than risking credential loss.
