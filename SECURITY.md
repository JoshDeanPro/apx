# APX Security Model

APX uses a zero-trust, minimum-disclosure model:

- Local APX starts with a loopback-only HTTP server unless the operator explicitly configures remote serving with a bearer token.
- Provider discovery is public capability metadata only; credentials, local paths, unrelated providers, devices, plugins, and client state are not part of the public manifest.
- Credential values stay in credential backends and are resolved only for the authorized action that needs them. Credential references are not secret values.
- Child processes receive a minimal environment by default. SSH agent access is passed only to SSH transport when explicitly present.
- Ordinary errors are mapped to safe protocol messages; local checks and logs are not a sandbox.
- Python in-process plugins/providers are trusted-code boundaries, not containment boundaries. Untrusted code requires an OS/process/container sandbox that APX does not currently mandate or provide.
- Filesystem, network, SSH, policy, confirmation, and actor restrictions remain enforced by the existing runtime and OS.

Run `apx security check` for a fast, offline inspection of configuration exposure, state-file permissions, plaintext endpoints, public binds, enabled plugins, and debug mode. Findings are warnings or failures with an actionable next step; the command never resolves or prints secrets.

Report security issues privately through the repository's configured GitHub security reporting channel. Do not include credentials, tokens, private keys, personal data, or private host details in issues or pull requests.
