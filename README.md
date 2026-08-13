# LOCALCLOUD

LOCALCLOUD lets you use your computers and services together. It discovers what
already exists, reaches hosts locally or through SSH, and exposes one small set
of actions to Python, humans at a CLI, and AI agents through MCP.

LOCALCLOUD is the reference implementation of **AXP — Action Exchange
Protocol**, a tiny operational language for Resources, Capabilities, Actions,
Events, and Context. MCP, SSH, and the CLI are adapters around AXP rather than
the foundation.

It is a package, not a control-plane server. The base runtime is Python's
standard library. It does not install or require Docker, a database, an HTTP
service, or an agent on remote machines.

## Install and configure

Python 3.11 or newer is required. From a checkout:

```bash
python3 -m pip install -e .
cp localcloud.example.toml localcloud.toml
localcloud hosts
localcloud inspect server
```

`localcloud.toml` is deliberately ignored because it describes a specific
owner's machines. Use `LOCALCLOUD_CONFIG=/path/to/file.toml` or `--config` to
select another file.

## CLI

```text
localcloud hosts
localcloud inspect HOST
localcloud init [--host NAME=SSH_TARGET]
localcloud doctor
localcloud plugins
localcloud plugin NAME
localcloud relationships
localcloud create plugin NAME
localcloud create action resource.verb
localcloud create adapter NAME
localcloud run resource.verb --input '{"key":"value"}'
localcloud status HOST
localcloud services HOST
localcloud service status HOST SERVICE
localcloud service start|stop|restart HOST SERVICE --yes
localcloud logs HOST [SERVICE] --lines 100
localcloud copy SOURCE_HOST SOURCE DESTINATION_HOST DESTINATION
localcloud sync SOURCE_HOST SOURCE DESTINATION_HOST DESTINATION [--apply]
localcloud projects
localcloud project NAME
localcloud discover-projects HOST [ROOT ...]
localcloud actions
localcloud shutdown HOST --yes
localcloud mcp
```

`sync` is a dry run unless `--apply` is supplied. Destructive CLI actions
require `--yes`; their MCP tools require `confirm=true`.

## Python

```python
from localcloud import LocalCloud

cloud = LocalCloud("localcloud.toml")
result = cloud.run("service.status", host="server", service="caddy")
print(result.to_dict())
```

## MCP

Register this stdio command with an MCP client:

```json
{
  "mcpServers": {
    "localcloud": {
      "command": "localcloud",
      "args": ["--config", "/absolute/path/localcloud.toml", "mcp"]
    }
  }
}
```

The MCP adapter exposes the shared actions using underscore names such as
`host_info`, `service_status`, `service_restart`, `logs_read`, `file_copy`, and
`project_inspect`. It contains no separate host or service implementation.

## AXP 0.1

Every execution becomes a typed, serializable request and result:

```json
{"axp":"0.1","type":"action.request","action":"service.status","target":{"host":"server"},"input":{"host":"server","service":"caddy"}}
```

```json
{"axp":"0.1","type":"action.result","action":"service.status","ok":true,"result":{"service":"caddy"}}
```

`localcloud.axp` defines Resource, Capability, ActionDefinition, ActionRequest,
ActionResult, Event, Context, and StructuredError. These are plain dataclasses;
AXP 0.1 adds no networking, negotiation, authentication, or storage system.

The in-process `EventRouter` supports exact or wildcard subscriptions. Core
actions emit `action.completed`/`action.failed` plus useful specific events such
as `service.started`, `file.copied`, and `host.shutdown_requested`. Plugins and
future interfaces can subscribe or emit without an event broker.

## Credentials and connections

LOCALCLOUD stores references, not secret values:

```toml
[credentials.provider]
kind = "provider"
source = "environment"
reference = "PROVIDER_API_TOKEN"
scopes = ["read"]
```

Values are re-read when an action needs them, so replacing an environment value
requires no code or configuration change. `doctor` reports configured,
available, source, and reference status without resolving or printing values.
Nested sensitive fields and known credential values are redacted at the shared
AXP result boundary.

`Connection` records say how a Resource is reached. Built-in adapters are
local, SSH, bounded HTTPS/API, outbound webhook, and MCP stdio. The HTTP adapter
requires HTTPS except for explicitly allowed localhost use, injects referenced
credentials only at execution, strips sensitive response headers, redacts
response data, limits responses to 256 KiB, and bounds timeouts.

An existing MCP server can become namespaced AXP actions:

```toml
[[connections]]
id = "existing_tools"
adapter = "mcp_stdio"
command = ["python3", "/absolute/path/server.py"]
```

Its implementation stays in that MCP server. LOCALCLOUD performs initialize,
discovers tools, and adapts them as actions such as
`existing_tools.some_tool`. It does not run a federation service.

## Architecture

```text
Python / CLI / MCP
        |
 shared ActionRegistry
        |
 Hosts -- Projects -- portable TOML context
        |
 local or SSH Transport
        |
 discovered host software
```

- `models.py`: configured Hosts, Projects, and project locations.
- `axp.py`: typed AXP 0.1 exchange structures.
- `events.py`: synchronous AXP event router.
- `transports.py`: local subprocess and existing SSH aliases.
- `discovery.py`: dependency-free remote probe executed in memory.
- `actions.py`: shared action contracts and implementations.
- `cloud.py`: public Python facade.
- `cli.py`: human interface.
- `protocol.py`: dependency-free MCP JSON-RPC/stdio adapter.
- `plugins.py`: optional `localcloud.plugins` Python entry-point contract.
- `credentials.py`: lazy environment references and shared redaction.
- `adapters/`: local, SSH, HTTPS/API, webhook, and MCP stdio connections.
- `scaffold.py`: small plugin, action, and adapter generators.

Configured Project records relate development, production, services, domains,
archives, and context. Discovery remains authoritative for installed host
capabilities. TOML context is structured data that can later render documents
such as AGENTS.md; generated Markdown is not the source of truth.

## Dependencies

Required:

- Python 3.11+
- SSH client only when an SSH host is configured
- Python 3 on a remote host for discovery

Capability-specific:

- `scp` for file copy involving SSH hosts
- `rsync` on both participating hosts for file sync
- `systemctl` for systemd service actions and journald for log actions
- Git for repository inspection

LOCALCLOUD reports a missing capability instead of installing it.

## Plugins

A plugin is a Python entry point in the `localcloud.plugins` group. Its loaded
object implements `setup(api)`. The API can register actions, subscribe to or
emit events, and contribute resources, capabilities, or contexts. Older
`register(action_registry)` plugins remain supported.

The bundled optional `discord_webhook` plugin demonstrates AXP event delivery
to an external provider without an SDK. Enable it in TOML and place the URL in
the configured environment variable. The URL is never stored in configuration
or returned to callers.

Plugins publish inspectable metadata: name, version, description, AXP
compatibility, resources/actions/events, optional dependencies, and credential
requirements. Metadata inspection does not invoke plugin actions.

## Relationships and extension scaffolds

`localcloud relationships` returns AXP `ResourceRelationship` records. Project
locations automatically become relationships such as `developed_on`,
`runs_on`, and `backed_up_to`; arbitrary relationships may be declared in TOML.
There is no graph database.

`localcloud create plugin|action|adapter NAME` writes two to four small files.
The plugin scaffold is an installable entry-point package with metadata, one
example AXP action, a lazy credential-reference example, and a test. Generated
actions and adapters similarly contain one implementation and one test.
Once installed, plugin actions automatically appear in Python and MCP, and are
available to humans through `localcloud run`. Destructive actions still require
`--yes`.

## First run and diagnosis

`localcloud init` discovers the local host, prints its capabilities, optionally
accepts and validates SSH hosts, and writes minimal TOML. It never installs
software. `localcloud doctor` validates configuration, connectivity, host
capabilities, missing optional commands, plugin health, and MCP tool creation.

## Safety

There is no raw-shell action. Arguments are passed as argv locally and are
shell-quoted for SSH. Services and host names are validated. Secrets are not
part of the configuration schema or discovery output. LOCALCLOUD never installs
remote software during inspection.
