# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .base import AdapterMetadata
from ..credentials import CredentialRegistry
from ..http import HTTPClient, HTTPFailure, MAX_RESPONSE_BYTES

@dataclass(frozen=True)
class HTTPResponse:
    status: int
    headers: dict[str,str]
    body: Any
    truncated: bool = False

    def to_dict(self): return {"status":self.status,"headers":self.headers,"body":self.body,"truncated":self.truncated}


class HTTPAdapter:
    metadata=AdapterMetadata("http","0.1","Bounded HTTP/API requests with lazy credential injection.",( "http","api"))

    def __init__(self, credentials: CredentialRegistry, *, opener=None, client: HTTPClient|None=None):
        self.credentials=credentials; self.opener=opener; self.client=client or HTTPClient(max_response_bytes=MAX_RESPONSE_BYTES)

    def request(self, method: str, url: str, *, headers: dict[str,str] | None = None, query: dict[str,Any] | None = None, body: Any = None, credential: str | None = None, credential_header: str = "Authorization", credential_prefix: str = "Bearer ", timeout: int = 30, allow_http_localhost: bool = False, max_response_bytes: int = MAX_RESPONSE_BYTES) -> HTTPResponse:
        method=method.upper()
        if method not in {"GET","POST","PUT","PATCH","DELETE","HEAD"}: raise ValueError(f"unsupported HTTP method {method}")
        parsed=urllib.parse.urlparse(url)
        if parsed.username or parsed.password: raise ValueError("credentials must not be embedded in URLs")
        local=parsed.hostname in {"127.0.0.1","localhost","::1"}
        if parsed.scheme!="https" and not (allow_http_localhost and parsed.scheme=="http" and local): raise ValueError("remote HTTP connections require HTTPS")
        if query:
            encoded=urllib.parse.urlencode(query,doseq=True); url += ("&" if parsed.query else "?")+encoded
        safe_headers={"Accept":"application/json",**(headers or {})}
        if credential: safe_headers[credential_header]=credential_prefix+self.credentials.resolve(credential)
        payload=None
        if body is not None:
            payload=json.dumps(body).encode(); safe_headers.setdefault("Content-Type","application/json")
        if self.opener is None:
            try:
                response=self.client.request(method,url,headers=safe_headers,json=body,timeout=timeout,
                    idempotent=method in {"GET","HEAD"},allow_http_localhost=allow_http_localhost)
                try: decoded=response.json()
                except (ValueError,UnicodeDecodeError): decoded=response.content.decode("utf-8","replace")
                return HTTPResponse(response.status,response.headers,self.credentials.redact(decoded),False)
            except HTTPFailure as error: raise RuntimeError(str(error)) from None
        request=urllib.request.Request(url,data=payload,headers=safe_headers,method=method)
        try:
            response=self.opener(request,timeout=max(1,min(timeout,120)))
            raw=response.read(max_response_bytes+1); truncated=len(raw)>max_response_bytes; raw=raw[:max_response_bytes]
            try: decoded=json.loads(raw) if raw else None
            except (json.JSONDecodeError,UnicodeDecodeError): decoded=raw.decode("utf-8","replace")
            returned_headers={key:value for key,value in response.headers.items() if key.lower() not in {"set-cookie","authorization"}}
            return HTTPResponse(response.status,returned_headers,self.credentials.redact(decoded),truncated)
        except urllib.error.HTTPError as error:
            error.read(max_response_bytes)
            raise RuntimeError(f"HTTP request failed with status {error.code}") from None
        except urllib.error.URLError:
            raise RuntimeError("HTTP request failed") from None

    def health(self): return {"ok":True,"status":"healthy","adapter":"http",**self.client.health()}
