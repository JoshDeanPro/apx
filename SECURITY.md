# Security Policy

APX provides permissioned action capability and capability fabric execution. Security and privacy are core requirements.

## Reporting a Vulnerability

Please report security vulnerabilities responsibly through private channels (such as GitHub Security Advisories) rather than public issues or discussion threads.

Include:
- Summary of the vulnerability and impact
- Steps to reproduce or a minimal proof of concept
- Affected versions or components

## Scope

Key security areas:
- **Permission & Policy Enforcement**: Correct evaluation of permissions, roles, and grants.
- **Confirmation Verification**: Enforcing confirmations on mutating and high-risk actions.
- **Credential Protection**: Proper redaction of secrets in logs, receipts, and event streams.
- **Protocol Conformance**: Schema validation and verification of requests, results, and provider manifests.
- **Receipt Integrity**: Verifiable digests and signature integrity.
