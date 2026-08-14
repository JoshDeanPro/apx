# APX Specification 0.1

APX standardizes how capabilities are discovered, authorized, invoked, observed,
and exchanged across humans, software, machines, businesses, and AI. MCP connects
AI to tools; APX connects authorized actors to actions.

This directory is the **Protocol** -- the open, implementation-independent
contract. It is deliberately small. The **Platform** (Blueprints, Missions,
Projects, Bridges, Patterns, Agents, the Python reference runtime in `src/apx/`,
and everything else built on top) is not part of this contract and MUST NOT be
required to implement it.

## Core

| Document | Covers |
|---|---|
| [`protocol.md`](protocol.md) | Roles, wire format, versioning, the invocation lifecycle and commit boundary, authority/policy separation, confirmation levels, execution safety (idempotency, budgets, cooldowns, postcondition verification), Core error codes, security posture. |
| [`http.md`](http.md) | The reference HTTP transport: discovery endpoint, prepare/authorize/execute/status/receipt/reverse paths. One reference transport among possible others -- see `protocol.md`'s transport neutrality. |
| [`fabric.md`](fabric.md) | The Resource → Capability → Action → Policy → Execution → Verification → Receipt graph; provenance-ranked path selection; Bridges and Components. |
| [`discovery.md`](discovery.md) | DISCOVER: identity-aware, policy-filtered capability listing -- the difference between "what a Provider could expose" and "what this subject can currently see." |
| [`grants.md`](grants.md) | Grants: standalone, independently-expiring, revocable delegated authority, distinct from static role policy. |
| [`adapters.md`](adapters.md) | The minimum for an external service to become a conforming APX Adapter, and the `apx adapter test` conformance runner. |
| [`conformance.md`](conformance.md) | What makes a Provider or Client conforming; where the reusable test suites live. |

## Where the rest of the task's protocol-operation vocabulary lives

- **IDENTITY** -- `protocol.md`'s Authority and policy section (`Actor`,
  `AuthContext`, `ActorDescriptor` in the reference implementation's `axp.py`).
- **RESOURCE** -- `fabric.md`; addressing is `apx://kind/id`
  (`axp.resource_ref`/`parse_resource_ref`), additive over existing bare-id
  resources, not a required migration for every resource in a running system.
- **CAPABILITY** -- `fabric.md`.
- **DISCOVER** -- `discovery.md`.
- **DESCRIBE** -- an Action's full `ActionDefinition` (`protocol.md`'s wire format);
  reference CLI: `apx action inspect <name>`.
- **INVOKE** -- `protocol.md`'s lifecycle (prepare → authorize → execute).
- **OBSERVE** -- `protocol.md`'s status/receipt/operation lookup (`http.md`'s
  `/apx/v0.1/{status,operations,receipts}` paths).
- **SUBSCRIBE** -- Events, referenced in `protocol.md`'s long-running-Action
  section; per-transport, not yet a Core-normative wire format in this version.
- **GRANT** -- `grants.md`.
- **RESULT** -- `protocol.md`'s wire format (`ActionResult`/`ActionReceipt`).

## Optional extensions

Extensions declare themselves under a manifest's `extensions` map
(`namespace:name` keys) and MUST NOT change Core semantics. See
[`personal-context.md`](personal-context.md) and
[`optional-commercial-extensions.md`](optional-commercial-extensions.md) for two
worked examples of the pattern.

## Schemas

Machine-readable JSON Schemas for the shapes above live in [`schemas/`](schemas/)
and are packaged with the reference implementation (see `pyproject.toml`'s
`[tool.setuptools.data-files]`) so they ship independently of any particular SDK
version.

## Versioning

The current protocol version is `0.1`. `axp: "0.1"` (wire) / `apx: "0.1"` (newer
documents) appears on every message. See `protocol.md`'s Wire format and versions
section for the compatibility rules unknown fields, actions, and enum values MUST
follow.
