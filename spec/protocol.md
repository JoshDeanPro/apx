# APX Protocol 0.1

APX standardizes consequential Actions. Clients express intent; Providers establish
truth about Provider-owned Resources and retain their business rules.

The key words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are to be interpreted as
described by RFC 2119 and RFC 8174.

## Roles

- A **Client** requests Actions and enforces its user's delegation policy.
- A **Provider** describes and performs Actions and enforces Provider policy.
- A **Node** is a Provider representing a machine or environment.
- An **Authority** optionally authenticates identities or issues scoped delegation.

No role depends on OpenPower. A participant MAY implement several roles.

## Wire format and versions

The initial representation is UTF-8 JSON. Messages carry `axp: "0.1"` and a
`type`. The protocol version is independent of SDK, Provider, implementation, and
extension versions. Implementations MUST reject unsupported major/minor protocol
versions with `protocol_version_unsupported`. Unknown fields MUST be ignored unless
their interpretation is necessary for safe execution. Unknown confirmation, risk,
retry, or state values MUST fail closed.

Action names use lower-case `resource.verb` segments. Provider-specific names SHOULD
use a stable namespace. Extensions use keys of the form `namespace:name` and MUST NOT
change Core semantics.

## Lifecycle and commit boundary

`requested -> prepared -> authorization_required -> authorized -> accepted ->
executing -> completed`

Terminal alternatives are `denied`, `rejected`, `cancelled`, `expired`, `failed`,
`partial`, `verification_failed`, and `reversed`.

`requested`, `prepared`, `authorization_required`, and `authorized` are pre-commit.
Neither connection nor preparation accepts an Action. Either party MAY end the flow;
the Provider MUST cause no Action side effect. `accepted` is the commit boundary.
Cancellation after it is Action-specific and MUST NOT be represented as pre-commit
cancellation. Reversal is a separate Action.

Prepared Actions MUST have a unique `prepared_action_id`, creation and expiry times,
resolved target and terms, authoritative state version, preconditions, and required
confirmation. Consequential execution MUST exactly match the prepared Action. An
expired or stale preparation MUST be prepared again.

## Authority and policy

Client policy determines what the actor may request. Provider policy determines what
the Provider permits. Both MUST pass. Authentication is not authorization. Provider
denial is a legitimate terminal result; a conforming Client MUST NOT automatically
bypass it through another endpoint, browser automation, altered parameters, or a
different Action.

Clients provide intent and identifiers. They MUST NOT establish eligibility,
ownership, price, policy, or Provider state through user-supplied assertions. The
Provider resolves authoritative state and checks preconditions immediately before
commit.

Consequential requests MUST identify an actor. Delegation states delegator, delegate,
scope, actions/resources, constraints, confirmation, and expiry. Only minimum-needed
identity claims may cross the boundary. Conversations, prompts, memories, unrelated
profiles, inventories, and reasoning MUST NOT be disclosed.

Confirmation levels are `none`, `delegated`, `confirm`, `step_up`, `transaction`, and
`security_critical`. A Provider MAY increase but neither party may lower the required
level. Strong confirmation MUST bind to the prepared Action, resolved terms, expiry,
and a single-use authorization identifier.

## Execution safety

Requests carry `request_id`; consequential retryable requests carry an
`idempotency_key`. Duplicate keys MUST return the existing result or receipt, not
execute again. Retry policies are `safe`, `idempotency_required`, `manual`, and
`never`. Retries are bounded and observable.

Providers MAY advertise rate limits, cooldowns, concurrency, resource locks, and
budgets in Action constraints. Clients MUST respect `retry_after`, rate-limit,
cooldown, lock, circuit, and budget responses. Core does not prescribe distributed
locking or a budget service.

After execution, Providers SHOULD reread authoritative state and evaluate declared
postconditions. They MUST NOT report `completed` when verification fails. A
consequential completion returns a secret-free receipt. If a response is lost, the
Client uses request status or receipt lookup; it MUST NOT blindly retry an ambiguous
unsafe Action.

## Errors

Core codes are: `invalid_request`, `unsupported_action`, `unauthenticated`,
`permission_denied`, `confirmation_required`, `policy_denied`,
`precondition_failed`, `state_conflict`, `rate_limited`, `cooldown_active`,
`resource_locked`, `provider_unavailable`, `expired`, `cancelled`,
`execution_failed`, `partial_failure`, `verification_failed`,
`protocol_version_unsupported`, and `ambiguous_execution`.

Providers MAY add `provider_code`, safe details, `retry_after`, and `next_actions`.
Provider codes never override Core behavior.

## Security

Consequential Actions fail closed when identity, permission, target, preparation, or
confirmation cannot be established. APX does not define cryptography. Transports use
established OAuth, WebAuthn/passkeys, proof-of-possession, enterprise, local, or
Provider authentication. Passwords, tokens, private keys, authorization headers,
secret inputs, and payment credentials MUST NOT appear in schemas' examples, logs,
events, errors, inspectors, or receipts.
