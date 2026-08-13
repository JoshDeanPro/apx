# APX Bridges

Bridges connect existing ecosystems without changing APX Core. Every Bridge reports
resources, capabilities, actions, provenance, and health.

## Browser

The optional browser Bridge uses an injected deterministic driver. Its Playwright
adapter is imported only when selected; Playwright and browser binaries are not APX
dependencies. It caches semantic DOM/accessibility state, uses stable element
references and accessible field names, and records tool calls, cache hits, retries,
reasoning calls, and duration. Screenshots are not part of the primitive loop.

This design was informed by Browser Use's persistent structured-state CLI and
Playwright's locator model. No Browser Use source is copied or vendored. Browser Use is
MIT licensed; Playwright is Apache-2.0. See `NOTICE` and the upstream projects.

Browser provenance is lower than native/provider/API paths. Consequential fallback
requires explicit lower-trust permission and confirmation.

## Physical devices

The Home Assistant Bridge maps existing entities and services into APX Resources,
Capabilities, and Actions through Home Assistant's documented REST API. APX stores no
device drivers. The token is resolved at execution and never appears in discovery or
receipts. State is reread after a service call. Unlocking/opening use
`security_critical`; ordinary light operations use lower risk.

## Local software

Local discovery detects installed executables and macOS applications without installing
anything. Discovered software becomes a Resource and advertises capabilities such as
version control, SSH transport, fast search, sync, editing, and application opening.
