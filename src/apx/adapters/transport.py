# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

from .base import AdapterMetadata
from ..models import Host
from ..transports import LocalTransport, SSHTransport


class LocalAdapter(LocalTransport):
    metadata=AdapterMetadata("local","0.1","Execute argv on the local host.",( "local",))
    def __init__(self, host: Host | None = None): super().__init__(host or Host("local","local"))
    def health(self): return {"ok":True,"adapter":"local"}


class SSHAdapter(SSHTransport):
    metadata=AdapterMetadata("ssh","0.1","Execute quoted argv using an existing SSH target.",( "ssh",),("ssh",))
    def health(self):
        result=self.run(["true"],timeout=10)
        return {"ok":result.ok,"adapter":"ssh","target":self.host.target,"error":result.stderr.strip() or None}
