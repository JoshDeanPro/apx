# AI Contribution Policy

APX explicitly welcomes AI-assisted work: AI-generated Actions, plugins,
adapters, provider implementations, documentation, tests, and ordinary
code contributions. Given what APX is for, it would be strange to do
otherwise.

AI-assisted contributions meet the same bar as anything else:

- security
- licensing
- review
- quality
- provenance
- testing

There is no separate, weaker review lane for AI-generated work, and no
penalty for using AI either. It's evaluated on the result.

## Who's responsible

The **human contributor submitting the change is responsible for it** —
for its correctness, its licensing, and its behavior — regardless of how
much AI assistance was involved in writing it. An AI model is not the
copyright owner or contributor-of-record; current law and this project's
policy don't support treating it as one. If you submit AI-assisted work,
you're vouching for it the same way you would for anything you wrote by
hand.

## Provenance in Action metadata

APX's `provenance` field on `ActionDefinition` already distinguishes
`generated_component` from `native_provider`/`official_plugin`/etc. (see
[docs/action-providers.md](docs/action-providers.md)) — use it honestly.
An AI-generated Action should say so; provenance grants no extra
authority and hides nothing.

## What this doesn't change

- Generated code still needs tests.
- Generated components still go through normal policy/permission scoping
  — see [Let an agent build the missing action](https://openpower.one/apx/ai-components).
- Generated contributions still go through the same PR review as
  [CONTRIBUTING.md](CONTRIBUTING.md) describes.
