import unittest

from apx.identity import ActorRegistry, AgentProfile, parse_actor_id


class IdentityTests(unittest.TestCase):
    def test_parse_actor_id(self):
        self.assertEqual(parse_actor_id("agent:runner:node-2"),("agent","runner:node-2"))
        self.assertEqual(parse_actor_id("human:operator"),("human","operator"))

    def test_parse_actor_id_rejects_unknown_kind_and_missing_name(self):
        with self.assertRaises(ValueError): parse_actor_id("robot:x")
        with self.assertRaises(ValueError): parse_actor_id("human:")
        with self.assertRaises(ValueError): parse_actor_id("no-colon")

    def test_agent_profile_kind_must_match_id(self):
        AgentProfile(id="agent:worker:node-1",kind="agent")
        with self.assertRaises(ValueError): AgentProfile(id="agent:worker:node-1",kind="host")

    def test_registry_resolves_default_and_known_actors(self):
        registry=ActorRegistry.from_config([{"id":"agent:runner:node-2","runtime":"worker","host":"server","roles":["developer","deployer"]}])
        self.assertEqual(registry.resolve_default(),"human:local")
        self.assertEqual(registry.roles_for("agent:runner:node-2"),("developer","deployer"))
        self.assertIsNone(registry.get("agent:worker:node-1"))
        self.assertEqual(registry.roles_for("agent:worker:node-1"),())

    def test_registry_honors_configured_default_actor(self):
        registry=ActorRegistry.from_config([],default_actor="human:operator")
        self.assertEqual(registry.resolve_default(),"human:operator")


if __name__ == "__main__": unittest.main()
