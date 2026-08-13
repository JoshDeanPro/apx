import tempfile
import unittest
from pathlib import Path

from localcloud import LocalCloud
from localcloud.protocol import MCPServer


def config(tmp_path: Path, extra: str = "") -> Path:
    path=tmp_path/"localcloud.toml"
    path.write_text('version=1\n[[hosts]]\nname="test"\ntransport="local"\n[[projects]]\nname="demo"\ndescription="demo"\n'+extra)
    return path


class MissionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.cloud=LocalCloud(config(Path(self.temp.name)),plugins=False)

    def tearDown(self): self.temp.cleanup()

    def create_mission(self, **overrides):
        fields=dict(project="demo",title="Fix bug",objective="Repair the thing",success_criteria=["tests pass"])
        fields.update(overrides)
        return self.cloud.run("mission.create",**fields).result

    def test_mission_create_requires_known_project(self):
        result=self.cloud.run("mission.create",project="missing",title="x",objective="y")
        self.assertFalse(result.ok)

    def test_mission_starts_proposed_and_moves_through_lifecycle(self):
        mission=self.create_mission()
        self.assertEqual(mission["status"],"proposed")
        started=self.cloud.run("mission.start",mission=mission["id"]).result
        self.assertEqual(started["status"],"active")
        self.assertIsNotNone(started["started_at"])

    def test_completed_and_verified_are_distinct(self):
        mission=self.create_mission()
        self.cloud.run("mission.start",mission=mission["id"])
        completed=self.cloud.run("mission.complete",mission=mission["id"]).result
        self.assertEqual(completed["status"],"completed")
        unmet=self.cloud.run("mission.verify",mission=mission["id"],criteria_met=[]).result
        self.assertEqual(unmet["status"],"completed")  # not yet verified
        self.assertFalse(unmet["verification"]["verified"])
        met=self.cloud.run("mission.verify",mission=mission["id"],criteria_met=["tests pass"]).result
        self.assertEqual(met["status"],"verified")
        self.assertTrue(met["verification"]["verified"])

    def test_mission_cannot_complete_with_unresolved_blocker(self):
        mission=self.create_mission()
        self.cloud.run("blocker.create",mission=mission["id"],kind="credential",description="missing token")
        result=self.cloud.run("mission.complete",mission=mission["id"])
        self.assertFalse(result.ok)
        self.assertIn("unresolved blockers",result.error.message)

    def test_mission_list_filters_by_project_and_status(self):
        self.create_mission()
        other=self.create_mission(project="demo",title="Other",objective="Other work")
        self.cloud.run("mission.start",mission=other["id"])
        active=self.cloud.run("mission.list",status="active").result["missions"]
        self.assertEqual([m["id"] for m in active],[other["id"]])


class TaskLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.cloud=LocalCloud(config(Path(self.temp.name)),plugins=False)
        self.mission=self.cloud.run("mission.create",project="demo",title="Fix bug",objective="Repair the thing").result

    def tearDown(self): self.temp.cleanup()

    def create_task(self, **overrides):
        fields=dict(mission=self.mission["id"],title="diagnose",reason="need root cause before fixing")
        fields.update(overrides)
        return self.cloud.run("task.create",**fields).result

    def test_task_reason_explains_relationship_to_mission(self):
        task=self.create_task()
        self.assertEqual(task["reason"],"need root cause before fixing")
        self.assertEqual(task["mission"],self.mission["id"])

    def test_task_start_fails_on_unmet_dependency(self):
        first=self.create_task(title="step 1")
        second=self.create_task(title="step 2",dependencies=[first["id"]])
        result=self.cloud.run("task.start",task=second["id"])
        self.assertFalse(result.ok)
        self.cloud.run("task.start",task=first["id"]); self.cloud.run("task.verify",task=first["id"])
        self.assertTrue(self.cloud.run("task.start",task=second["id"]).ok)

    def test_task_cannot_complete_with_unresolved_blocker(self):
        task=self.create_task()
        self.cloud.run("task.start",task=task["id"])
        self.cloud.run("blocker.create",mission=self.mission["id"],task=task["id"],kind="service",description="host unreachable")
        result=self.cloud.run("task.complete",task=task["id"])
        self.assertFalse(result.ok)
        self.assertEqual(self.cloud.run("task.inspect",task=task["id"]).result["status"],"blocked")

    def test_claim_and_release(self):
        task=self.create_task()
        self.cloud.run("task.claim",task=task["id"],claimant="agent::mac")
        conflict=self.cloud.run("task.claim",task=task["id"],claimant="agent::vps")
        self.assertFalse(conflict.ok)
        self.cloud.run("task.release",task=task["id"],claimant="agent::mac")
        self.assertTrue(self.cloud.run("task.claim",task=task["id"],claimant="agent::vps").ok)

    def test_claim_with_no_actor_fails_instead_of_silently_no_op_claiming(self):
        task=self.create_task()
        result=self.cloud.run("task.claim",task=task["id"],claimant=None)
        self.assertFalse(result.ok)
        self.assertIsNone(self.cloud.run("task.inspect",task=task["id"]).result["claimed_by"])
        # a real actor can still claim it afterwards -- the failed attempt left nothing behind
        self.assertTrue(self.cloud.run("task.claim",task=task["id"],claimant="agent::mac").ok)

    def test_task_propose_stores_agents_plan_verbatim(self):
        proposals=[{"title":"reproduce","reason":"establish a baseline"},{"title":"diagnose","reason":"find root cause"}]
        result=self.cloud.run("task.propose",mission=self.mission["id"],proposals=proposals)
        self.assertTrue(result.ok)
        self.assertEqual([t["title"] for t in result.result["tasks"]],["reproduce","diagnose"])

    def test_acceptance_criteria_verification(self):
        task=self.create_task(acceptance_criteria=["no regressions"])
        self.cloud.run("task.start",task=task["id"])
        unmet=self.cloud.run("task.verify",task=task["id"],criteria_met=[]).result
        self.assertEqual(unmet["status"],"active")
        met=self.cloud.run("task.verify",task=task["id"],criteria_met=["no regressions"]).result
        self.assertEqual(met["status"],"verified")

    def test_conflict_detection_is_advisory_not_blocking(self):
        a=self.create_task(title="a",related_resources=["service:web"])
        b=self.create_task(title="b",related_resources=["service:web"])
        self.cloud.run("task.start",task=a["id"])
        result=self.cloud.run("task.start",task=b["id"])
        self.assertTrue(result.ok)  # never blocks
        self.assertEqual(result.result["conflicts"][0]["task"],a["id"])


class FindingsDecisionsBlockersEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.cloud=LocalCloud(config(Path(self.temp.name)),plugins=False)
        self.mission=self.cloud.run("mission.create",project="demo",title="Fix bug",objective="Repair").result
        self.task=self.cloud.run("task.create",mission=self.mission["id"],title="diagnose",reason="root cause").result

    def tearDown(self): self.temp.cleanup()

    def test_finding_does_not_create_a_task(self):
        before=len(self.cloud.run("task.list",mission=self.mission["id"]).result["tasks"])
        self.cloud.run("finding.create",mission=self.mission["id"],summary="backup process looks broken",category="future_work")
        after=len(self.cloud.run("task.list",mission=self.mission["id"]).result["tasks"])
        self.assertEqual(before,after)

    def test_decision_is_recorded_with_reason(self):
        result=self.cloud.run("decision.record",subject="Caddy",decision="Keep Caddy",reason="production config is healthy",mission=self.mission["id"])
        self.assertTrue(result.ok)
        self.assertEqual(result.result["reason"],"production config is healthy")

    def test_blocker_lifecycle(self):
        blocker=self.cloud.run("blocker.create",mission=self.mission["id"],task=self.task["id"],kind="credential",description="cloudflare token missing").result
        self.assertEqual(self.cloud.run("task.inspect",task=self.task["id"]).result["status"],"blocked")
        resolved=self.cloud.run("blocker.resolve",blocker=blocker["id"],resolution="rotated token").result
        self.assertIsNotNone(resolved["resolved_at"])

    def test_evidence_attach(self):
        result=self.cloud.run("evidence.attach",task=self.task["id"],kind="test_result",summary="143 passed",reference="ci-run-42")
        self.assertTrue(result.ok)
        self.assertEqual(self.cloud.run("task.inspect",task=self.task["id"]).result["id"],self.task["id"])

    def test_blocker_against_unknown_task_fails_cleanly_not_a_raw_crash(self):
        result=self.cloud.run("blocker.create",mission=self.mission["id"],kind="x",description="y",task="tk-does-not-exist")
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code,"action.failed")
        self.assertIn("unknown task",result.error.message)


class ScopeChangeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.cloud=LocalCloud(config(Path(self.temp.name)),plugins=False)
        self.mission=self.cloud.run("mission.create",project="demo",title="Fix OAuth",objective="Fix callback").result

    def tearDown(self): self.temp.cleanup()

    def test_request_and_approve(self):
        request=self.cloud.run("mission.scope_change.request",mission=self.mission["id"],reason="middleware can't support this",impact="auth architecture changes",requested_by="agent::mac").result
        self.assertEqual(request["status"],"pending")
        resolved=self.cloud.run("mission.scope_change.resolve",request_id=request["id"],status="approved",resolution="go ahead").result
        self.assertEqual(resolved["status"],"approved")

    def test_invalid_resolution_status_rejected(self):
        request=self.cloud.run("mission.scope_change.request",mission=self.mission["id"],reason="x",impact="y").result
        result=self.cloud.run("mission.scope_change.resolve",request_id=request["id"],status="maybe")
        self.assertFalse(result.ok)


ROLE_CONFIG = '''
[[actors]]
id="human:local"
roles=["admin"]
[[actors]]
id="agent::mac"
roles=["developer"]
[[roles]]
name="admin"
[[roles.allow]]
action="*"
[[roles]]
name="developer"
[[roles.allow]]
action="project.inspect"
[[roles.deny]]
action="host.shutdown"
'''


class MissionScopedPermissionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.cloud=LocalCloud(config(Path(self.temp.name),ROLE_CONFIG),plugins=False)
        self.mission=self.cloud.run("mission.create",project="demo",title="Deploy fix",objective="Ship it").result

    def tearDown(self): self.temp.cleanup()

    def test_denied_without_grant(self):
        result=self.cloud.run("service.restart",actor="agent::mac",host="test",service="x")
        self.assertFalse(result.ok); self.assertEqual(result.error.code,"permission_denied")

    def test_mission_grant_allows_while_mission_active(self):
        self.cloud.run("mission.grant",mission=self.mission["id"],grantee="agent::mac",action="service.restart")
        # proposed mission (not yet active) does not grant
        denied=self.cloud.run("policy.explain",subject="agent::mac",requested_action="service.restart")
        self.assertFalse(denied.result["allowed"])
        self.cloud.run("mission.start",mission=self.mission["id"])
        allowed=self.cloud.run("policy.explain",subject="agent::mac",requested_action="service.restart")
        self.assertTrue(allowed.result["allowed"])
        self.assertIn("mission-scoped grant",allowed.result["reason"])

    def test_grant_expires_when_mission_ends(self):
        self.cloud.run("mission.grant",mission=self.mission["id"],grantee="agent::mac",action="service.restart")
        self.cloud.run("mission.start",mission=self.mission["id"])
        self.assertTrue(self.cloud.run("policy.explain",subject="agent::mac",requested_action="service.restart").result["allowed"])
        self.cloud.run("mission.cancel",mission=self.mission["id"],reason="no longer needed")
        self.assertFalse(self.cloud.run("policy.explain",subject="agent::mac",requested_action="service.restart").result["allowed"])

    def test_grant_never_overrides_explicit_static_deny(self):
        self.cloud.run("mission.grant",mission=self.mission["id"],grantee="agent::mac",action="host.shutdown")
        self.cloud.run("mission.start",mission=self.mission["id"])
        result=self.cloud.run("policy.explain",subject="agent::mac",requested_action="host.shutdown")
        self.assertFalse(result.result["allowed"])
        self.assertIn("explicit deny",result.result["reason"])

    def test_actor_cannot_grant_a_permission_it_does_not_itself_hold(self):
        # agent::mac only has "developer" (project.inspect); it must not be able to
        # self-escalate to secret.reveal just because it can call mission.grant at all.
        self.cloud.run("mission.start",mission=self.mission["id"])
        escalation=self.cloud.run("mission.grant",actor="agent::mac",mission=self.mission["id"],grantee="agent::mac",action="secret.reveal")
        self.assertFalse(escalation.ok)
        self.assertEqual(escalation.error.code,"permission_denied")
        self.assertFalse(self.cloud.run("policy.explain",subject="agent::mac",requested_action="secret.reveal").result["allowed"])

    def test_actor_can_grant_a_permission_it_does_hold(self):
        # human:local is "admin" (wildcard allow) and legitimately holds project.inspect.
        result=self.cloud.run("mission.grant",mission=self.mission["id"],grantee="agent::mac",action="project.inspect")
        self.assertTrue(result.ok)


class WorkContextAndResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.cloud=LocalCloud(config(Path(self.temp.name)),plugins=False)
        self.mission=self.cloud.run("mission.create",project="demo",title="Fix bug",objective="Repair",constraints=["do not touch billing"]).result
        self.task=self.cloud.run("task.create",mission=self.mission["id"],title="diagnose",reason="root cause",related_resources=["service:web"],acceptance_criteria=["root cause identified"]).result

    def tearDown(self): self.temp.cleanup()

    def test_work_current_is_scoped_not_the_whole_environment(self):
        self.cloud.run("task.claim",task=self.task["id"],claimant="agent::mac")
        self.cloud.run("task.start",task=self.task["id"])
        context=self.cloud.run("work.current",subject="agent::mac").result
        self.assertEqual(context["task"]["id"],self.task["id"])
        self.assertEqual(context["related_resources"],["service:web"])
        self.assertEqual(context["constraints"],["do not touch billing"])
        self.assertNotIn("porkbun",str(context).lower())

    def test_work_current_empty_when_nothing_claimed(self):
        context=self.cloud.run("work.current",subject="agent:codex:mac").result
        self.assertIsNone(context["task"])

    def test_mission_resume_gives_cold_start_agent_enough_to_continue(self):
        self.cloud.run("task.claim",task=self.task["id"],claimant="agent::mac")
        self.cloud.run("task.start",task=self.task["id"])
        self.cloud.run("finding.create",mission=self.mission["id"],summary="found it",category="relevant")
        self.cloud.run("decision.record",subject="approach",decision="patch in place",reason="minimal risk",mission=self.mission["id"])
        snapshot=self.cloud.run("mission.resume",mission=self.mission["id"]).result
        self.assertEqual(snapshot["active_task"]["id"],self.task["id"])
        self.assertEqual(len(snapshot["findings"]),1)
        self.assertEqual(len(snapshot["decisions"]),1)

    def test_mission_docs_ai_audience_has_no_secrets(self):
        result=self.cloud.run("mission.docs",mission=self.mission["id"],audience="ai")
        self.assertTrue(result.ok)
        self.assertIn(self.task["title"],result.result["content"])


class MissionTemplateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.cloud=LocalCloud(config(Path(self.temp.name)),plugins=False)

    def tearDown(self): self.temp.cleanup()

    def test_builtin_templates_available(self):
        result=self.cloud.run("mission_template.list").result
        self.assertIn("bug_fix",result["templates"])
        self.assertIn("steps",result["templates"]["bug_fix"])


class ResourceAndEventTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.cloud=LocalCloud(config(Path(self.temp.name)),plugins=False)

    def tearDown(self): self.temp.cleanup()

    def test_missions_and_tasks_are_axp_resources(self):
        mission=self.cloud.run("mission.create",project="demo",title="Fix bug",objective="Repair").result
        task=self.cloud.run("task.create",mission=mission["id"],title="diagnose",reason="root cause").result
        kinds={r.kind for r in self.cloud.resources()}
        self.assertIn("mission",kinds); self.assertIn("task",kinds)
        ids={r.id for r in self.cloud.resources()}
        self.assertIn(f"mission:{mission['id']}",ids); self.assertIn(f"task:{task['id']}",ids)

    def test_named_events_emitted_for_lifecycle(self):
        events=[]; self.cloud.events.subscribe("*",events.append,owner="test")
        mission=self.cloud.run("mission.create",project="demo",title="x",objective="y").result
        self.cloud.run("mission.start",mission=mission["id"])
        task=self.cloud.run("task.create",mission=mission["id"],title="t",reason="r").result
        self.cloud.run("finding.create",mission=mission["id"],summary="found something")
        names=[e.name for e in events]
        self.assertIn("mission.created",names); self.assertIn("mission.started",names)
        self.assertIn("task.created",names); self.assertIn("finding.created",names)


class InterfaceParityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.cloud=LocalCloud(config(Path(self.temp.name)),plugins=False)

    def tearDown(self): self.temp.cleanup()

    def test_mcp_and_python_use_the_same_mission_action(self):
        python_result=self.cloud.run("mission.create",project="demo",title="Via Python",objective="x")
        server=MCPServer(self.cloud)
        request={"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"mission_create","arguments":{"project":"demo","title":"Via MCP","objective":"y"}}}
        mcp_result=server.dispatch(request)["result"]["structuredContent"]
        self.assertTrue(python_result.ok); self.assertTrue(mcp_result["ok"])
        titles={m["title"] for m in self.cloud.run("mission.list").result["missions"]}
        self.assertEqual(titles,{"Via Python","Via MCP"})


if __name__ == "__main__": unittest.main()
