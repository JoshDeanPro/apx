import json
import subprocess
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from jsonschema.validators import Draft202012Validator

from apx import APXClient, ActionProvider, ActionRequest, CredentialHandle, HTTPClientTransport, HTTPProviderAdapter, LocalClientTransport, OperationAccepted, ProviderSession
from apx.conformance import client_conformance, provider_conformance
from apx.examples.subscriptions import build_reference_provider


def confirmation(prepared, nonce="confirmation-1"):
    return {"level":prepared.confirmation_required,"confirmed":True,"authorization_id":nonce,
            "expires_at":(datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat(),
            "terms":prepared.confirmation_terms}


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.provider=build_reference_provider(); self.session=ProviderSession(self.provider)
        self.client=APXClient(LocalClientTransport(self.session))
        purchase=self.client.prepare("subscription.start",input={"plan":"Example Plus"},actor="human:owner")
        self.client.authorize(purchase.prepared_action_id,confirmation(purchase,"purchase"))
        self.client.execute("subscription.start",input={"plan":"Example Plus"},actor="human:owner",
            prepared_action_id=purchase.prepared_action_id,idempotency_key="purchase",authoritative_state_version=purchase.authoritative_state_version)

    def test_published_schemas_validate_wire_messages(self):
        root=Path(__file__).parents[1]/"spec"/"schemas"
        for name,value in (("provider-manifest.schema.json",self.provider.manifest().to_dict()),
                           ("action-request.schema.json",ActionRequest("subscription.inspect").to_dict())):
            Draft202012Validator(json.loads((root/name).read_text())).validate(value)

    def test_cancel_before_commit_has_no_effect(self):
        prepared=self.client.prepare("subscription.cancel",actor="human:owner")
        result=self.client.cancel(prepared.prepared_action_id)
        self.assertEqual(result.status,"cancelled"); self.assertFalse(result.result["committed"])
        self.assertTrue(self.client.execute("subscription.inspect").result["renewal"])

    def test_exactly_once_and_ambiguous_response_recovery(self):
        prepared=self.client.prepare("subscription.cancel",actor="human:owner")
        self.client.authorize(prepared.prepared_action_id,confirmation(prepared))
        kwargs=dict(actor="human:owner",prepared_action_id=prepared.prepared_action_id,idempotency_key="cancel-once",
                    authoritative_state_version=prepared.authoritative_state_version)
        first=self.client.execute("subscription.cancel",**kwargs)
        duplicates=[self.client.execute("subscription.cancel",**kwargs) for _ in range(50)]
        self.assertTrue(all(item.receipt.receipt_id==first.receipt.receipt_id for item in duplicates))
        self.assertEqual(self.client.status(first.request_id).receipt.receipt_id,first.receipt.receipt_id)
        self.assertEqual(first.result["cancellations"],1)

    def test_confirmation_replay_and_intent_change_fail_closed(self):
        prepared=self.client.prepare("subscription.cancel",actor="human:owner")
        proof=confirmation(prepared,"once")
        self.assertEqual(self.client.authorize(prepared.prepared_action_id,proof).status,"authorized")
        another=self.client.prepare("subscription.cancel",actor="human:owner")
        self.assertEqual(self.client.authorize(another.prepared_action_id,proof).status,"authorization_required")
        changed=self.client.execute("subscription.cancel",input={"invented":True},actor="human:owner",
            prepared_action_id=prepared.prepared_action_id,idempotency_key="changed",authoritative_state_version=prepared.authoritative_state_version)
        self.assertEqual(changed.error.code,"precondition_failed")

    def test_stale_state_and_provider_denial(self):
        prepared=self.client.prepare("subscription.cancel",actor="human:owner")
        self.client.authorize(prepared.prepared_action_id,confirmation(prepared))
        self.provider._actions["subscription.resume"].registered.handler()
        stale=self.client.execute("subscription.cancel",actor="human:owner",prepared_action_id=prepared.prepared_action_id,
            idempotency_key="stale",authoritative_state_version=prepared.authoritative_state_version)
        self.assertEqual(stale.error.code,"precondition_failed")
        refund=self.client.prepare("order.refund.request",input={"order_id":"order-123"},actor="human:owner")
        self.client.authorize(refund.prepared_action_id,confirmation(refund,"refund"))
        denied=self.client.execute("order.refund.request",input={"order_id":"order-123"},actor="human:owner",
            prepared_action_id=refund.prepared_action_id,idempotency_key="refund",authoritative_state_version=refund.authoritative_state_version)
        self.assertEqual(denied.status,"denied"); self.assertEqual(denied.error.code,"policy_denied")
        self.assertEqual(denied.error.next_actions,("support.case.create",))

    def test_verification_failure_never_claims_completed(self):
        action=self.provider._actions["subscription.cancel"].registered
        object.__setattr__(action,"verify_handler",lambda result: False)
        prepared=self.client.prepare("subscription.cancel",actor="human:owner")
        self.client.authorize(prepared.prepared_action_id,confirmation(prepared))
        result=self.client.execute("subscription.cancel",actor="human:owner",prepared_action_id=prepared.prepared_action_id,
            idempotency_key="verify",authoritative_state_version=prepared.authoritative_state_version)
        self.assertEqual(result.status,"verification_failed"); self.assertFalse(result.ok)

    def test_conformance_helpers(self):
        self.assertEqual(provider_conformance(self.provider),[])
        self.assertEqual(client_conformance(self.client,read_action="subscription.inspect"),[])

    def test_durable_idempotency_receipt_and_status_survive_restart(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            database=Path(directory)/"provider.sqlite3"
            prepared=self.client.prepare("subscription.cancel",actor="human:owner")
            # Use a durable session from the preparation onward.
            first=ProviderSession(self.provider,state_path=database); durable=APXClient(LocalClientTransport(first))
            prepared=durable.prepare("subscription.cancel",actor="human:owner")
            durable.authorize(prepared.prepared_action_id,confirmation(prepared,"durable"))
            result=durable.execute("subscription.cancel",actor="human:owner",prepared_action_id=prepared.prepared_action_id,
                idempotency_key="durable-cancel",authoritative_state_version=prepared.authoritative_state_version)
            receipt_id=result.receipt.receipt_id; request_id=result.request_id; first.close()
            restored=ProviderSession(self.provider,state_path=database); recovered=APXClient(LocalClientTransport(restored))
            duplicate=recovered.execute("subscription.cancel",actor="human:owner",idempotency_key="durable-cancel")
            self.assertEqual(duplicate.receipt.receipt_id,receipt_id)
            self.assertEqual(recovered.status(request_id).receipt.receipt_id,receipt_id)
            self.assertEqual(recovered.receipt(receipt_id).status,"completed"); restored.close()

    def test_long_running_operation_and_budget(self):
        provider=ActionProvider("jobs.local","Jobs")
        calls={"count":0}
        @provider.action("project.deploy",risk="account_change",confirmation="none",idempotent=True,retry="idempotency_required",
            constraints={"budget":{"maximum":1,"window_seconds":60}})
        def deploy(): calls["count"]+=1; return OperationAccepted("op-deploy")
        session=ProviderSession(provider); client=APXClient(LocalClientTransport(session))
        prepared=client.prepare("project.deploy",actor="agent:test")
        accepted=client.execute("project.deploy",actor="agent:test",prepared_action_id=prepared.prepared_action_id,idempotency_key="deploy-1")
        self.assertEqual(accepted.status,"accepted"); self.assertEqual(client.operation_status("op-deploy").status,"accepted")
        completed=session.complete_operation("op-deploy",result={"deployed":True})
        self.assertEqual(completed.status,"completed"); self.assertIsNotNone(completed.receipt)
        prepared2=client.prepare("project.deploy",actor="agent:test")
        limited=client.execute("project.deploy",actor="agent:test",prepared_action_id=prepared2.prepared_action_id,idempotency_key="deploy-2")
        self.assertEqual(limited.error.code,"rate_limited"); self.assertEqual(calls["count"],1)

    def test_long_running_operation_survives_provider_restart(self):
        import tempfile
        provider=ActionProvider("durable-jobs.local","Durable Jobs")
        @provider.action("project.deploy",risk="account_change",confirmation="none",idempotent=True,retry="idempotency_required")
        def deploy(): return OperationAccepted("op-durable")
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"operations.sqlite3"; first=ProviderSession(provider,state_path=path); client=APXClient(LocalClientTransport(first))
            prepared=client.prepare("project.deploy",actor="agent:test")
            accepted=client.execute("project.deploy",actor="agent:test",prepared_action_id=prepared.prepared_action_id,idempotency_key="durable-op")
            self.assertEqual(accepted.status,"accepted"); first.close()
            restored=ProviderSession(provider,state_path=path)
            self.assertEqual(restored.operation_status("op-durable").status,"accepted")
            self.assertEqual(restored.complete_operation("op-durable",result={"deployed":True}).status,"completed"); restored.close()

    def test_proof_of_possession_requires_transport_verifier(self):
        prepared=self.client.prepare("subscription.cancel",actor="agent:keyed")
        self.client.authorize(prepared.prepared_action_id,confirmation(prepared,"pop"))
        credential=CredentialHandle("cred-1","proof_of_possession","issuer","reference.local",fingerprint="sha256:key")
        denied=self.client.execute("subscription.cancel",actor="agent:keyed",credential=credential,
            prepared_action_id=prepared.prepared_action_id,idempotency_key="pop-denied",authoritative_state_version=prepared.authoritative_state_version)
        self.assertEqual(denied.error.code,"unauthenticated")


class InteropTests(unittest.TestCase):
    def test_independent_typescript_client_over_http(self):
        provider=build_reference_provider(); session=ProviderSession(provider); adapter=HTTPProviderAdapter(provider,session=session)
        starter=APXClient(LocalClientTransport(session)); prepared=starter.prepare("subscription.start",input={"plan":"Plus"},actor="human")
        starter.authorize(prepared.prepared_action_id,confirmation(prepared,"seed")); starter.execute("subscription.start",input={"plan":"Plus"},actor="human",
            prepared_action_id=prepared.prepared_action_id,idempotency_key="seed",authoritative_state_version=prepared.authoritative_state_version)
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self): self.dispatch(None)
            def do_POST(self): self.dispatch(json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))) or b"{}"))
            def dispatch(self,body):
                status,headers,value=adapter.handle(self.command,self.path,body); raw=json.dumps(value).encode()
                self.send_response(status)
                for key,item in headers.items(): self.send_header(key,item)
                self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw)
            def log_message(self,*args): pass
        server=ThreadingHTTPServer(("127.0.0.1",0),Handler); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            script=Path(__file__).parents[1]/"interop"/"typescript"/"client.ts"
            run=subprocess.run(["node",str(script),f"http://127.0.0.1:{server.server_port}"],capture_output=True,text=True,timeout=20)
            self.assertEqual(run.returncode,0,run.stderr); value=json.loads(run.stdout)
            self.assertEqual(value["status"],"completed"); self.assertFalse(value["renewal"])
        finally: server.shutdown(); server.server_close()

    def test_python_client_against_independent_typescript_provider(self):
        script=Path(__file__).parents[1]/"interop"/"typescript"/"provider.ts"
        process=subprocess.Popen(["node",str(script)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            port=json.loads(process.stdout.readline())["port"]; client=APXClient(HTTPClientTransport(f"http://127.0.0.1:{port}"))
            self.assertEqual(client.discover().provider.id,"typescript.local")
            prepared=client.prepare("subscription.cancel",actor="agent:python")
            authorized=client.authorize(prepared.prepared_action_id,confirmation(prepared,"python-ts")); self.assertTrue(authorized.ok)
            result=client.execute("subscription.cancel",actor="agent:python",prepared_action_id=prepared.prepared_action_id,
                idempotency_key="python-ts",authoritative_state_version=prepared.authoritative_state_version)
            duplicate=client.execute("subscription.cancel",actor="agent:python",prepared_action_id=prepared.prepared_action_id,
                idempotency_key="python-ts",authoritative_state_version=prepared.authoritative_state_version)
            self.assertFalse(result.result["renewal"]); self.assertEqual(result.receipt.receipt_id,duplicate.receipt.receipt_id)
        finally:
            process.terminate(); process.wait(timeout=5)


if __name__=="__main__": unittest.main()
