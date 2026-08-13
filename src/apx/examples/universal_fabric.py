# SPDX-License-Identifier: MPL-2.0
"""Runnable, credential-free proofs of the APX universal capability model.

Run with ``python -m apx.examples.universal_fabric``. The physical proof uses
an in-memory Home Assistant-compatible state service; it changes and verifies
real simulator state rather than returning a canned success response.
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from apx.actions import ActionRegistry, RegisteredAction
from apx.bridges.browser import BrowserBridge
from apx.bridges.home_assistant import HomeAssistantBridge
from apx.client import APXClient, LocalClientTransport
from apx.examples.subscriptions import build_reference_provider
from apx.fabric import ActionComponent, ComponentRegistry, CompositionEngine, CompositionStep
from apx.http import HTTPResult
from apx.personal import ContentVariant, PersonalContextStore
from apx.runtime import ProviderSession


class StructuredWebSimulator:
    def __init__(self): self.url = ""; self.fields: dict[str,str] = {}; self.state_reads = 0
    def open(self, url): self.url = url; return {"url":url,"title":"APX form"}
    def structured_state(self):
        self.state_reads += 1
        return {"url":self.url,"elements":[{"ref":"e0","role":"textbox","name":"email"}]}
    def click(self, reference): return {"clicked":reference}
    def fill(self, fields): self.fields.update(fields); return {"filled":sorted(fields)}
    def close(self): pass


class HomeAssistantSimulator:
    def __init__(self): self.state = "off"
    def request(self, method, url, **kwargs):
        if url.endswith("/api/states"):
            value = [{"entity_id":"light.study","state":self.state,"attributes":{"friendly_name":"Study"}}]
        elif "/api/services/light/turn_on" in url:
            self.state = "on"; value = []
        else:
            value = {"entity_id":"light.study","state":self.state,"attributes":{}}
        return HTTPResult(200,{},json.dumps(value).encode())


def run() -> dict:
    # Web: structured state is read once and primitive execution uses no model.
    web = StructuredWebSimulator(); browser = BrowserBridge(web); browser_actions = ActionRegistry(); browser.register_actions(browser_actions)
    browser_actions.get("browser.open").handler("https://example.test")
    page = browser_actions.get("browser.inspect").handler()
    form = browser_actions.get("form.fill").handler({"email":"person@example.test"})

    # Physical: mutate a safe simulated device and re-read authoritative state.
    ha_state = HomeAssistantSimulator(); ha = HomeAssistantBridge("http://127.0.0.1:8123",lambda:"simulator-token",client=ha_state)
    ha_actions = ActionRegistry(); ha.register_actions(ha_actions)
    light = ha_actions.get("light.turn_on").handler("light.study")

    # Provider: the ordinary APX Client SDK discovers and executes real provider logic.
    client = APXClient(LocalClientTransport(ProviderSession(build_reference_provider())))
    subscription = client.execute("subscription.inspect").result

    # Personalization: selection stays local and discloses no context.
    with tempfile.TemporaryDirectory() as directory:
        context = PersonalContextStore(Path(directory)/"context.json"); context.add("technology","developer technical")
        selection = context.select_variant((ContentVariant("general",("general",),"General"),ContentVariant("technical",("developer",),"Technical")))

    # Missing capability: validated, approved component becomes a normal Action.
    base = ActionRegistry(); base.register(RegisteredAction("text.lower","Lowercase text",lambda value:value.lower(),{"type":"object","required":["value"],"properties":{"value":{"type":"string"}}}))
    engine = CompositionEngine(lambda action, values: base.get(action).handler(**values))
    component = ActionComponent("text.normalize","1.0",(CompositionStep("text.lower",bind={"value":"text"}),),tests_passed=True,approved=True)
    components = ComponentRegistry(); components.register(component,base,engine,input_schema={"type":"object","required":["text"],"properties":{"text":{"type":"string"}}})
    normalized = base.get("text.normalize").handler(text="HELLO APX")

    return {
        "computer": {"command":"apx run host.status --input '{\"host\":\"vps\"}'","note":"run against an explicitly configured SSH Node"},
        "web": {"page":page,"form":form,"state_reads":web.state_reads,"metrics":asdict(browser.metrics)},
        "physical": light,
        "provider": subscription,
        "personalization": {"variant":selection["variant"].id,"disclosed":selection["disclosed"]},
        "missing_capability": normalized,
    }


if __name__ == "__main__": print(json.dumps(run(),indent=2,default=str))
