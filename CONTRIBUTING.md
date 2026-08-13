# Contributing to APX

Thanks for considering it. This document explains how contribution
actually works here — kept intentionally light for an early project.

## What you can contribute

- Bug fixes
- New core Actions, Resources, or transports
- Providers and plugins (see [Build a plugin](https://openpower.one/apx/build-a-plugin)
  and [Build an APX Server](https://openpower.one/apx/build-a-server))
- SDK improvements
- Documentation
- Tests
- Security fixes (see [SECURITY.md](SECURITY.md) for the private
  reporting path — please don't open a public issue for a vulnerability)
- Specification proposals for larger changes (see
  [APX-ENHANCEMENTS.md](APX-ENHANCEMENTS.md))

Small contributions — typos, small bug fixes, a new test, an ordinary
plugin Action — don't need process. Open a PR.

## Before you start on something large

For anything that changes a core primitive, protocol behavior,
confirmation level, wire format, Action semantics broadly, or a
Commerce/compatibility profile, open an
[APX Enhancement Proposal](APX-ENHANCEMENTS.md) first. It's a short
document, not a committee process — the point is to avoid a large PR
landing on a design nobody agreed to yet.

## Workflow

1. Open an issue or AEP for anything non-trivial; skip this for small
   fixes.
2. Fork the repository, make your change.
3. Add or update tests. `python -m pytest` should pass.
4. Open a pull request describing what changed and why.
5. A maintainer reviews for correctness, security, compatibility, and
   fit with the project's direction (see [GOVERNANCE.md](GOVERNANCE.md)).

Submitting a PR does not automatically make it part of official APX.
Maintainers review every change; acceptance into the canonical project is
a governance decision, not a merge-button formality.

## What review actually checks

- Does it work, with tests proving it?
- Does it introduce a security or credential-handling issue?
- Does it break backward compatibility without a documented reason?
- Does it belong in APX Core, or is it better as a plugin/provider (see
  the "would this still make sense for someone who never uses OpenPower"
  test in the README)?
- Is Action metadata (risk, confirmation, reversibility) honest? See
  [CONFORMANCE.md](CONFORMANCE.md).

## Licensing of your contribution

By submitting a contribution, you agree it's licensed under
[MPL-2.0](LICENSE), same as the rest of the codebase, under the terms
described in [CLA.md](CLA.md) (draft — see that file for its current
status). You keep ownership of what you write.


Welcome — see [AI_POLICY.md](AI_POLICY.md). The human submitting the PR
is responsible for what's in it either way.

## Code of conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
