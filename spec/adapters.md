# APX Adapters 0.1

An APX Adapter connects existing functionality -- a business's API, a device, a
library, a CLI tool -- into the Action protocol without requiring the underlying
system to be rebuilt around APX. This document names the minimum an implementation
must provide to be a conforming Adapter, and how to check that it does.

The key words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are to be interpreted
as described by RFC 2119 and RFC 8174.

## Minimum requirements

An APX Adapter MUST provide:

1. **Stable service identity** -- a `ProviderIdentity` (`id`, `name`, optional
   `url`, `provenance`), unique and stable across restarts and redeploys.
2. **Capability discovery** -- a `ProviderManifest` reachable at
   `GET /.well-known/apx` (see `http.md`) describing every Action and Resource it
   exposes.
3. **Typed action schemas** -- every Action's `input_schema` (and, where
   applicable, `output_schema`) MUST be a valid JSON Schema (Draft 2020-12).
4. **An invocation mechanism** -- at minimum `prepare`/`execute` (or the combined
   single-call form for `confirmation: "none"` read Actions); see `protocol.md`'s
   lifecycle and commit boundary.
5. **An authentication mechanism** -- the Adapter MUST be able to determine who/what
   APX is acting for from the request's `auth_context`/credential, sufficient to
   apply its own authorization. APX does not mandate a specific auth scheme (OAuth,
   mTLS, workload identity, a shared local secret for a same-host dev Adapter) --
   see `protocol.md`'s Security section.

Everything else -- prepare/authorize/execute state persisted across restart,
reversal, budgets/cooldowns, async operations, events -- is an OPTIONAL extension a
manifest advertises via `capabilities`/`extensions`, not a Core requirement. An
Adapter that only implements the five items above and nothing else is still
conforming; it simply advertises a smaller `capabilities` list.

## Retaining existing systems

Adopting APX does not require replacing a business's application, database,
business logic, security model, users, UI, or infrastructure. The Adapter is an
interoperability layer in front of what already exists -- it translates between
APX's Action model and whatever the underlying system already does, and maps the
business's own permission model onto which capabilities a given identity is allowed
to discover and invoke (see `discovery.md`).

## Semantic actions, not endpoint mirroring

An Adapter SHOULD expose semantic actions (`invoice.create`, `payroll.run`) rather
than mirroring transport-level endpoints (`http.post./v2/accounts/83/invoices`) or
collapsing arbitrary shell/script execution into a single opaque Action. Prefer a
small number of meaningful, typed Actions over exhaustively wrapping every
underlying call. Where a semantic Action doesn't yet exist for something the
underlying system can do, add the smallest new Action that represents it -- do not
create a generic passthrough Action as a substitute.

## Transport

`http.md` describes the reference HTTP transport
(`GET /.well-known/apx`, `POST /apx/v0.1/{prepare,authorize,execute,...}`). It is
the first reference transport, not the only legal one -- local IPC, a Unix socket,
stdio, or another message transport MAY carry the same discovery/invocation
semantics. A non-HTTP Adapter MUST still be able to answer identity, capabilities,
schemas, and auth requirements without depending on APX's own Python runtime.

## Conformance: `apx adapter test`

`adapter.test` (CLI: `apx adapter test`) runs the reusable checks in
`apx.conformance`/`apx.providers.validate_provider` against a target and returns a
pass/fail report with one entry per check, so a business or developer can verify
their own implementation without reading the reference SDK:

```bash
apx adapter test --url https://acme.example       # discover + validate a remote Provider's manifest
apx adapter test --provider acme.payroll          # a locally-registered ActionProvider
apx adapter test --bridge browser                 # an internal Bridge (fabric.py's Bridge protocol)
```

`--url` checks: discovery succeeds; the manifest round-trips and passes
`validate_provider` (no duplicate Action ids, no secret-shaped manifest fields,
every reversible Action declares a `reverse_action` that is itself exposed, input/
output schemas are valid); the advertised `apx_version` is supported; and every
Action's schema independently validates. `--provider` additionally checks retry-
policy/idempotency consistency and that strong-confirmation Actions declare a
prepare handler (`apx.conformance.provider_conformance`). `--bridge` checks the
internal Bridge protocol (`apx.conformance.bridge_conformance`): resource ids are
unique, every capability's resource is known, every capability action is actually
registered.

A report of `"ok": true` means the target passed every check it was tested against
-- it does not certify business logic correctness, only protocol conformance.
Discovering or validating a manifest never implies trust: a caller MUST still apply
its own policy before invoking any Action a newly-discovered Adapter advertises.
