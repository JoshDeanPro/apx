# APX Governance

APX is early. This document describes a **Founder-Steward** governance
model appropriate for that stage — not a foundation, not a voting body,
not a committee. It will evolve as the project and its contributor base
grow; this is a starting point, not a permanent constitution.

## The governing philosophy

> APX should be open enough that anyone can make agents more capable,
> while official APX remains coherent, secure, trustworthy, and
> intentionally stewarded.

> We protect the official project without trying to own the entire
> agentic ecosystem.

> We encourage valuable Actions instead of deciding what agents are
> allowed to want.

> Open source gives people freedom to build. Governance determines what
> becomes official APX.

Concretely, this means two things have to be true at once:

**Project integrity.** Official APX may reject changes that materially
undermine security, privacy, user control, interoperability, protocol
coherence, stability, compatibility, or truthful Action semantics.

**Agentic freedom.** Official APX governance is not used to artificially
suppress legitimate Actions, interoperability, competition, integrations,
or agent capabilities merely because they compete with OpenPower or
another preferred product. See [No Central Action Censorship](#no-central-action-censorship)
below — this is load-bearing, not a footnote.

## Founder / Project Steward

The Founder / Project Steward retains final responsibility for the
official APX Project. Today that is the project's original author (see
git history and [NOTICE](NOTICE)).

The Steward controls, or delegates control over:

- the canonical APX repositories
- acceptance of the APX specification and its changes
- official releases and release signing
- the project roadmap
- maintainer appointment and removal
- security-critical changes
- compatibility rules
- official conformance designations (see [CONFORMANCE.md](CONFORMANCE.md))
- official project infrastructure (openpower.dev, package namespaces, etc.)


This is **governance authority over the official project** — it is not
ownership of contributors' independent work, and not a claim that the
Steward owns copyright in contributions they didn't write (see
[Copyright](#copyright)).

## Maintainers

Maintainers may be appointed by the Steward and given scoped authority
over a specific area (see [MAINTAINERS.md](MAINTAINERS.md) for current
roles). The Steward may revoke maintainer status where required to
protect the project — for cause, not as a matter of course.

## Copyright

Formalizing governance does not transfer copyright ownership away from
whoever actually holds it. The existing copyright holder is documented in
[NOTICE](NOTICE) and [LICENSE](LICENSE). Contributors keep ownership of
their own contributions unless they separately and explicitly agree
otherwise (see [CLA.md](CLA.md)) — official project control and copyright
ownership of a given contribution are not the same thing, and this
document does not conflate them.

## Official vs. unofficial

Open source permits forks, and APX does not fight that. But there is a
real difference between:

- **Official APX** — releases, specification text, and compatibility
  designations that come from the canonical, Steward-controlled project.
- **APX-derived software** — forks, redistributions, and independent
  implementations, all fully permitted under [LICENSE](LICENSE).

A fork may modify APX under the MPL-2.0. It may not represent itself as
an official release, or use the APX/OpenPower names in a way that implies
endorsement it doesn't have — see [TRADEMARKS.md](TRADEMARKS.md) for
exactly where that line is, described generously, not defensively.

## No central Action censorship

APX Core defines **how** Actions are described, permissioned,
authenticated, confirmed, and receipted. It does not centrally decide
every possible **what**.

Applications, businesses, users, developers, and agents may create new
Actions freely. Official APX conformance may decline to designate an
Action or provider as officially compatible if it is malformed,
deceptive, insecure, misrepresented, or incompatible — that's a
conformance judgment (see [CONFORMANCE.md](CONFORMANCE.md)), not a
license restriction, and it never prevents the independent software from
existing and working.

The official project does not reject an Action merely because APX didn't
invent it, OpenPower doesn't use it, another company benefits from it, or
it competes with an OpenPower feature.

## APX vs. OpenPower

APX is open-source infrastructure. [OpenPower](https://openpower.dev) is
an independently operated product/service built on APX — the flagship
implementation, not a requirement. The MPL-2.0 license on APX does not
obligate the project to provide openpower.dev hosted services, accounts,
relays, registry access, databases, or support to every fork. See the

[APX vs OpenPower](README.md#apx-vs-openpower) section of the README for
the technical/architectural version of this boundary.

## Changing this document

Governance changes are themselves subject to the Steward's authority
during this phase. As APX matures and gains more independent
maintainers and contributors, this document is expected to evolve toward
something less founder-centric — that evolution will be documented here
when it happens, not silently assumed.
