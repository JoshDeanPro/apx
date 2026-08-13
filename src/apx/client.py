# SPDX-License-Identifier: MPL-2.0
"""Small, provider-independent APX 0.1 client SDK."""
from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import quote

from .axp import ActionReceipt, ActionRequest, ActionResult, PreparedAction
from .http import HTTPClient
from .providers import DISCOVERY_PATH, ProviderManifest
from .runtime import ProviderSession


class ClientTransport(Protocol):
    def discover(self) -> ProviderManifest: ...
    def prepare(self, request: ActionRequest) -> PreparedAction | ActionResult: ...
    def authorize(self, prepared_action_id: str, confirmation: dict[str, Any]) -> ActionResult: ...
    def execute(self, request: ActionRequest) -> ActionResult: ...
    def status(self, request_id: str) -> ActionResult | None: ...
    def receipt(self, receipt_id: str) -> ActionReceipt | None: ...
    def cancel(self, prepared_action_id: str) -> ActionResult: ...
    def reverse(self, receipt_id: str, request: ActionRequest) -> ActionResult: ...


class LocalClientTransport:
    def __init__(self, session: ProviderSession): self.session = session
    def discover(self): return self.session.provider.manifest()
    def prepare(self, request): return self.session.prepare(request)
    def authorize(self, prepared_action_id, confirmation): return self.session.authorize(prepared_action_id, confirmation)
    def execute(self, request): return self.session.execute(request)
    def status(self, request_id): return self.session.status(request_id)
    def receipt(self, receipt_id): return self.session.receipt(receipt_id)
    def cancel(self, prepared_action_id): return self.session.cancel(prepared_action_id)
    def reverse(self, receipt_id, request): return self.session.reverse(receipt_id, request)


def _result(value: dict[str, Any]) -> ActionResult:
    return ActionResult.from_dict(value)


class HTTPClientTransport:
    """HTTPS mapping for the same client contract; localhost HTTP is test-only."""
    def __init__(self, origin: str, *, http: HTTPClient | None = None):
        self.origin = origin.rstrip("/")
        self.http = http or HTTPClient()

    def _get(self, path: str) -> dict[str, Any]:
        return self.http.request("GET", self.origin + path, headers={"Accept": "application/apx+json"},
                                 allow_http_localhost=True).json()

    def _post(self, path: str, value: dict[str, Any]) -> dict[str, Any]:
        return self.http.request("POST", self.origin + path, json=value,
                                 headers={"Accept": "application/apx+json", "Content-Type": "application/apx+json"},
                                 allow_http_localhost=True).json()

    def discover(self): return ProviderManifest.from_dict(self._get(DISCOVERY_PATH))
    def prepare(self, request):
        value = self._post("/apx/v0.1/prepare", request.to_dict())
        if value.get("type") == "action.result": return _result(value)
        raw={k:v for k,v in value.items() if k not in {"apx","axp","type"}}
        for key in ("side_effects","provider_conditions","preconditions"):
            if key in raw: raw[key]=tuple(raw[key])
        return PreparedAction(**raw)
    def authorize(self, prepared_action_id, confirmation):
        return _result(self._post("/apx/v0.1/authorize", {"prepared_action_id": prepared_action_id, "confirmation": confirmation}))
    def execute(self, request): return _result(self._post("/apx/v0.1/execute", request.to_dict()))
    def status(self, request_id):
        value = self._get("/apx/v0.1/status/" + quote(request_id, safe=""))
        return None if value.get("error") else _result(value)
    def receipt(self, receipt_id):
        value = self._get("/apx/v0.1/receipts/" + quote(receipt_id, safe=""))
        if value.get("error"): return None
        raw = {k: v for k, v in value.items() if k not in {"apx", "axp", "type"}}
        for key in ("side_effects", "postconditions", "partial_effects"):
            if key in raw: raw[key] = tuple(raw[key])
        return ActionReceipt(**raw)
    def cancel(self, prepared_action_id): return _result(self._post("/apx/v0.1/cancel", {"prepared_action_id": prepared_action_id}))
    def reverse(self, receipt_id, request): return _result(self._post("/apx/v0.1/reverse/" + quote(receipt_id, safe=""), request.to_dict()))


class APXClient:
    """One lifecycle API for local, HTTP, SSH-node, or future transports."""
    def __init__(self, transport: ClientTransport): self.transport = transport
    def discover(self): return self.transport.discover()
    def actions(self): return self.discover().actions
    def prepare(self, action: str, *, target=None, input=None, **envelope):
        return self.transport.prepare(ActionRequest(action, target or {}, input or {}, **envelope))
    def authorize(self, prepared_action_id: str, confirmation: dict[str, Any]):
        confirmation = {**confirmation, "prepared_action_id": prepared_action_id}
        return self.transport.authorize(prepared_action_id, confirmation)
    def execute(self, action: str, *, target=None, input=None, **envelope):
        return self.transport.execute(ActionRequest(action, target or {}, input or {}, **envelope))
    def status(self, request_id: str): return self.transport.status(request_id)
    def receipt(self, receipt_id: str): return self.transport.receipt(receipt_id)
    def cancel(self, prepared_action_id: str): return self.transport.cancel(prepared_action_id)
    def reverse(self, receipt_id: str, action: str, *, target=None, input=None, **envelope):
        return self.transport.reverse(receipt_id, ActionRequest(action, target or {}, input or {}, **envelope))
