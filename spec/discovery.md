# APX Discovery 0.1

DISCOVER answers "what can this subject actually do" -- not "what does this
Provider expose." It is a distinct operation from manifest discovery
(`GET /.well-known/apx`, see `http.md`), which advertises everything a Provider
*could* offer to *any* Client. DISCOVER additionally filters that surface down to
what one identified subject may currently see.

The key words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are to be interpreted
as described by RFC 2119 and RFC 8174.

## The filtering identity

```
discoverable(subject) = registered actions
                       ∩ role/policy authority for subject
                       ∩ Mission-scoped delegation active for subject
                       ∩ Grant-scoped delegation active for subject (see grants.md)
```

A conforming implementation MUST use the exact same predicate to answer DISCOVER as
it uses to filter every other capability listing surface it exposes -- an MCP
`tools/list` response, a UI's "available actions" panel, a capability graph query,
an agent's tool manifest. There MUST NOT be one permission system for humans/UIs and
a separate, looser one for AI/agents. The reference implementation enforces this by
routing every discovery surface through one shared predicate
(`APX._actor_can_discover`), rather than reimplementing the filter per surface.

Introspection actions (an actor asking who it is, why an action was denied, what
system state currently is) MUST always be discoverable and invokable regardless of
policy -- refusing to answer "why was I denied" makes denials undebuggable, and
policy that can hide itself is not auditable.

## Not authoritative

DISCOVER results MAY use a coarse, scope-agnostic check (a Grant scoped to
`host=dev` MAY still cause `service.restart` to appear in discovery even though a
specific `host=prod` invocation would later be denied). A Client MUST NOT treat
appearing in a discovery response as proof an invocation will succeed --
INVOKE/`execute()` still evaluates full scope-aware policy, exactly as if discovery
had not run at all. Discovery is a UX/context-window optimization, never a second
place authorization logic can diverge from EXECUTE's.

## Filtering, not redacting

Implementations SHOULD filter at the point of listing, not merely reject at
invocation. A subject with no visibility into `payroll.run` SHOULD NOT receive it in
a tool manifest that is then rejected on use -- an unauthorized action a caller
never learns exists is a stronger property than one it learns about and is merely
refused. Both layers apply: filtered discovery, and authoritative re-check at
invocation (defense in depth).

## Reducing what a large capability surface costs to reason about

A Provider or aggregate APX installation MAY register a very large number of
actions (thousands, across many namespaces). DISCOVER responses SHOULD be narrowed
further by namespace, resource relationship, or task context before being handed to
an AI agent's context window -- the goal is not "list everything this subject could
theoretically touch," it is "list what is relevant right now." A caller MAY request
a namespace-scoped subset (`namespaces=("project.*","git.*")`) rather than the full
authorized set.

## Wire shape

```json
{
  "apx": "0.1",
  "subject": "apx-actor-id",
  "capabilities": [
    {
      "id": "project.build",
      "description": "...",
      "args": ["project"],
      "required": ["project"],
      "permission": ["project.build"],
      "risk": "low_change",
      "confirmation": "none",
      "idempotent": false,
      "deterministic": true
    }
  ]
}
```

`capabilities` uses the same compact shape as `ActionRegistry.describe(compact=True)`
(action id, description, args, required, permission, risk, confirmation,
idempotent) -- deliberately smaller than a full `ActionDefinition`, so a large
authorized set stays cheap to hand to a reasoning model. A caller that needs full
schemas for a specific, already-discovered action MUST use DESCRIBE (`apx action
inspect <name>`, or manifest lookup for a remote Provider), not request
`compact=false` discovery for everything.
