# SPDX-License-Identifier: MPL-2.0
"""Deterministic structured-browser Bridge; Playwright is a lazy optional extra.

Design patterns were informed by Browser Use's MIT-licensed persistent CLI/state
model and Playwright's semantic locator model. No Browser Use code is vendored.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Protocol
from urllib.parse import urlparse

from ..actions import ActionRegistry, RegisteredAction
from ..axp import Capability, Resource
from ..health import ComponentHealth


class BrowserDriver(Protocol):
    def open(self,url: str) -> dict[str,Any]: ...
    def structured_state(self) -> dict[str,Any]: ...
    def click(self,reference: str) -> dict[str,Any]: ...
    def fill(self,fields: dict[str,str]) -> dict[str,Any]: ...
    def close(self) -> None: ...


class PlaywrightDriver:
    """Optional adapter. Install `playwright`; APX Core never imports it eagerly."""
    def __init__(self,*,headless: bool=True):
        try: from playwright.sync_api import sync_playwright
        except ImportError as error: raise RuntimeError("browser bridge requires optional 'playwright'; APX Core remains usable without it") from error
        self._runtime=sync_playwright().start(); self._browser=self._runtime.chromium.launch(headless=headless); self._page=self._browser.new_page()
    def open(self,url): self._page.goto(url,wait_until="domcontentloaded"); return {"url":self._page.url,"title":self._page.title()}
    def structured_state(self):
        elements=self._page.locator("a,button,input,select,textarea,[role]")
        values=[]
        for index in range(min(elements.count(),1000)):
            item=elements.nth(index); values.append({"ref":f"e{index}","role":item.get_attribute("role") or item.evaluate("e=>e.tagName.toLowerCase()"),"name":item.get_attribute("aria-label") or item.get_attribute("name") or item.inner_text()[:200],"type":item.get_attribute("type")})
        return {"url":self._page.url,"title":self._page.title(),"elements":values,"source":"dom_accessibility"}
    def _ref(self,value):
        if not value.startswith("e") or not value[1:].isdigit(): raise ValueError("invalid element reference")
        return self._page.locator("a,button,input,select,textarea,[role]").nth(int(value[1:]))
    def click(self,reference): self._ref(reference).click(); return {"clicked":reference,"url":self._page.url}
    def fill(self,fields):
        for name,value in fields.items(): self._page.get_by_label(name,exact=True).or_(self._page.locator(f'[name="{name}"]')).first.fill(value)
        return {"filled":sorted(fields),"url":self._page.url}
    def close(self): self._browser.close(); self._runtime.stop()


class LazyPlaywrightDriver:
    """Defers actually launching a browser process until the first real call.

    `BrowserBridge(PlaywrightDriver(...))` used to launch Chromium the moment a
    Node/APX config declared the browser bridge -- meaning every `apx` command,
    including ones with nothing to do with a browser, paid for a real Chromium
    startup (multiple seconds) just from constructing the config. This wrapper
    satisfies the same `BrowserDriver` protocol but only pays that cost the
    first time `browser.open`/`.inspect`/`.click`/`form.fill` is actually used."""
    def __init__(self, *, headless: bool = True):
        self._headless = headless; self._driver: PlaywrightDriver | None = None
    def _ensure(self) -> PlaywrightDriver:
        if self._driver is None: self._driver = PlaywrightDriver(headless=self._headless)
        return self._driver
    def open(self, url): return self._ensure().open(url)
    def structured_state(self): return self._ensure().structured_state()
    def click(self, reference): return self._ensure().click(reference)
    def fill(self, fields): return self._ensure().fill(fields)
    def close(self) -> None:
        if self._driver is not None: self._driver.close(); self._driver = None


@dataclass
class BrowserMetrics:
    tool_calls: int=0; reasoning_calls: int=0; retries: int=0; cache_hits: int=0
    successes: int=0; failures: int=0; duration_ms: float=0; fallback_level: str="browser"
    @property
    def success_rate(self):
        total=self.successes+self.failures; return self.successes/total if total else None


class BrowserBridge:
    id="browser"; version="0.1.0"; provenance="browser_fallback"
    def __init__(self,driver: BrowserDriver): self.driver=driver; self._state=None; self._origin=None; self.metrics=BrowserMetrics()
    def discover_resources(self): return (Resource("browser:local","browser","Local Browser",capabilities=("browser.navigation","browser.forms")),)
    def discover_capabilities(self): return (
        Capability("browser.navigation","browser:local","Structured browser navigation",actions=("browser.open","browser.inspect","browser.click"),provenance=self.provenance,reliability=.75,source=self.id),
        Capability("browser.forms","browser:local","Semantic form filling",actions=("form.fill",),provenance=self.provenance,reliability=.75,source=self.id),)
    def _timed(self,fn,*args):
        started=time.monotonic(); self.metrics.tool_calls+=1
        try:
            value=fn(*args); self.metrics.successes+=1; return value
        except Exception:
            self.metrics.failures+=1; raise
        finally: self.metrics.duration_ms+=round((time.monotonic()-started)*1000,3)
    def open(self,url):
        parsed=urlparse(url)
        if parsed.scheme not in {"https","http"} or not parsed.hostname: raise ValueError("browser.open requires an HTTP(S) URL")
        result=self._timed(self.driver.open,url); self._origin=f"{parsed.scheme}://{parsed.netloc}"; self._state=None; return result
    def inspect(self,refresh=False):
        if self._state is not None and not refresh: self.metrics.cache_hits+=1; return {**self._state,"cached":True}
        self._state=self._timed(self.driver.structured_state); return {**self._state,"cached":False}
    def click(self,reference): self._state=None; return self._timed(self.driver.click,reference)
    def fill(self,fields): self._state=None; return self._timed(self.driver.fill,fields)
    def register_actions(self,registry: ActionRegistry):
        obj=lambda properties,required=():{"type":"object","properties":properties,"required":list(required),"additionalProperties":False}; string={"type":"string"}
        registry.register(RegisteredAction("browser.open","Open an HTTP(S) page",self.open,obj({"url":string},("url",)),False,False,risk="low_change",provider=self.id,provenance=self.provenance))
        registry.register(RegisteredAction("browser.inspect","Read cached semantic DOM/accessibility state",self.inspect,obj({"refresh":{"type":"boolean"}}),True,False,provider=self.id,provenance=self.provenance))
        registry.register(RegisteredAction("browser.click","Click a stable element reference",self.click,obj({"reference":string},("reference",)),False,False,risk="low_change",provider=self.id,provenance=self.provenance))
        registry.register(RegisteredAction("form.fill","Fill fields by accessible label/name",self.fill,obj({"fields":{"type":"object","additionalProperties":{"type":"string"}}},("fields",)),False,False,risk="low_change",provider=self.id,provenance=self.provenance))
    def health(self): return ComponentHealth(self.id,"healthy",capabilities=("browser.navigation","browser.forms"),metadata={"provenance":self.provenance,"metrics":{**self.metrics.__dict__,"success_rate":self.metrics.success_rate}})
