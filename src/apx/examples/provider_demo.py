# SPDX-License-Identifier: MIT
"""Actual end-to-end Action Provider demonstration: `python -m apx.examples.provider_demo`."""
from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from pathlib import Path

from ..cloud import APX
from .subscriptions import build_reference_provider


def run_demo() -> dict:
    with tempfile.TemporaryDirectory() as directory:
        config=Path(directory)/"apx.toml"
        config.write_text('''version=1
[[hosts]]
name="local"
transport="local"
[[actors]]
id="agent:test"
kind="agent"
roles=["reader"]
[[roles]]
name="reader"
allow=[{action="subscription.inspect"}]
[[roles]]
name="subscriber"
allow=[{action="subscription.*"}]
''')
        apx=APX(config,plugins=False); manifest=apx.register_provider(build_reference_provider())
        auth={"principal_id":"agent:test","principal_type":"agent","authentication_method":"test"}
        inspect=apx.run("subscription.inspect",actor="agent:test")
        denied=apx.run("subscription.cancel",actor="agent:test",auth_context=auth,confirmation={"level":"confirm","confirmed":True})
        profile=apx.actors.get("agent:test")
        apx.actors.actors["agent:test"]=replace(profile,roles=("reader","subscriber"))
        purchase=apx.prepare("subscription.start",actor="agent:test",plan="Example Plus")
        started=apx.run("subscription.start",actor="agent:test",auth_context=auth,plan="Example Plus",
            confirmation={"level":"transaction","confirmed":True,"authorization_id":"demo-purchase","terms":purchase.confirmation_terms})
        cancel_prepared=apx.prepare("subscription.cancel",actor="agent:test")
        needs_confirmation=apx.run("subscription.cancel",actor="agent:test",auth_context=auth)
        cancelled=apx.run("subscription.cancel",actor="agent:test",auth_context=auth,
            confirmation={"level":"confirm","confirmed":True,"authorization_id":"demo-cancel"})
        after_cancel=apx.run("subscription.inspect",actor="agent:test")
        resumed=apx.run("subscription.resume",actor="agent:test",auth_context=auth,
            confirmation={"level":"confirm","confirmed":True,"authorization_id":"demo-resume"})
        final=apx.run("subscription.inspect",actor="agent:test")
        return {
            "provider":manifest.provider.id,"discovered_actions":[a.id for a in manifest.actions],
            "self_description":[a.to_dict() for a in apx.action_definitions() if a.provider==manifest.provider.id],
            "inspect":inspect.result,"policy_before_delegation":denied.error.code,
            "delegation":"reader + subscriber role assigned by test harness",
            "purchase_prepared":purchase.to_dict(),"purchase_status":started.status,
            "cancel_prepared":cancel_prepared.to_dict(),"confirmation_gate":needs_confirmation.status,
            "cancel_receipt":cancelled.receipt.to_dict(),"state_after_cancel":after_cancel.result,
            "reverse_action":cancelled.receipt.reverse_action,"resume_receipt":resumed.receipt.to_dict(),
            "restored_state":final.result,"events":[event.name for event in apx.events.history],
        }


if __name__=="__main__": print(json.dumps(run_demo(),indent=2))
