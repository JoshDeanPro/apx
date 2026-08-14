# Deterministic execution plane

APX uses one Action Registry and one policy-checked execution path for Python,
CLI, MCP, Providers, bridges, OpenPower controls, voice, and procedures. The
execution plane imports no model SDK and works without API keys.

```text
intent -> ActionRequest -> identity/policy/confirmation -> Python handler
       -> native adapter/API/subprocess -> verification -> compact result
```

`APX.run()` and `APX.run_async()` invoke named Actions. `ActionResult.execution`
reports deterministic execution, duration, adapter, changed state, reasoning
calls, and model calls avoided. `ActionResult.compact()` is the default
agent-facing shape; raw diagnostics remain available only where useful.

`ReasoningRequired` is a fail-closed escalation boundary. It returns
`needs_reasoning=true`; APX never calls a model itself. A caller may then ask an
authorized agent to resolve ambiguity and submit a new Action.

Procedures are typed, inspectable Action sequences. Every step re-enters APX
policy and validation. Procedure confirmation cannot be weaker than any step.

```toml
[[procedures]]
id = "procedure.restart-web"
description = "Restart and inspect the web service"
confirmation = "confirm"

[[procedures.steps]]
action = "service.restart"
input = { host = "vps", service = "caddy" }

[[procedures.steps]]
action = "service.status"
input = { host = "vps", service = "caddy" }
```

Action catalogs support compact namespace/policy filtering. Clients should send
only relevant descriptors, not implementation source or the entire registry.

## Optional white-label engines

External engines remain replaceable bridges and are never synonymous with APX.

| Engine | APX role | Core dependency |
|---|---|---|
| HTTPX | shared HTTPS client | yes, already present |
| MCP Python SDK | optional richer MCP transport | no |
| psutil | cross-platform machine inspection | no; lazy `PsutilBridge` |
| PyCasbin | possible policy backend after semantic parity tests | no |
| Ansible Runner | capability-specific remote convergence | no |
| APScheduler | optional persistent schedules | no |
| openapi-python-client | reviewed generated API bridges | no |
| SOPS | external secret resolver | no |
| LiteLLM | optional reasoning-plane provider bridge | never execution Core |
| OpenTelemetry | optional exporter for Action metrics | no |

APX keeps its existing schemas and validation instead of adding Pydantic as a
duplicate required validator. Generated clients/actions require review and
conformance before registration.
