# APX Conformance

Conformance is a **separate concern from the software license**. The
MPL-2.0 license (see [LICENSE](LICENSE)) governs what you may do with
APX's code. Conformance governs what may be represented as officially
APX-compatible (see [TRADEMARKS.md](TRADEMARKS.md)). A fork or an
unlisted provider remains free to exist, unmodified by anything in this
document, without ever seeking conformance.

This is intentionally technical and testable, not a pay-to-play
certification program, and it does not require an OpenPower account.

## What's checked today

`apx.providers.validate_provider()` is the real, implemented,
tested (`tests/test_providers.py`, `tests/test_action_providers.py`)
conformance check for an `ActionProvider` or `ProviderManifest`:

- the manifest round-trips through `to_dict()`/`from_dict()` without loss
- action IDs are unique within the provider
- every action's `input_schema` describes a JSON object
- declared `risk` and `confirmation` values are within the standard
  vocabulary (see [docs/action-providers.md](docs/action-providers.md))
- a `reversible` action declares a `reverse_action`, and that action is
  actually exposed by the same provider
- idempotency is a resolved boolean, never left ambiguous
- the manifest contains no secret-shaped fields (checked against the
  same key-pattern list APX's own redaction uses)
- if the provider declares the `apx-commerce` profile, it satisfies
  [Commerce Reciprocity](#commerce-reciprocity) below

Run it yourself: `apx.providers.validate_provider(my_provider)` returns a
list of human-readable errors — empty means it passes.

## Commerce Reciprocity

If an APX Commerce-compatible provider (the `apx-commerce` profile)
exposes a machine-readable way to create a recurring financial
obligation — `subscription.start`, `subscription.purchase`, or
`subscription.resume` — then, where cancellation is actually available
to the user through the underlying service, it must also expose a
machine-readable `subscription.cancel`.

The agentic internet should not become excellent at signing people up and
silent about how to get out. This is a conformance requirement, not a
license restriction — nothing prevents a non-conformant provider from
existing, it just can't claim `apx-commerce` compatibility while hiding
the exit.

`validate_provider()` enforces this today for any provider claiming the
`apx-commerce` profile.

## Planned conformance designations

These are named and structurally reserved (see
[TRADEMARKS.md](TRADEMARKS.md#official-designations)) but not yet backed
by a formal certification process:

- **APX Compatible**
- **APX Provider Compatible**
- **APX Commerce Compatible**

When a real process exists for claiming these, it will be technical
(pass the conformance suite) rather than an approval/account
requirement, consistent with [GOVERNANCE.md](GOVERNANCE.md)'s "no central
Action censorship" principle.

## What conformance is not

- Not a requirement to use APX at all — APX works standalone with zero
  conformance checking.
- Not an OpenPower account requirement.
- Not a claim that non-conformant software is insecure or bad — only
  that it hasn't been checked against, or doesn't meet, this specific
  technical bar.
