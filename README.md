# APX

APX lets you use your computers and services together. It discovers what
already exists, reaches hosts locally or through SSH, and exposes one small set
of actions to Python, humans at a CLI, and AI agents through MCP.

APX is the reference implementation of **AXP — Action Exchange
Protocol**, a tiny operational language for Resources, Capabilities, Actions,
Events, and Context. MCP, SSH, and the CLI are adapters around AXP rather than
the foundation.

It is a package, not a control-plane server. The base runtime is Python's
standard library. It does not install or require Docker, a database, an HTTP
service, or an agent on remote machines.

## APX vs OpenPower

APX is the open-source framework: Resources, Actions, Events, Context, the
Action Registry, and the Policy engine. It works completely on its own, on
one machine, with zero account and zero network dependency.

[OpenPower](https://openpower.one) is an optional product built on top of
APX (separate repository) — a website, a server, and a per-machine installer
(`op`) that add device linking, an optional hosted account, and remote
dispatch between your own machines. OpenPower depends on APX; APX never
depends on OpenPower, imports nothing from it, and has no code that talks to
`openpower.one`. The only place APX even knows the name "OpenPower" is one
explicitly-optional, unconfigured-by-default auth adapter
(`auth_openpower.py`) that verifies OpenPower-issued identity tokens — the
same generic `AuthContext` shape any other identity provider would produce.

## Working now / deferred

Working now: the Action Registry and self-description (`apx actions`),
Resource/Actor/Policy primitives (`axp.py`, `policy.py`, `identity.py`),
local + SSH transports, discovery, plugins, credentials-by-reference,
Missions/Tasks (`apx mission`, `apx task`), Projects/Relationships, and the
MCP adapter — all going through the one shared `APX.run()` dispatch path.

Deferred: a unified machine-readable schema endpoint beyond `apx actions`
(risk/permission metadata per action is on the roadmap, not yet exposed),
richer HumanProfile/MachineProfile beyond the current AgentProfile/actor
model, and asymmetric (RS256/EdDSA) JWT verification for the OpenPower auth
adapter (HS256 shared-secret only today).

## Install and configure

Python 3.11 or newer is required. From a checkout:

```bash
python3 -m pip install -e .
cp apx.example.toml apx.toml
apx hosts
apx inspect server
```

`apx.toml` is deliberately ignored because it describes a specific
owner's machines. Use `APX_CONFIG=/path/to/file.toml` or `--config` to
select another file.

## CLI

```text
apx hosts
apx inspect HOST
apx init [--host NAME=SSH_TARGET]
apx doctor
apx plugins
apx plugin NAME
apx relationships
apx resources
apx groups
apx group show GROUP
apx group add|remove GROUP RESOURCE
apx create plugin NAME
apx create action resource.verb
apx create adapter NAME
apx run resource.verb --input '{"key":"value"}'
apx status HOST
apx services HOST
apx service status HOST SERVICE
apx service start|stop|restart HOST SERVICE --yes
apx logs HOST [SERVICE] --lines 100
apx copy SOURCE_HOST SOURCE DESTINATION_HOST DESTINATION
apx sync SOURCE_HOST SOURCE DESTINATION_HOST DESTINATION [--apply]
apx projects
apx project NAME
apx discover-projects HOST [ROOT ...]
apx actions
apx shutdown HOST --yes
apx mcp
```

`sync` is a dry run unless `--apply` is supplied. Destructive CLI actions
require `--yes`; their MCP tools require `confirm=true`.

## Python

```python
from apx import APX

cloud = APX("apx.toml")
result = cloud.run("service.status", host="server", service="caddy")
print(result.to_dict())
```

## MCP

Register this stdio command with an MCP client:

```json
{
  "mcpServers": {
    "apx": {
      "command": "apx",
      "args": ["--config", "/absolute/path/apx.toml", "mcp"]
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

`apx.axp` defines Resource, Capability, VersionInfo, ActionDefinition,
ActionRequest, ActionResult, Event, Context, and StructuredError. Resources may
carry arbitrary groups and tags. These are plain dataclasses;
AXP 0.1 adds no networking, negotiation, authentication, or storage system.

The in-process `EventRouter` supports exact or wildcard subscriptions. Core
actions emit `action.completed`/`action.failed` plus useful specific events such
as `service.started`, `file.copied`, and `host.shutdown_requested`. Plugins and
future interfaces can subscribe or emit without an event broker.

## Credentials and connections

APX stores references, not secret values:

```toml
[credentials.provider]
kind = "provider"
source = "environment"
reference = "PROVIDER_API_TOKEN"
scopes = ["read"]
groups = ["production", "domains"]
tags = ["scoped"]
api_version = "v4"
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

Its implementation stays in that MCP server. APX performs initialize,
discovers tools, and adapts them as actions such as
`existing_tools.some_tool`. It does not run a federation service.

A Host can also declare ordered `connections`, including `ssh` and
`tailscale_ssh`. `host.connection.status` tests them in order and selects the
first usable method. Tailscale remains optional and is inspected through its
local CLI; APX never changes tailnet policy or reads auth keys.

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

APX also includes transport-neutral Action Providers: typed manifests at the conventional HTTP discovery path `/.well-known/apx`, secure prepare/authorize/execute/verify/receipt lifecycles, a decorator-based Python provider SDK, an optional framework-neutral HTTP adapter, explicit remote discovery, Commerce reciprocity conformance, and a runnable local subscription provider. See [Action Providers](docs/action-providers.md).

- `models.py`: configured Hosts, Projects, and project locations.
- `axp.py`: typed AXP 0.1 exchange structures.
- `events.py`: synchronous AXP event router.
- `transports.py`: local subprocess and existing SSH aliases.
- `discovery.py`: dependency-free remote probe executed in memory.
- `actions.py`: shared action contracts and implementations.
- `cloud.py`: public Python facade.
- `cli.py`: human interface.
- `protocol.py`: dependency-free MCP JSON-RPC/stdio adapter.
- `plugins.py`: optional `apx.plugins` Python entry-point contract.
- `credentials.py`: lazy environment references and shared redaction.
- `adapters/`: local, SSH, HTTPS/API, webhook, and MCP stdio connections.
- `scaffold.py`: small plugin, action, and adapter generators.
- `system.py`: read-only connectivity, Tailscale, cron/timer, and launchd discovery.
- `service_managers.py`: explicit systemd/launchd capability contracts.
- `integrations/`: modular provider and database plugins.

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
- provider network access only when a configured provider action is invoked
- native database clients only for the capabilities that use them

APX reports a missing capability instead of installing it.

## Plugins

A plugin is a Python entry point in the `apx.plugins` group. Its loaded
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

Bundled, standard-library integrations cover Porkbun, Cloudflare, GoDaddy,
Discord, OpenAI, Airtable, DigitalOcean, Supabase, PostgreSQL/MySQL resources,
and AWS/DigitalOcean/Supabase database representations. They are shown as
`available_not_configured` until explicitly enabled. Provider actions are a
curated read-only catalog, not a dump of every endpoint. No provider SDK is a
base dependency.

`VersionInfo` separates installed, configured, detected, API-family, supported,
deprecated, recommended, and latest-known information. Compatibility is one of
`current`, `supported`, `deprecated`, `unsupported`, `unknown`, or
`update_available`; APX reports this information and never upgrades a
provider or host automatically.
The official references used for bundled metadata are recorded in
[`docs/provider-versions.md`](docs/provider-versions.md).

## Relationships and extension scaffolds

`apx relationships` returns AXP `ResourceRelationship` records. Project
locations automatically become relationships such as `developed_on`,
`runs_on`, and `backed_up_to`; arbitrary relationships may be declared in TOML.
There is no graph database.

`apx groups`, `apx group show`, and `resource.list` provide simple
group/tag queries. CLI group edits use a small user-owned JSON overlay beside
the TOML file rather than introducing a database.

`apx create plugin|action|adapter NAME` writes two to four small files.
The plugin scaffold is an installable entry-point package with metadata, one
example AXP action, a lazy credential-reference example, and a test. Generated
actions and adapters similarly contain one implementation and one test.
Once installed, plugin actions automatically appear in Python and MCP, and are
available to humans through `apx run`. Destructive actions still require
`--yes`.

## First run and diagnosis

`apx init` discovers the local host, prints its capabilities, optionally
accepts and validates SSH hosts, and writes minimal TOML. It never installs
software. `apx doctor` validates configuration, connectivity, host
capabilities, missing optional commands, plugin health, and MCP tool creation.
It also summarizes integrations, API compatibility, credential health,
configured databases, service managers, schedulers, connections, and Tailscale
availability without contacting unconfigured providers.

## Safety

There is no raw-shell action. Arguments are passed as argv locally and are
shell-quoted for SSH. Services and host names are validated. Secrets are not
part of the configuration schema or discovery output. APX never installs
remote software during inspection.
