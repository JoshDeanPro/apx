# Optional Content, Offer, Reward, and Campaign Extensions

APX Protocol 0.1 Providers MAY advertise `content`, `offers`, `rewards`,
`campaigns`, `personalization`, or `commerce` in the manifest `extensions`
object. Each value is the extension version. Absence means unsupported; a
Provider remains fully conformant with an empty object.

`ContentVariant`, `Offer`, `Reward`, `Campaign`, `Consent`,
`RelevanceRequest`, `RelevanceResult`, and `RewardReceipt` are generic wire
objects. They do not define an ad marketplace or payment rail. Sponsored
content MUST be labeled. Payment MUST NOT change organic ranking. Sensitive
commercial targeting is default-deny.

Relevance SHOULD be evaluated locally. A result discloses only approved narrow
claims. Raw conversation, prompt, memory, file, private communication, and
unrelated account data MUST NOT be disclosed. Commercial presentation MUST NOT
be injected into system prompts, Action results, tool results, or project
context.

Reward claiming is consequential: Providers SHOULD support PREPARE, bind
transaction confirmation to exact reward terms, and return a receipt. APX does
not settle money. Provider policy remains authoritative.

Password managers expose opaque credential pathways; financial Resources
expose inspection and prepared Actions without serializing credentials.
Subscription observations are non-authoritative until related to and resolved
by a Provider-owned Resource.
