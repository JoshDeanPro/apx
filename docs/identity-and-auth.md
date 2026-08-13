# Identity, authentication, and authorization

Six terms, kept strictly distinct:

- **Actor / Principal** (`axp.Actor`, re-exported as `auth.Principal`) — the identity itself: `id` (`kind:name`, e.g. `agent:claude:mac`), `kind` (human/host/machine/agent/service/automation/api/mcp/plugin), optional `display_name`. Stable IDs, never a display name alone.
- **Profile** (`identity.AgentProfile`) — what's known *about* a Principal: assigned roles, groups, tags, projects, host, runtime, and an optional `openpower_identity` link. One profile shape serves every principal kind.
- **AuthContext** (`axp.AuthContext`) — evidence that a Principal was authenticated *this request*: `authentication_method` (`local_os`/`openpower`/`cached_openpower`/`openpower_offline`/...), `issuer`, `credential_id`, `device_id`, `delegated_by`, timestamps. Identity evidence only — never a raw secret.
- **AuthProvider** (`auth.AuthProvider`) — produces an `AuthContext` from credentials. `LocalAuthProvider` is always available and requires no configuration; `OpenPowerAuthProvider` (`auth_openpower.py`) is opt-in.
- **Role / Permission** (`policy.RolePolicy`/`ScopedRule`, evaluated by `policy.PolicyEngine`) — what a Principal, identified by its bare actor-id string, may actually do. Scoped allow/deny, explicit deny always wins.
- **Delegation** — `AuthContext.delegated_by` plus Mission-scoped grants (`mission.grant`) record *who authorized whom*, distinctly from the executing actor and target — never flattened into a single `user=...` field.

## Authentication vs. authorization

> OpenPower can authenticate who an actor is. AXP decides locally what that actor may do on the resources the user owns.

`cloud.execute()` computes an `AuthContext` for every request (synthesizing `authentication_method="local_os"` when none was supplied — this is what every existing bare `actor="..."` call already gets, for free, unchanged). That context is attached to the emitted `policy.allowed`/`policy.denied` events for audit. It is **never** consulted by `PolicyEngine.evaluate()` — policy is keyed purely on the local actor-id → role mapping. An OpenPower-authenticated `agent:claude:mac` has exactly the permissions the local `[[roles]]` config grants `agent:claude:mac`, no more, regardless of what the OpenPower token claims about that principal. A local explicit `deny` always wins.

## Optional, always

Zero `[auth]` configuration: AXP behaves exactly as before this layer existed. `[auth.openpower]` adds one more `AuthProvider`; nothing in Core imports it unless configured. There is no Supabase dependency, no requirement that openpower.one be reachable, and no code path where losing connectivity to OpenPower disables a machine's local functionality (`allow_local_fallback`, default `true`).

## Enrollment and pairing

`identity.enrollment.*` lets an agent/machine ask for an identity; `[auth] enrollment_mode` (default `manual`) gates whether that's a no-op (`disabled`), needs a human (`manual`/`trusted_device`), or is immediate (`automatic` — only ever when a user explicitly sets it). `identity.pairing.*` is a one-time-code primitive for future secure device pairing (e.g. a new Buddy Box) — process-lifetime only, no relay, no network transport built yet.
