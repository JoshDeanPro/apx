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
| receipt | `GET /apx/v0.1/receipts/{receipt_id}` |
| pre-commit cancel | `POST /apx/v0.1/cancel` |
| reverse | `POST /apx/v0.1/reverse/{receipt_id}` |

Bodies are the schemas in `spec/schemas`. HTTP success only means the protocol
message was delivered; the body state/error determines Action outcome. Long-running
execution returns `accepted` with an operation identifier and is recovered through
status polling. Transports MAY add event subscriptions without changing Core.

Local direct calls and SSH on-demand Nodes carry the same logical messages and state
machine. SSH host verification remains enabled; APX does not require a daemon.
