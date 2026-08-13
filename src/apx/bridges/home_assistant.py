# SPDX-License-Identifier: MPL-2.0
"""Home Assistant REST Bridge: one proven ecosystem, no device drivers in APX."""
from __future__ import annotations

from typing import Any, Callable
from urllib.parse import quote, urlparse

from ..actions import ActionError, ActionRegistry, RegisteredAction
from ..axp import Capability, Resource
from ..health import ComponentHealth
from ..http import HTTPClient


DOMAIN_ACTIONS={
    "light":(("light.turn_on","turn_on","low_change","confirm"),("light.turn_off","turn_off","low_change","none"),("light.set_brightness","turn_on","low_change","confirm")),
    "lock":(("door.lock","lock","account_change","confirm"),("door.unlock","unlock","security_critical","security_critical")),
    "cover":(("garage.open","open_cover","security_critical","security_critical"),("garage.close","close_cover","account_change","confirm")),
    "climate":(("thermostat.set_temperature","set_temperature","account_change","confirm"),),
    "media_player":(("media.play","media_play","low_change","confirm"),),
    "vacuum":(("vacuum.start","start","low_change","confirm"),),
}


class HomeAssistantBridge:
    id="home_assistant"; version="0.1.0"; provenance="standard_bridge"
    def __init__(self,base_url: str,credential: Callable[[],str],*,client: HTTPClient|None=None):
        parsed=urlparse(base_url)
        if parsed.scheme!="https" and parsed.hostname not in {"localhost","127.0.0.1","::1"}: raise ValueError("Home Assistant requires HTTPS except on loopback")
        self.base_url=base_url.rstrip("/"); self.credential=credential; self.client=client or HTTPClient(); self._states: list[dict[str,Any]]|None=None
    def _request(self,method,path,body=None):
        return self.client.request(method,self.base_url+path,headers={"Authorization":"Bearer "+self.credential()},json=body,
            allow_http_localhost=True,idempotent=method=="GET").json()
    def states(self,refresh=False):
        if self._states is None or refresh: self._states=self._request("GET","/api/states")
        return self._states
    def discover_resources(self):
        values=[]
        for state in self.states():
            entity=state["entity_id"]; domain=entity.split(".",1)[0]
            values.append(Resource(f"home_assistant:{entity}",domain,state.get("attributes",{}).get("friendly_name",entity),
                {"entity_id":entity,"state":state.get("state")},tags=("physical",)))
        return tuple(values)
    def discover_capabilities(self):
        values=[]
        for resource in self.discover_resources():
            actions=tuple(item[0] for item in DOMAIN_ACTIONS.get(resource.kind,())) or ("sensor.inspect",)
            values.append(Capability(f"device.{resource.kind}",resource.id,f"Home Assistant {resource.kind}",actions=actions,
                provenance=self.provenance,reliability=.9,source=self.id))
        return tuple(values)
    def inspect(self,entity_id): return self._request("GET","/api/states/"+quote(entity_id,safe="."))
    def call(self,domain,service,entity_id,**data):
        before=self.inspect(entity_id); self._request("POST",f"/api/services/{quote(domain)}/{quote(service)}",{"entity_id":entity_id,**data}); self._states=None
        after=self.inspect(entity_id)
        expected={"turn_on":"on","turn_off":"off","lock":"locked","unlock":"unlocked","open_cover":"open","close_cover":"closed","media_play":"playing","start":"cleaning"}.get(service)
        if service=="set_temperature": verified=after.get("attributes",{}).get("temperature")==data.get("temperature")
        elif expected is not None: verified=after.get("state")==expected
        else: verified=before!=after
        if not verified: raise ActionError("Home Assistant postcondition was not verified")
        return {"entity_id":entity_id,"before":before.get("state"),"after":after.get("state"),"verified":verified}
    def register_actions(self,registry: ActionRegistry):
        schema={"type":"object","properties":{"entity_id":{"type":"string"},"brightness":{"type":"integer","minimum":0,"maximum":255},"temperature":{"type":"number"}},"required":["entity_id"],"additionalProperties":False}
        registered=set()
        for domain,items in DOMAIN_ACTIONS.items():
            for action_id,service,risk,confirmation in items:
                if action_id in registered: continue
                def invoke(entity_id,brightness=None,temperature=None,_domain=domain,_service=service):
                    data={key:value for key,value in {"brightness":brightness,"temperature":temperature}.items() if value is not None}
                    return self.call(_domain,_service,entity_id,**data)
                registry.register(RegisteredAction(action_id,f"Home Assistant {service.replace('_',' ')}",invoke,schema,False,risk=="security_critical",
                    output_schema={"type":"object"},risk=risk,confirmation=confirmation,idempotent=True,provider=self.id,provenance=self.provenance,expected_verification="entity state changed"))
                registered.add(action_id)
        registry.register(RegisteredAction("sensor.inspect","Inspect Home Assistant authoritative entity state",self.inspect,
            {"type":"object","properties":{"entity_id":{"type":"string"}},"required":["entity_id"],"additionalProperties":False},True,False,provider=self.id,provenance=self.provenance))
    def health(self):
        try: count=len(self.states()); return ComponentHealth(self.id,"healthy",capabilities=("physical.devices",),metadata={"entities":count,"provenance":self.provenance})
        except Exception as error: return ComponentHealth(self.id,"authentication_required" if "401" in str(error) else "unavailable",str(error),capabilities=("physical.devices",))
