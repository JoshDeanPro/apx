# SPDX-License-Identifier: MPL-2.0
"""Universal capability graph, bridges, selection and deterministic composition."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
import time
from typing import Any, Callable, Iterable, Protocol

from .actions import ActionRegistry, RegisteredAction
from .axp import Capability, PROVENANCE_KINDS, Resource
from .health import ComponentHealth


PROVENANCE_PRIORITY={
    "native_apx":100,"native_provider":100,"official_api":90,"official_sdk":90,
    "standard_bridge":80,"local_native":75,"official_plugin":75,"community_plugin":60,
    "local_component":60,"generated_component":50,"browser_component":40,
    "browser_fallback":30,"computer_fallback":10,
}


@dataclass(frozen=True)
class ActionPath:
    action: str
    resource: str
    capability: str
    provider: str | None
    provenance: str
    reliability: float
    health: str
    confirmation: str
    score: float
    metadata: dict[str,Any]=field(default_factory=dict)

    def to_dict(self): return asdict(self)


class Bridge(Protocol):
    id: str
    version: str
    provenance: str
    def discover_resources(self) -> Iterable[Resource]: ...
    def discover_capabilities(self) -> Iterable[Capability]: ...
    def register_actions(self, registry: ActionRegistry) -> None: ...
    def health(self) -> ComponentHealth: ...


class CapabilityGraph:
    """One searchable space; it owns no credentials and executes nothing itself."""
    def __init__(self):
        self.resources: dict[str,Resource]={}; self.capabilities: dict[str,Capability]={}
        self.actions: dict[str,Any]={}; self.bridges: dict[str,Bridge]={}

    def add_resource(self,value: Resource) -> None: self.resources[value.id]=value
    def add_capability(self,value: Capability) -> None:
        if value.resource not in self.resources: raise ValueError(f"unknown resource {value.resource}")
        self.capabilities[f"{value.resource}:{value.id}"]=value
    def add_action(self,definition: Any) -> None: self.actions[definition.id]=definition
    def add_bridge(self,bridge: Bridge,registry: ActionRegistry | None=None) -> None:
        if bridge.provenance not in PROVENANCE_KINDS: raise ValueError("invalid bridge provenance")
        self.bridges[bridge.id]=bridge
        for item in bridge.discover_resources(): self.add_resource(item)
        for item in bridge.discover_capabilities(): self.add_capability(item)
        if registry: bridge.register_actions(registry)

    def search(self,query: str,*,resource_kind: str | None=None) -> dict[str,list[dict[str,Any]]]:
        words={item.lower() for item in query.replace("."," ").split()}
        def relevant(*values: str) -> bool:
            text=" ".join(values).lower(); return not words or all(word in text for word in words)
        resources=[item.to_dict() for item in self.resources.values() if (not resource_kind or item.kind==resource_kind) and relevant(item.id,item.kind,item.name,*item.tags)]
        capabilities=[item.to_dict() for item in self.capabilities.values() if relevant(item.id,item.description,item.resource,*item.actions)]
        actions=[item.to_dict() for item in self.actions.values() if relevant(item.id,item.description,*item.tags)]
        return {"resources":resources,"capabilities":capabilities,"actions":actions}

    def paths(self,action: str,*,resource: str | None=None,allow_fallback: bool=False,
              confirmed_lower_trust: bool=False) -> list[ActionPath]:
        definition=self.actions.get(action)
        values=[]
        for capability in self.capabilities.values():
            if action not in capability.actions or (resource and capability.resource!=resource): continue
            fallback=capability.provenance in {"browser_component","browser_fallback","computer_fallback"}
            consequential=bool(definition and (definition.risk not in {"read","low_change"} or definition.confirmation!="none"))
            if fallback and (not allow_fallback or (consequential and not confirmed_lower_trust)): continue
            health_factor={"healthy":1,"degraded":.6,"authentication_required":.3,"update_required":.2}.get(capability.health,0)
            score=PROVENANCE_PRIORITY[capability.provenance]*capability.reliability*health_factor
            values.append(ActionPath(action,capability.resource,capability.id,getattr(definition,"provider",None),capability.provenance,capability.reliability,capability.health,getattr(definition,"confirmation","none"),score))
        return sorted(values,key=lambda item:item.score,reverse=True)

    def alternatives(self,action: str,failed_resource: str) -> list[ActionPath]:
        return [item for item in self.paths(action,allow_fallback=False) if item.resource!=failed_resource]

    def describe(self) -> dict[str,Any]:
        return {"resources":[item.to_dict() for item in self.resources.values()],"capabilities":[item.to_dict() for item in self.capabilities.values()],"actions":[item.to_dict() for item in self.actions.values()],"bridges":[{"id":key,**value.health().to_dict()} for key,value in self.bridges.items()]}


@dataclass(frozen=True)
class CompositionStep:
    action: str
    input: dict[str,Any]=field(default_factory=dict)
    bind: dict[str,str]=field(default_factory=dict)


@dataclass(frozen=True)
class ActionComponent:
    id: str
    version: str
    steps: tuple[CompositionStep,...]
    provenance: str="generated_component"
    compatible_with: str | None=None
    valid_until: str | None=None
    tests_passed: bool=False
    approved: bool=False
    risk: str="low_change"
    confirmation: str="confirm"
    permissions: tuple[str,...]=()

    def __post_init__(self):
        if self.provenance not in PROVENANCE_KINDS: raise ValueError("invalid provenance")
        if not self.tests_passed: raise ValueError("components must pass validation tests")
        if self.provenance in {"generated_component","browser_component"} and not self.approved: raise ValueError("generated/browser components require approval")


class CompositionEngine:
    """Deterministic sequencing only; no hidden planning or authority expansion."""
    def __init__(self,invoke: Callable[[str,dict[str,Any]],Any]): self.invoke=invoke
    def run(self,component: ActionComponent,inputs: dict[str,Any]) -> dict[str,Any]:
        values=dict(inputs); outputs=[]
        started=time.monotonic()
        for step in component.steps:
            arguments={**step.input,**{target:values[source] for target,source in step.bind.items()}}
            result=self.invoke(step.action,arguments); outputs.append(result); values[f"step.{len(outputs)}"]=result
        return {"component":component.id,"version":component.version,"steps":len(outputs),"results":outputs,"duration_ms":round((time.monotonic()-started)*1000,3),"reasoning_calls":0}


class ComponentRegistry:
    """Validated registration path for human- or agent-authored reusable Actions."""
    def __init__(self): self.components: dict[str,ActionComponent]={}; self.invalidated: dict[str,str]={}
    def register(self,component: ActionComponent,registry: ActionRegistry,engine: CompositionEngine,
                 *,input_schema: dict[str,Any]|None=None,description: str="Reusable Action component") -> RegisteredAction:
        if component.id in self.components: raise ValueError("component already registered")
        if component.valid_until and datetime.fromisoformat(component.valid_until.replace("Z","+00:00"))<=datetime.now(timezone.utc): raise ValueError("component has expired")
        missing=[step.action for step in component.steps if step.action not in {item.name for item in registry.list()}]
        if missing: raise ValueError("component references unavailable Actions: "+", ".join(missing))
        action=RegisteredAction(component.id,description,lambda **values:engine.run(component,values),input_schema or {"type":"object"},False,False,
            risk=component.risk,confirmation=component.confirmation,required_permissions=component.permissions,
            provider="component.registry",provenance=component.provenance,version=component.version)
        registry.register(action); self.components[component.id]=component; return action
    def invalidate(self,component_id: str,reason: str) -> None:
        if component_id not in self.components: raise KeyError(component_id)
        self.invalidated[component_id]=reason
    def available(self): return tuple(item for key,item in self.components.items() if key not in self.invalidated)


@dataclass(frozen=True)
class ComponentCandidate:
    name: str
    source_url: str
    license: str
    maintained: bool
    official: bool=False
    dependencies: tuple[str,...]=()
    security_notes: tuple[str,...]=()


def audit_component_candidate(candidate: ComponentCandidate,*,compatible_licenses=("MIT","Apache-2.0","MPL-2.0","BSD-2-Clause","BSD-3-Clause")) -> dict[str,Any]:
    problems=[]
    if not candidate.source_url.startswith("https://"): problems.append("source must use HTTPS")
    if candidate.license not in compatible_licenses: problems.append("license requires review")
    if not candidate.maintained: problems.append("project is not actively maintained")
    if len(candidate.dependencies)>20: problems.append("dependency surface requires isolation review")
    return {"candidate":asdict(candidate),"approved":not problems,"problems":problems,"workflow":["official documentation","source repository","license","maintenance","dependencies","security","bridge isolation","tests","registration"]}


def graph_from_registry(resources: Iterable[Resource],capabilities: Iterable[Capability],registry: ActionRegistry) -> CapabilityGraph:
    graph=CapabilityGraph()
    for item in resources: graph.add_resource(item)
    for action in registry.list(): graph.add_action(action.definition())
    for item in capabilities: graph.add_capability(item)
    return graph
