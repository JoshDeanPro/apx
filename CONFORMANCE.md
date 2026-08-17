# APX Conformance

Conformance is a technical standard verifying protocol compatibility. The MPL-2.0 license (see [LICENSE](LICENSE)) governs what you may do with APX's code. Conformance governs what may be represented as officially APX-compatible.

Conformance is technical and testable, not a pay-to-play certification program.

## What's checked

`apx.providers.validate_provider()` is the implemented, tested (`tests/test_providers.py`, `tests/test_action_providers.py`) conformance check for an `ActionProvider` or `ProviderManifest`:

- The manifest round-trips through `to_dict()`/`from_dict()` without loss
- Action IDs are unique within the provider
- Every action's `input_schema` describes a JSON object
- Declared `risk` and `confirmation` values are within the standard vocabulary (see [docs/action-providers.md](docs/action-providers.md))
- A `reversible` action declares a `reverse_action`, and that action is exposed by the same provider
- Idempotency is a resolved boolean, never left ambiguous
- The manifest contains no secret-shaped fields (checked against the same key-pattern list APX's redaction uses)
- If the provider declares the `apx-commerce` profile, it satisfies Commerce Reciprocity below

Run it via CLI: `apx conformance` or in Python: `apx.providers.validate_provider(my_provider)`.

## Commerce Reciprocity

If an APX Commerce-compatible provider (the `apx-commerce` profile) exposes a machine-readable way to create a recurring financial obligation — `subscription.start`, `subscription.purchase`, or `subscription.resume` — then, where cancellation is available through the underlying service, it must also expose a machine-readable `subscription.cancel`.

`validate_provider()` enforces this for any provider claiming the `apx-commerce` profile.

## What conformance is not

- Not a requirement to use APX — APX works standalone with zero conformance checking.
- Not a claim that non-conformant software is insecure — only that it hasn't been checked against this technical standard.

