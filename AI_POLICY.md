# AI Contribution Policy

APX allows human contributors to use AI assistance in drafting code, tests, or documentation, but **no credit or authorship is given to AI models or tools**. 

## Strict Human Responsibility & Zero AI Credit

- **No AI Authorship or Credit**: An AI model is not a contributor-of-record, author, or copyright owner. No AI tools, assistants, or LLMs will be listed as authors, co-authors, maintainers, or credited in commit messages, notices, or documentation.
- **Human Contributor Responsibility**: The human contributor submitting the pull request is 100% responsible for the submitted code — its security, correctness, provenance, licensing, and behavior.
- **Steward Review**: No contributions (AI-assisted or manual) are automatically merged into the `main` branch. All pull requests require manual review and explicit approval by the Project Steward (Ethan Gegos).

AI-assisted work meets the exact same rigorous bar as any other contribution:
- Rigorous security and sandboxing
- Complete unit and integration testing
- Strict license conformance (MPL-2.0)
- Full architectural and protocol coherence

## Provenance in Action Metadata

APX's `provenance` field on `ActionDefinition` distinguishes component origins (such as `generated_component` vs `native_provider`/`official_plugin` — see [docs/action-providers.md](docs/action-providers.md)). This metadata is strictly for runtime policy and safety scoping, not for contributor credit.

## What this means in practice

- Generated code must pass all unit tests (`pytest`).
- Generated components must comply with APX policy scoping and capability boundaries.
- Every contribution goes through the pull request review process outlined in [CONTRIBUTING.md](CONTRIBUTING.md) and requires Project Steward approval before merging.

