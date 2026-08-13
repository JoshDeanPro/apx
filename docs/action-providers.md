# APX Action Providers

APX providers expose what a user can do, not the implementation details used to do it. Core remains transport-independent: a provider may be local, application-native, plugin-backed, generated, or remote.

## Provider manifest and discovery

`ProviderManifest` is the implemented typed manifest. HTTP providers publish it at `/.well-known/apx` with `application/apx+json`. It includes APX and manifest versions, provider identity/origin, resources, the full action definitions, authentication and confirmation methods, capabilities, transports, compatibility, optional conformance profiles, and metadata. It must not contain credentials.

Connecting a remote origin is explicit:

```python
from apx import APX

apx = APX("apx.toml")
manifest = apx.connect_provider("https://service.example")
```

Discovery validates HTTPS (plain HTTP is limited to loopback), caps manifests at 1 MiB, validates the schema and conformance rules, and only then registers actions into the existing `ActionRegistry`. Discovery does not imply trust or authorization.

## Action definitions

`ActionDefinition` describes meaning and consequences: input/output JSON Schemas, resource type, permissions, risk, confirmation, side effects, idempotency and retry policy, pre/postconditions, concurrency/cooldown constraints, reversibility/reverse or remediation action, expected verification, credential and actor requirements, provider, provenance, tags, version, and deprecation data. Existing `RegisteredAction` values remain valid; defaults preserve local and SSH behavior.

Risk is one of `read`, `low_change`, `account_change`, `destructive`, `financial`, or `security_critical`. Confirmation is one of `none`, `delegated`, `confirm`, `step_up`, `transaction`, or `security_critical`. Provenance is descriptive: `native_provider`, `official_plugin`, `community_plugin`, `local_component`, `generated_component`, or `browser_fallback`.

## Lifecycle and receipts

The lifecycle is DISCOVER → PREPARE → AUTHORIZE → EXECUTE → VERIFY → RECEIPT, with optional reversal. Simple reads may collapse stages. `ProviderSession.prepare()` returns an expiring `prepared_action_id`, authoritative state/version, resolved terms, exact confirmation, preconditions, and reversibility. Preparation has no side effect. `accepted` is the commit boundary; cancellation before it guarantees `committed: false`.

Consequential provider actions require authenticated actor context. Confirmation must match the declared level. Transaction confirmation must match the exact `confirmation_terms` from preparation. Expired confirmations, reused authorization IDs, expired requests, and revoked credentials are rejected. A provider can return `authorization_required` with its authorization URL and expiry; a client should open that provider-controlled OAuth/WebAuthn/passkey flow and retry with the resulting confirmation. APX does not hold provider passkeys or invent cryptography.

Confirmation binds to that exact prepared ID, terms, and expiry. Execution must match prepared input/target/state version. Provider policy is checked again at commit. A denial ends the APX request; conforming clients do not seek a bypass.

Idempotency keys make duplicate logical requests return the same result/receipt. Status and receipt lookup resolve the case where execution happened but the response was lost. Retry policy is `safe`, `idempotency_required`, `manual`, or `never`. Providers can declare cooldown, concurrency, resource-lock, rate, and budget constraints without APX becoming a job queue.

## Identity, delegation, and credentials

Authentication answers who is acting; policy authorization separately answers what that actor may do. Both APX policy and provider account policy can deny an action. Explicit APX denies win over allows and mission delegation cannot grant authority the delegator does not hold.

`ActorDescriptor` is the provider-facing minimum-disclosure envelope: actor ID/type, delegator/owner, client, device, relevant roles, and the requested permission. It omits conversations, prompts, memories, unrelated profiles, inventory, and account data.

`CredentialHandle` contains only credential metadata: ID, bearer or `proof_of_possession` mode, issuer, audience, fingerprint, expiry, and revocation state. Private keys stay at the originating device. Actual proof can use established OAuth sender-constrained tokens, DPoP, mTLS, or WebAuthn as selected by a transport/provider; APX Core defines no signing algorithm.

Secret parameters use JSON Schema `"x-apx-secret": true` and pass an opaque `SecretInput`/reference through a secure provider pathway. Provider handlers should resolve the secret outside the language model. APX redaction prevents secret-shaped output fields from reaching results, receipts, or events.

## Building a provider

```python
from apx import ActionProvider

provider = ActionProvider("example.com", "Example")

@provider.action(
    "subscription.cancel",
    description="Disable renewal while retaining current access",
    risk="account_change",
    confirmation="confirm",
    permissions=("subscription.cancel",),
    reversible=True,
    reverse_action="subscription.resume",
)
def cancel_subscription():
    return {"renewal": False}

@provider.prepare("subscription.cancel")
def prepare_cancel():
    return {"effect": "Disable renewal"}

@provider.verify("subscription.cancel")
def verify_cancel(result):
    return result["renewal"] is False

apx.register_provider(provider)
```

`ProviderSession` supplies the protocol machinery. `APXClient` speaks through `LocalClientTransport` or `HTTPClientTransport`; Provider business code is unchanged. `HTTPProviderAdapter.handle()` exposes the compact `/apx/v0.1` lifecycle without requiring FastAPI. See [the HTTP specification](../spec/http.md).

## Commerce reciprocity

The optional `apx-commerce` profile requires a provider that exposes recurring enrollment (`subscription.start`, `.purchase`, or `.resume`) to expose `subscription.cancel` when cancellation is supported. Refundable/cancellable purchases should expose the corresponding cancel/refund action. Transaction preparation includes exact amount, currency, merchant, item/service, recurring and cancellation terms; APX delegates payment authorization and settlement to established payment systems.

## Generated actions and conformance


`validate_provider()` checks manifest round trips, unique IDs, object input schemas, risk/confirmation enums, reversal consistency, declared idempotency, secret-shaped manifest fields, and Commerce reciprocity. The reusable tests in `tests/test_providers.py` cover lifecycle, authorization, replay, expiry, revocation, disclosure, receipt redaction, policy precedence, HTTP wire behavior, and reversal.

## Reference provider and CLI

Enable the runnable, local-only reference provider in a test configuration:

```toml
[[providers]]
type = "reference"
enabled = true
```

Then, with the `apx` CLI:

```console
apx providers
apx provider inspect reference.local
apx actions --provider reference.local
apx action inspect subscription.cancel --provider reference.local
```

`op` (OpenPower's CLI, a separate optional product built on APX) does not yet
have equivalent `providers`/`provider`/`action` inspection commands -- it
currently only delegates `host`/`service`/`logs` actions to APX. Deferred,
not implemented; do not assume `op providers` works today.

The implementation lives in `apx.examples.subscriptions`. It has inspect, transaction-style start, confirmed cancel, resume, preparation, verification, receipts, and real in-memory state changes; it uses no production credentials.

Lifecycle events are `action.prepared`, `action.authorization_required`, `action.authorized`, `action.started`, `action.completed`, `action.failed`, and `action.reversed`. Provider and credential events include connect/disconnect, action add/remove, and credential revocation. Event payloads contain metadata, never secret inputs.
