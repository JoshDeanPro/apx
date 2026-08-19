# APX 0.1 HTTP Transport

Remote Providers use HTTPS. Plain HTTP MAY be used on loopback for development only.
TLS verification MUST NOT be disabled.

Discovery is `GET /.well-known/apx` with `Accept: application/apx+json`. The manifest
lists compatible protocol versions and transport base URLs; it contains no secrets.

The compact v0.1 endpoint set is:

| Operation | HTTP request |
|---|---|
| prepare | `POST /apx/v0.1/prepare` |
| authorize | `POST /apx/v0.1/authorize` |
| execute | `POST /apx/v0.1/execute` |
| status | `GET /apx/v0.1/status/{request_id}` |
| operation status | `GET /apx/v0.1/operations/{operation_id}` |
| receipt | `GET /apx/v0.1/receipts/{receipt_id}` |
| pre-commit cancel | `POST /apx/v0.1/cancel` |
| reverse | `POST /apx/v0.1/reverse/{receipt_id}` |

Bodies are the schemas in `spec/schemas`. HTTP success only means the protocol
message was delivered; the body state/error determines Action outcome. Long-running
execution returns `accepted` with an operation identifier and is recovered through
status polling. Transports MAY add event subscriptions without changing Core. The
Python reference engine can persist protocol state in a Provider-owned SQLite file;
no database server is required.

Local direct calls and SSH on-demand Nodes carry the same logical messages and state
machine. SSH host verification remains enabled; APX does not require a daemon.

## Discovery and compatibility outcomes

Discovery failures remain ordinary Python exceptions for existing callers, but
`RemoteProvider.discover()` raises `ProviderDiscoveryError`, which is both a
`ValueError` and an `HTTPFailure`. Its `structured_error` field contains the
machine-readable outcome without secrets:

- `connection_rejected`: the endpoint or transport is not acceptable, such as
  remote plain HTTP.
- `provider_unavailable`: timeout, connection failure, or retryable server failure.
- `invalid_request`: the manifest is malformed, oversized, or fails provider validation.
- `protocol_version_unsupported`: the client and provider have no compatible APX version.
- `incompatible_requirements`: required capabilities, actions, credentials,
  permissions, or actor types cannot be satisfied.

`evaluate_compatibility()` keeps the existing human-readable `reasons` tuple and
also returns structured `errors`. A caller may inspect the first error through
`CompatibilityResult.error`; no raw credential values are included.
