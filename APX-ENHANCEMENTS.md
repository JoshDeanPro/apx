# APX Enhancement Proposals (AEPs)

A lightweight process for meaningful changes to the APX framework or
specification. Most contributions don't need this — see below.

## When you need an AEP

- A new core primitive (alongside Resource/Action/Policy/Context/etc.)
- New protocol/wire behavior in AXP
- A new standard confirmation or risk level
- Wire protocol (AXP) changes
- Major changes to Action semantics
- Compatibility-breaking changes
- Changes to a Commerce/compatibility profile
- A new official transport (alongside local/SSH/HTTP)

## When you don't

- Typos
- Small bug fixes
- Ordinary plugin/provider Actions (your own `subscription.cancel` for
  your own service doesn't need project-wide sign-off — see
  [Build a plugin](https://openpower.dev/apx/build-a-plugin))

- Routine implementation work that doesn't change a public contract

When in doubt, open an issue and ask before writing the AEP — it's faster
than guessing wrong in either direction.

## Process

1. **Propose.** Anyone can open an AEP as a short document (a GitHub
   issue or PR is fine — no special template is required yet). Describe
   the problem, the proposed change, and what it breaks or doesn't.
2. **Review.** Maintainers (see [MAINTAINERS.md](MAINTAINERS.md))
   discuss it in the open. Expect questions about security,
   compatibility, and whether it belongs in Core versus a plugin/provider.
3. **Decide.** During the current Founder-Steward governance phase (see
   [GOVERNANCE.md](GOVERNANCE.md)), the Steward holds final acceptance
   authority. That's expected to shift toward maintainer consensus as the
   maintainer team grows.
4. **Implement.** An accepted AEP becomes a normal PR under
   [CONTRIBUTING.md](CONTRIBUTING.md) — the AEP is the design agreement,
   not a substitute for tests and review on the actual code.

## What an AEP should say

- **Problem** — what's missing or wrong today
- **Proposal** — the actual change
- **Compatibility** — what breaks, and for whom
- **Alternatives considered** — including "leave it as a plugin instead
  of Core"

Keep it short. The goal is avoiding a large PR landing on a design nobody
agreed to yet, not producing a specification document for its own sake.
