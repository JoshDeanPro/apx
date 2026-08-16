# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import shlex
from dataclasses import dataclass

from .models import Host
from .process import ProcessError, ProcessTimeout, run
from .health import ComponentHealth


class TransportError(RuntimeError): pass


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool: return self.exit_code == 0


class Transport:
    def __init__(self, host: Host): self.host = host
    def run(self, argv: list[str], *, timeout: int = 30, input_text: str | None = None) -> CommandResult: raise NotImplementedError
    def health(self)->ComponentHealth:
        try:
            result=self.run(["true"],timeout=10)
            return ComponentHealth(f"transport:{self.host.name}","healthy" if result.ok else "degraded",metadata={"exit_code":result.exit_code})
        except TransportError as error: return ComponentHealth(f"transport:{self.host.name}","unavailable",str(error))


class LocalTransport(Transport):
    def run(self, argv: list[str], *, timeout: int = 30, input_text: str | None = None) -> CommandResult:
        try:
            result = run(argv,input_text=input_text,timeout=timeout)
        except (ProcessError,ProcessTimeout) as error: raise TransportError(str(error)) from error
        return CommandResult(tuple(argv), result.exit_code, result.stdout, result.stderr)


class SSHTransport(Transport):
    def run(self, argv: list[str], *, timeout: int = 30, input_text: str | None = None) -> CommandResult:
        target = self.host.target or ""
        if not target or target.startswith("-"):
            raise TransportError(f"invalid SSH host target {target!r}")
        command = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ConnectionAttempts=1", target, "--", shlex.join(argv)]
        try:
            result = run(command,input_text=input_text,timeout=timeout)
        except (ProcessError,ProcessTimeout) as error: raise TransportError(str(error)) from error
        return CommandResult(tuple(command), result.exit_code, result.stdout, result.stderr)



class FallbackTransport(Transport):
    def __init__(self, host: Host, candidates: list[Transport]):
        super().__init__(host); self.candidates=candidates

    def run(self, argv: list[str], *, timeout: int = 30, input_text: str | None = None) -> CommandResult:
        errors=[]
        for transport in self.candidates:
            try:
                result=transport.run(argv,timeout=timeout,input_text=input_text)
                if result.ok or result.exit_code not in {255}: return result
                errors.append(result.stderr.strip())
            except TransportError as error: errors.append(str(error))
        raise TransportError("all configured connections failed" + (f": {'; '.join(filter(None,errors))}" if errors else ""))


def transports_for(host: Host) -> list[Transport]:
    definitions=list(host.connections) or [{"adapter":host.transport,"target":host.target}]
    transports=[]
    for value in definitions:
        adapter=value.get("adapter",value.get("transport","ssh"))
        candidate=Host(host.name,adapter,value.get("target"),(),host.groups,host.tags,host.roles,host.is_self)
        # A `local` connection is only a connection on the machine it describes. On
        # any other node it is someone else's entry in a shared topology, and
        # running it here would answer questions about the wrong computer.
        if adapter=="local":
            if host.is_self: transports.append(LocalTransport(candidate))
        elif adapter in {"ssh","tailscale_ssh"}: transports.append(SSHTransport(candidate))
    return transports


def transport_for(host: Host) -> Transport:
    candidates=transports_for(host)
    if not candidates:
        if host.transport=="local" and not host.is_self:
            raise TransportError(f"host {host.name!r} is declared local on another machine and has no connection reachable from here")
        raise TransportError(f"host {host.name!r} has no supported connections")
    return candidates[0] if len(candidates)==1 else FallbackTransport(host,candidates)
