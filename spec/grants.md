# APX Grants 0.1

A Grant is bounded, delegated authority: subject X may perform actions Y on
resources Z, optionally until it expires, until it is revoked. Static role policy
(`[[roles]]`, `protocol.md`'s "Authority and policy") answers "what can this kind
of actor generally do." A Grant answers "what can this specific actor do right now,
because someone who already held that authority chose to delegate a slice of it."

The key words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are to be interpreted
as described by RFC 2119 and RFC 8174.

## Shape

```json
{
  "id": "grant-a1b2c3d4",
  "subject": "apx-actor-id",
  "issued_by": "apx-actor-id",
  "actions": ["service.restart", "service.status"],
  "resources": ["apx://service/web"],
  "constraints": {"host": ["staging"]},
  "reason": "on-call incident response, INC-482",
  "issued_at": "2026-08-13T20:00:00+00:00",
  "expires_at": "2026-08-13T22:00:00+00:00",
  "revoked_at": null,
  "revoked_by": null,
  "active": true
}
```

- `actions` are exact action names or `namespace.*` patterns, matched the same way
  `[[roles]]` allow/deny rules match (`protocol.md`'s Core action-name convention).
- `resources` are `apx://kind/id` references (see the addressing note below).
  Empty means the Grant is not resource-scoped -- it applies wherever `actions`
  matches, subject to `constraints`. A reference's `kind` determines which policy
  scope dimension it binds to: `host`/`node` refs scope to the same `host`
  dimension a static role rule would use (`apx://host/prod` behaves exactly like
  `scope={"host":["prod"]}`); `project` refs scope to the `project` dimension
  similarly. Other kinds bind to a generic `resource` dimension, which only takes
  effect for an action whose own target happens to carry a matching `resource`
  key -- most Core actions do not populate one today, so scoping a Grant to an
  arbitrary non-host/non-project resource kind is currently advisory, not yet
  enforced, until more actions carry resource-typed targets. A Grant that mixes
  reference kinds narrows by AND across the resulting dimensions (the same
  scope-matching semantics `ScopedRule` already has), so scoping one Grant to
  resources of a single kind is the predictable case.
- `constraints` are arbitrary scope dimensions matched the same way a `ScopedRule`'s
  `scope` is matched against an action's `target` (see `protocol.md`'s Authority
  and policy section) -- e.g. `{"host": ["staging"]}` only authorizes the delegated
  actions against that host.
- `expires_at` is OPTIONAL. A Grant without one does not expire on its own and
  remains active until explicitly revoked -- implementations SHOULD warn when
  issuing a long-lived or non-expiring Grant for a consequential action.

## Self-delegation

An issuer MUST already hold every action pattern it delegates. `grant.issue` MUST
be evaluated against the issuer's own current authority (static role policy plus
its own active Grants and Mission delegations) before the Grant is created --
`grant.*` itself carries no ambient authority to create new authority out of
nothing. An issuer that does not itself hold `payroll.run` cannot grant `payroll.run`
to anyone, no matter what role `grant.issue` itself requires.

## Interaction with policy evaluation

A Grant is evaluated as additional allow authority, after static role `allow`/`deny`
rules, exactly like a Mission's temporary permission grant (`protocol.md` does not
distinguish the two -- both are "delegated, non-static authority"). An explicit
static `deny` rule always wins over any Grant; a Grant can expand what a role alone
would allow, never override a denial.

## Discovery

An active Grant MUST be reflected in DISCOVER results for its subject immediately
-- see `discovery.md`. A subject should not have to re-authenticate, reconnect, or
wait for a cache to expire before a newly issued Grant becomes visible in what it
can see and invoke.

## Revocation

`grant.revoke` MUST take effect immediately: the next policy evaluation for that
subject MUST NOT consider a revoked Grant, and the next DISCOVER call MUST NOT list
capabilities that only that Grant provided. A revoked Grant is not deleted -- it
remains inspectable (`grant.inspect`) with `revoked_at`/`revoked_by` set, for audit.
A Grant MUST NOT be revoked twice.

## Relationship to Mission-scoped delegation

Missions (`fabric.md`'s higher-level project/task tracking) MAY also grant
temporary permission scoped to the Mission's own lifetime (`mission.grant`) -- this
remains useful for "this permission only makes sense while this specific unit of
work is active," and is not superseded by standalone Grants. A conforming
implementation MUST combine both sources when evaluating policy and discovery, so
an actor's effective authority is never split across two answers depending on which
one asked.

## What a Grant is not

A Grant does not create a new identity, does not itself authenticate anyone, and
does not bypass a Provider's own authorization (`protocol.md`'s Authority and
policy: Client policy and Provider policy both MUST pass). It narrows what an
already-identified actor may attempt through APX; it never widens what a Provider
independently permits.
