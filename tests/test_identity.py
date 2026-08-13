import unittest

from apx.identity import ActorRegistry, AgentProfile, parse_actor_id


class IdentityTests(unittest.TestCase):
    def test_parse_actor_id(self):
        self.assertEqual(parse_actor_id("agent::vps"),("agent",":vps"))
        self.assertEqual(parse_actor_id("human:ethan"),("human","ethan"))

    def test_parse_actor_id_rejects_unknown_kind_and_missing_name(self):
        with self.assertRaises(ValueError): parse_actor_id("robot:x")
        with self.assertRaises(ValueError): parse_actor_id("human:")
        with self.assertRaises(ValueError): parse_actor_id("no-colon")

    def test_agent_profile_kind_must_match_id(self):
        AgentProfile(id="agent::mac",kind="agent")
        with self.assertRaises(ValueError): AgentProfile(id="agent::mac",kind="host")

    def test_registry_resolves_default_and_known_actors(self):
        registry=ActorRegistry.from_config([{"id":"agent::vps","runtime":"","host":"vps","roles":["developer","deployer"]}])
        self.assertEqual(registry.resolve_default(),"human:local")
        self.assertEqual(registry.roles_for("agent::vps"),("developer","deployer"))
        self.assertIsNone(registry.get("agent::mac"))
        self.assertEqual(registry.roles_for("agent::mac"),())

    def test_registry_honors_configured_default_actor(self):
        registry=ActorRegistry.from_config([],default_actor="human:ethan")
        self.assertEqual(registry.resolve_default(),"human:ethan")


if __name__ == "__main__": unittest.main()
