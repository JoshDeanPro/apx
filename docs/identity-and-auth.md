# Identity, authentication, and authorization

Six terms, kept strictly distinct:

- **Actor / Principal** (`axp.Actor`, re-exported as `auth.Principal`) — the identity itself: `id` (`kind:name`, e.g. `agent:worker:node-1`), `kind` (human/host/machine/agent/service/automation/api/mcp/plugin), optional `display_name`. Stable IDs, never a display name alone.
- **Profile** (`identity.AgentProfile`) — what's known *about* a Principal: assigned roles, groups, tags, projects, host, runtime, and an optional external identity link. One profile shape serves every principal kind.
- **AuthContext** (`axp.AuthContext`) — evidence that a Principal was authenticated this request: `authentication_method` (`local_os`/`token`/...), `issuer`, `credential_id`, `device_id`, `delegated_by`, timestamps. Identity evidence only — never a raw secret.
- **AuthProvider** (`auth.AuthProvider`) — produces an `AuthContext` from credentials. `LocalAuthProvider` is always available and requires no configuration.
- **Role / Permission** (`policy.RolePolicy`/`ScopedRule`, evaluated by `policy.PolicyEngine`) — what a Principal, identified by its bare actor-id string, may actually do. Scoped allow/deny, explicit deny always wins.
- **Delegation** — `AuthContext.delegated_by` plus Mission-scoped grants (`mission.grant`) record who authorized whom, distinctly from the executing actor and target — never flattened into a single user field.

## Authentication vs. authorization

> Identity providers can authenticate who an actor is. APX decides locally what that actor may do on the resources the user owns.

`cloud.execute()` computes an `AuthContext` for every request (synthesizing `authentication_method="local_os"` when none was supplied — this is what every existing bare `actor="..."` call already gets). That context is attached to the emitted `policy.allowed`/`policy.denied` events for audit. It is **never** consulted by `PolicyEngine.evaluate()` — policy is keyed purely on the local actor-id → role mapping. An authenticated actor has exactly the permissions the local `[[roles]]` config grants that actor, no more. A local explicit `deny` always wins.

## Optional, always

Zero `[auth]` configuration: APX operates with the default local authentication provider (`allow_local_fallback`, default `true`).

## Enrollment and pairing

`identity.enrollment.*` lets an agent or node request an identity; `[auth] enrollment_mode` (default `manual`) gates whether that request is rejected (`disabled`), requires confirmation (`manual`/`trusted_device`), or is immediate (`automatic`). `identity.pairing.*` provides one-time pairing token validation.
