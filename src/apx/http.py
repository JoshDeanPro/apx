# SPDX-License-Identifier: MIT
"""Shared bounded HTTPS client with safe, idempotency-aware retries."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any,Mapping

import httpx

DEFAULT_TIMEOUT=30.0
MAX_RESPONSE_BYTES=1024*1024
USER_AGENT="OpenPower/0.3.0 APX/0.8.0 (+https://openpower.dev)"


class HTTPFailure(RuntimeError):
    def __init__(self,message: str,*,code: str="connection_failure",status: int|None=None):
        super().__init__(message); self.code=code; self.status=status


@dataclass(frozen=True)
class HTTPResult:
    status: int
    headers: dict[str,str]
    content: bytes
    def json(self)->Any:
        import json
        return json.loads(self.content) if self.content else None


class HTTPClient:
    def __init__(self, *, timeout: float=DEFAULT_TIMEOUT, max_response_bytes: int=MAX_RESPONSE_BYTES,
                 transport: httpx.BaseTransport|None=None):
        self.timeout=timeout; self.max_response_bytes=max_response_bytes
        self._client=httpx.Client(timeout=httpx.Timeout(timeout),follow_redirects=False,verify=True,trust_env=False,
            headers={"User-Agent":USER_AGENT,"Accept":"application/json"},transport=transport)

    def close(self)->None: self._client.close()

    def request(self, method: str, url: str, *, headers: Mapping[str,str]|None=None, params: Mapping[str,Any]|None=None,
                json: Any=None, content: bytes|None=None, timeout: float|None=None, idempotent: bool|None=None,
                retries: int=1, allow_http_localhost: bool=False, follow_redirects: bool=False, raise_for_status: bool=True) -> HTTPResult:
        parsed=httpx.URL(url); local=parsed.host in {"localhost","127.0.0.1","::1"}
        if parsed.scheme!="https" and not (allow_http_localhost and parsed.scheme=="http" and local): raise HTTPFailure("remote HTTP requires verified HTTPS",code="tls_required")
        if parsed.username or parsed.password: raise HTTPFailure("credentials must not be embedded in URLs",code="invalid_url")
        method=method.upper(); safe=idempotent if idempotent is not None else method in {"GET","HEAD","OPTIONS"}
        attempts=1+(max(0,min(retries,3)) if safe else 0)
        for attempt in range(attempts):
            try:
                with self._client.stream(method,url,headers=headers,params=params,json=json,content=content,timeout=timeout or self.timeout,follow_redirects=follow_redirects) as response:
                    collected=bytearray()
                    for chunk in response.iter_bytes():
                        if len(collected)+len(chunk)>self.max_response_bytes: raise HTTPFailure("HTTP response exceeded configured limit",code="response_too_large",status=response.status_code)
                        collected.extend(chunk)
                    body=bytes(collected)
                    clean={k:v for k,v in response.headers.items() if k.lower() not in {"set-cookie","authorization"}}
                    if raise_for_status and response.status_code>=400: raise HTTPFailure(f"HTTP request failed with status {response.status_code}",code="http_error",status=response.status_code)
                    return HTTPResult(response.status_code,clean,body)
            except (httpx.TimeoutException,httpx.NetworkError) as error:
                if attempt+1>=attempts: raise HTTPFailure(str(error) or "HTTP connection failed",code="timeout" if isinstance(error,httpx.TimeoutException) else "connection_failure") from error
                time.sleep(0.1*(2**attempt))
        raise AssertionError("unreachable")

    def health(self)->dict[str,Any]: return {"status":"healthy","https_required":True,"tls_verification":True,"timeout_seconds":self.timeout,"max_response_bytes":self.max_response_bytes}
