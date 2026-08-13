import unittest

from apx.identity import ActorRegistry
from apx.policy import PolicyEngine, RolePolicy, ScopedRule


def engine(actors_raw, roles_raw):
    actors=ActorRegistry.from_config(actors_raw)
    return PolicyEngine.from_config(roles_raw,actors)


class PolicyTests(unittest.TestCase):
    def test_disabled_engine_allows_everything(self):
        eng=engine([],[])
        self.assertFalse(eng.enabled)
        decision=eng.evaluate("agent:claude:mac","project.deploy")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason,"policy not configured")

    def test_no_applicable_allow_denies_with_explainable_reason(self):
        eng=engine([{"id":"agent:claude:mac","roles":["developer"]}],[{"name":"developer","allow":[{"action":"project.inspect"}]}])
        decision=eng.evaluate("agent:claude:mac","project.deploy")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason,"No applicable allow policy.")

    def test_wildcard_action_allows(self):
        eng=engine([{"id":"human:ethan","roles":["admin"]}],[{"name":"admin","allow":[{"action":"*"}]}])
        self.assertTrue(eng.evaluate("human:ethan","host.shutdown").allowed)

    def test_glob_action_prefix_matches(self):
        eng=engine([{"id":"agent:claude:mac","roles":["developer"]}],[{"name":"developer","allow":[{"action":"project.*"}]}])
        self.assertTrue(eng.evaluate("agent:claude:mac","project.deploy").allowed)
        self.assertFalse(eng.evaluate("agent:claude:mac","service.restart").allowed)

    def test_scoped_allow_respects_project_dimension(self):
        eng=engine([{"id":"agent:claude:vps","roles":["deployer"]}],[{"name":"deployer","allow":[{"action":"service.restart","scope":{"project":["palisbot"]}}]}])
        self.assertTrue(eng.evaluate("agent:claude:vps","service.restart",{"project":"palisbot"}).allowed)
        self.assertFalse(eng.evaluate("agent:claude:vps","service.restart",{"project":"other"}).allowed)
        self.assertFalse(eng.evaluate("agent:claude:vps","service.restart",{}).allowed)

    def test_scope_written_as_a_bare_string_is_not_silently_exploded_into_characters(self):
        # scope = { project = "palisbot" } (a string, not an array) is an easy config mistake --
        # tuple("palisbot") would silently become ('p','a','l',...) and could never match anything.
        eng=engine([{"id":"agent:claude:vps","roles":["deployer"]}],[{"name":"deployer","allow":[{"action":"service.restart","scope":{"project":"palisbot"}}]}])
        self.assertTrue(eng.evaluate("agent:claude:vps","service.restart",{"project":"palisbot"}).allowed)

    def test_explicit_deny_wins_over_allow(self):
        eng=engine(
            [{"id":"agent:claude:home","roles":["developer"]}],
            [{"name":"developer","allow":[{"action":"file.write"},{"action":"project.deploy"}],"deny":[{"action":"project.deploy"}]}],
        )
        decision=eng.evaluate("agent:claude:home","project.deploy")
        self.assertFalse(decision.allowed)
        self.assertIn("explicit deny",decision.reason)
        self.assertTrue(eng.evaluate("agent:claude:home","file.write").allowed)

    def test_state_scoped_rule(self):
        eng=engine([{"id":"agent:claude:vps","roles":["responder"]}],[{"name":"responder","allow":[{"action":"logs.read","scope":{"state":["incident","lockdown"]}}]}])
        self.assertFalse(eng.evaluate("agent:claude:vps","logs.read",{},"normal").allowed)
        self.assertTrue(eng.evaluate("agent:claude:vps","logs.read",{},"incident").allowed)

    def test_host_scope_matches_two_host_actions_by_either_endpoint(self):
        # file.copy/file.sync populate source_host/destination_host, not "host" -- a deny
        # scoped to a sensitive host must still catch it on either end of the transfer.
        eng=engine(
            [{"id":"agent:claude:mac","roles":["copier"]}],
            [{"name":"copier","allow":[{"action":"file.*"}],"deny":[{"action":"file.*","scope":{"host":["prod"]}}]}],
        )
        self.assertFalse(eng.evaluate("agent:claude:mac","file.copy",{"source_host":"prod","destination_host":"dev"}).allowed)
        self.assertFalse(eng.evaluate("agent:claude:mac","file.copy",{"source_host":"dev","destination_host":"prod"}).allowed)
        self.assertTrue(eng.evaluate("agent:claude:mac","file.copy",{"source_host":"dev","destination_host":"staging"}).allowed)
        # single-host actions still work via the plain "host" target key
        self.assertFalse(eng.evaluate("agent:claude:mac","file.sync",{"host":"prod"}).allowed)

    def test_might_allow_is_scope_agnostic_convenience_only(self):
        eng=engine([{"id":"agent:claude:vps","roles":["deployer"]}],[{"name":"deployer","allow":[{"action":"service.restart","scope":{"project":["palisbot"]}}]}])
        # might_allow ignores scope -- listed as available even though a specific target could still be denied.
        self.assertTrue(eng.might_allow("agent:claude:vps","service.restart"))
        self.assertFalse(eng.evaluate("agent:claude:vps","service.restart",{"project":"other"}).allowed)

    def test_explain_matches_evaluate(self):
        eng=engine([{"id":"human:ethan","roles":["admin"]}],[{"name":"admin","allow":[{"action":"*"}]}])
        self.assertEqual(eng.explain("human:ethan","anything"),eng.evaluate("human:ethan","anything"))


if __name__ == "__main__": unittest.main()
