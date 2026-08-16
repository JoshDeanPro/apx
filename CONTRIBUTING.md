# Contributing to APX

Thanks for considering it. This document explains how contribution
actually works here — kept intentionally light for an early project.

## What you can contribute

- Bug fixes
- New core Actions, Resources, or transports
- Providers and plugins (see [Build a plugin](https://openpower.dev/apx/build-a-plugin)
  and [Build an APX Server](https://openpower.dev/apx/build-a-server))

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

## Workflow & Branch Protection

1. Fork the repository and create a descriptive feature branch.
2. Implement your changes with clean, readable code.
3. Add or update tests: `pytest` must pass completely.
4. Submit a Pull Request describing your changes, motivation, and test coverage.
5. **Steward Review & Approval**: The `main` branch is protected. Pull requests are never merged automatically. Every change must be reviewed and approved by the Project Steward (**Ethan Gegos**).

## What review actually checks

- Does it work, with tests proving it?
- Does it introduce a security or credential-handling issue?
- Does it break backward compatibility without a documented reason?
- Does it belong in APX Core, or is it better as an independent plugin/provider?
- Is Action metadata (risk, confirmation, reversibility) honest? See [CONFORMANCE.md](CONFORMANCE.md).

## Licensing of your contribution

By submitting a contribution, you agree it is licensed under [MPL-2.0](LICENSE), same as the rest of the codebase. You keep ownership of what you write.

## AI Policy & Credit

AI tools may be used by human developers to assist in writing code, but **no credit or authorship is given to AI models or tools**. The human submitting the PR is the contributor of record and is 100% responsible for the submission. See [AI_POLICY.md](AI_POLICY.md).

## Code of conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

