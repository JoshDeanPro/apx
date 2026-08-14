import itertools
import tempfile
import unittest
from pathlib import Path

from apx import APX
from apx.blueprints import Blueprint, BlueprintError, BlueprintStep, toposort

_authorization_ids = itertools.count()


def config(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "apx.toml"
    path.write_text('version=1\n[[hosts]]\nname="test"\ntransport="local"\n[[projects]]\nname="demo"\ndescription="demo"\n' + extra)
    return path


class BlueprintEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cloud = APX(config(Path(self.temp.name)), plugins=False)
        self.actor = self.cloud.actors.resolve_default()
        self.project_root = Path(self.temp.name) / "proj"

    def tearDown(self): self.temp.cleanup()

    def apply(self, blueprint: str, **overrides):
        action = self.cloud.actions.get("blueprint.apply")
        confirmation = {"level": action.confirmation, "confirmed": True, "authorization_id": f"t:{next(_authorization_ids)}"}
        fields = dict(blueprint=blueprint, project="demo", inputs={"path": str(self.project_root)})
        fields.update(overrides)
        return self.cloud.run("blueprint.apply", actor=self.actor, confirmation=confirmation, **fields)

    # ---- registry / DAG ----

    def test_registry_rejects_unknown_action(self):
        bad = Blueprint(stable_id="bp_x", name="test/bad", version="1.0.0", description="bad",
                         steps=(BlueprintStep("s1", "no.such.action"),))
        with self.assertRaises(BlueprintError):
            self.cloud._register_blueprint(bad)

    def test_step_dependency_cycle_is_rejected(self):
        steps = (BlueprintStep("a", "directory.ensure", after=("b",)), BlueprintStep("b", "directory.ensure", after=("a",)))
        with self.assertRaises(BlueprintError):
            toposort(steps)

    def test_step_after_unknown_id_is_rejected(self):
        with self.assertRaises(ValueError):
            Blueprint(stable_id="bp_y", name="test/bad2", version="1.0.0", description="bad",
                       steps=(BlueprintStep("a", "directory.ensure", after=("nope",)),))

    # ---- composition / dedup ----

    def test_composition_flattens_and_orders_includes(self):
        resolved = self.cloud.blueprint_registry.resolve("project/documented")
        self.assertEqual(len(resolved.steps), 4)
        by_id = {s.id: s for s in resolved.steps}
        self.assertIn("project/documented::architecture_stub", by_id)
        self.assertIn("project/base-layout::docs_dir", by_id["project/documented::architecture_stub"].after)
        self.assertEqual(set(resolved.resulting_capabilities), {"project.structure.base", "project.docs.architecture_stub"})

    def test_diamond_include_deduplicates_shared_steps(self):
        composite_toml = (
            '[[blueprints]]\nname="test/composite"\nversion="1.0.0"\ndescription="diamond"\n'
            'includes=["project/base-layout","project/documented"]\n'
            '[[blueprints.steps]]\nid="noop"\naction="file.exists"\nargs={path="{path}"}\n'
        )
        cloud = APX(config(Path(self.temp.name), extra=composite_toml), plugins=False)
        resolved = cloud.blueprint_registry.resolve("test/composite")
        # 3 base-layout steps + 1 documented-own step + 1 composite-own step, base-layout's
        # steps must not be duplicated even though both includes pull it in.
        self.assertEqual(len(resolved.steps), 5)
        action_counts = {}
        for step in resolved.steps: action_counts[step.action] = action_counts.get(step.action, 0) + 1
        self.assertEqual(action_counts["directory.ensure"], 2)  # src_dir + docs_dir, each once

    # ---- plan / apply / idempotence ----

    def test_plan_reports_will_change_before_apply_and_satisfied_after(self):
        before = self.cloud.run("blueprint.plan", actor=self.actor, blueprint="project/documented", project="demo", inputs={"path": str(self.project_root)})
        self.assertTrue(before.ok)
        self.assertEqual(before.result["will_change"], 4)
        self.assertEqual(before.result["satisfied"], 0)
        result = self.apply("project/documented")
        self.assertTrue(result.ok, result.error)
        after = self.cloud.run("blueprint.plan", actor=self.actor, blueprint="project/documented", project="demo", inputs={"path": str(self.project_root)})
        self.assertEqual(after.result["will_change"], 0)
        self.assertEqual(after.result["satisfied"], 4)

    def test_apply_is_idempotent_on_second_run(self):
        first = self.apply("project/documented")
        self.assertEqual(first.result["changed_count"], 4)
        second = self.apply("project/documented")
        self.assertTrue(second.ok)
        self.assertEqual(second.result["changed_count"], 0)
        self.assertTrue((self.project_root / "src").is_dir())
        self.assertTrue((self.project_root / "docs" / "ARCHITECTURE.md").exists())

    def test_capabilities_and_history_recorded(self):
        self.apply("project/documented")
        status = self.cloud.run("blueprint.status", actor=self.actor, project="demo")
        self.assertTrue(status.ok)
        self.assertEqual(set(status.result["capabilities"]), {"project.structure.base", "project.docs.architecture_stub"})
        self.assertEqual(status.result["applied"]["project/documented"]["version"], "1.0.0")
        self.assertEqual(len(status.result["history"]), 1)
        self.assertEqual(status.result["history"][0]["result"], "applied")

    def test_missing_required_input_fails_cleanly(self):
        result = self.cloud.run("blueprint.apply", actor=self.actor,
                                 confirmation={"level": "confirm", "confirmed": True, "authorization_id": "t:missing"},
                                 blueprint="project/base-layout", project="demo", inputs={})
        self.assertFalse(result.ok)
        self.assertIn("requires input", result.error.message)

    def test_search_and_show(self):
        found = self.cloud.run("blueprint.search", actor=self.actor, query="", tag="scaffold")
        names = {item["name"] for item in found.result["blueprints"]}
        self.assertEqual(names, {"project/base-layout", "project/documented"})
        missing = self.cloud.run("blueprint.show", actor=self.actor, blueprint="no/such/blueprint")
        self.assertFalse(missing.ok)

    def test_upgrade_is_a_no_op_when_already_current(self):
        self.apply("project/base-layout")
        result = self.cloud.run("blueprint.upgrade", actor=self.actor,
                                 confirmation={"level": "confirm", "confirmed": True, "authorization_id": "t:up"},
                                 blueprint="project/base-layout", project="demo", inputs={"path": str(self.project_root)})
        self.assertTrue(result.ok)
        self.assertTrue(result.result["already_current"])

    # ---- failure / partial execution ----

    def test_partial_failure_stops_and_is_recorded_without_rollback(self):
        # a regular file where a directory step wants to create a directory makes
        # directory.ensure raise ActionError -- exercise that a failing step stops
        # the graph, is recorded, and earlier successful steps are left in place.
        self.project_root.mkdir(parents=True)
        (self.project_root / "docs").write_text("not a directory")
        result = self.apply("project/base-layout")
        self.assertFalse(result.ok)
        self.assertTrue((self.project_root / "src").is_dir())  # ran before the failing step
        status = self.cloud.run("blueprint.status", actor=self.actor, project="demo")
        self.assertEqual(status.result["history"][-1]["result"], "failed")
        self.assertEqual(status.result["history"][-1]["failed_step"], "docs_dir")
        self.assertNotIn("project/base-layout", status.result["applied"])

    # ---- permissions ----

    def test_permission_denied_blocks_apply_and_leaves_no_side_effects(self):
        restricted_toml = (
            '[[actors]]\nid="human:local"\nkind="human"\nroles=["viewer"]\n'
            '[[roles]]\nname="viewer"\nallow=[{action="blueprint.list"}]\n'
        )
        cloud = APX(config(Path(self.temp.name), extra=restricted_toml), plugins=False)
        result = cloud.run("blueprint.apply", actor="human:local",
                            confirmation={"level": "confirm", "confirmed": True, "authorization_id": "t:denied"},
                            blueprint="project/base-layout", project="demo", inputs={"path": str(self.project_root)})
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "permission_denied")
        self.assertFalse(self.project_root.exists())


if __name__ == "__main__":
    unittest.main()
