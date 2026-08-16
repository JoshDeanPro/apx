# Security Policy

APX gives humans and AI agents real-world action capability — SSH access,
service control, credential resolution, and (via Action Providers)
account changes, financial transactions, and security-critical
operations like password rotation and session revocation. Security here
is not optional hardening; it's the point.

## Reporting a vulnerability

**Please do not open a public GitHub issue for a security
vulnerability.**

Report privately. Until a dedicated security contact/address exists,
report through a private channel to the project Steward (see
discussion thread. Include:

- what you found and why it's a security issue
- steps to reproduce, or a minimal proof of concept
- the affected version/commit
- your assessment of impact (what an attacker could actually do)

We will acknowledge receipt, investigate, and work with you on a
disclosure timeline. Please don't publish exploit details before a fix is
available and released.

## Supported versions

APX is pre-1.0 and evolving quickly. Until a formal support-window policy
exists, the only supported version is the latest release on the
canonical repository. Security fixes land there first.

## What's in scope

Categories that matter most, given what APX actually does:

- **Permission bypass** — any way to execute an action a policy decision
  should have denied
- **Confirmation bypass** — executing a `confirm`/`transaction`/
  `step_up`/`security_critical` action without valid, matching
  confirmation (see [docs/action-providers.md](docs/action-providers.md))
- **Replay** — reusing a confirmation's `authorization_id`, or executing
  an expired request/confirmation
- **Credential exposure** — a secret value reaching a log, an
  `ActionResult`, an `ActionReceipt`, or an `Event` that shouldn't carry
  it (APX redacts by design; a redaction gap is a real bug)
- **Provider impersonation** — a remote provider manifest or response
  being trusted without the discovery/validation `RemoteProvider.discover()`
  actually performs (HTTPS-only, schema validation, conformance checks)
- **Receipt spoofing** — anything that lets a caller fabricate or alter
  an `ActionReceipt` after the fact
- **Remote execution vulnerabilities** — anything in the SSH/local
  transport path that allows command injection beyond the validated
  argv-based execution APX uses
- **Signature/identity vulnerabilities** — issues in `CredentialHandle`
  handling, `AuthContext` construction, or the optional OpenPower JWT
  adapter (`auth_openpower.py`)

## What's explicitly not a vulnerability report

- "APX lets an authorized, correctly-permissioned actor do a destructive
  thing" — that's the design; policy and confirmation are the control,
  not a promise that authorized actions are impossible
- A provider you wrote yourself leaking its own secrets — that's a bug in
  your provider, not APX Core, unless APX's own redaction should have
  caught it and didn't

## Process

1. Report privately.
2. We confirm and assess severity.
3. A fix is developed, generally without a public branch/PR describing
   the vulnerability until release.
4. A new version ships with the fix.
5. We credit the reporter (unless you'd rather stay anonymous) once it's
   safe to disclose.

We do not currently run a paid bug bounty program.
