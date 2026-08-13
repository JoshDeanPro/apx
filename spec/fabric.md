# APX Universal Capability Fabric

APX Core defines one graph:

`Resource -> Capability -> Action -> Policy -> Execution -> Verification -> Receipt`

A Resource is anything legitimate authority can act upon. A Capability groups useful
operational vocabulary without implying permission. An Action is the versioned,
schema-described operation. Discoverability MUST NOT imply authority.

Capabilities identify their Resource, Actions, provenance, reliability, source, and
health. Clients select the highest-confidence healthy path. The normative provenance
order is: native APX/provider, official API/SDK, standard bridge, local native,
official/community component, validated generated/browser component, browser fallback,
general computer fallback.

A lower-trust path MUST NOT be selected silently. Consequential fallback to browser or
computer control requires explicit policy and fresh confirmation. Provider truth and
authorization are never cached by this graph.

Bridges implement discovery, Action registration, and shared health. They are
replaceable and MUST NOT become APX Core dependencies. Components compose existing
Actions deterministically; they add no authority. Generated and browser Components
MUST pass validation and approval, declare compatibility/version/expiry, and support
invalidation.

The initial reusable Action vocabulary includes inspect, list, create, update, delete,
enable, disable, start, stop, restart, send, receive, move, copy, sync, open, close,
lock, unlock, purchase, cancel, refund, rotate, revoke, subscribe, unsubscribe, deploy,
rollback, backup, restore, search, execute, and confirm. Domains remain extensions.

