from __future__ import annotations

import subprocess
import shlex
from dataclasses import dataclass

from .models import Host


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


class LocalTransport(Transport):
    def run(self, argv: list[str], *, timeout: int = 30, input_text: str | None = None) -> CommandResult:
        try:
            result = subprocess.run(argv, input=input_text, text=True, capture_output=True, timeout=timeout)
        except FileNotFoundError as error: raise TransportError(f"{argv[0]} is not installed") from error
        except subprocess.TimeoutExpired as error: raise TransportError(f"command timed out after {timeout}s") from error
        return CommandResult(tuple(argv), result.returncode, result.stdout, result.stderr)


class SSHTransport(Transport):
    def run(self, argv: list[str], *, timeout: int = 30, input_text: str | None = None) -> CommandResult:
        command = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ConnectionAttempts=1", self.host.target or "", "--", shlex.join(argv)]
        try:
            result = subprocess.run(command, input=input_text, text=True, capture_output=True, timeout=timeout)
        except FileNotFoundError as error: raise TransportError("ssh is not installed on this host") from error
        except subprocess.TimeoutExpired as error: raise TransportError(f"SSH command timed out after {timeout}s") from error
        return CommandResult(tuple(command), result.returncode, result.stdout, result.stderr)


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
        candidate=Host(host.name,adapter,value.get("target"),(),host.groups,host.tags)
        if adapter=="local": transports.append(LocalTransport(candidate))
        elif adapter in {"ssh","tailscale_ssh"}: transports.append(SSHTransport(candidate))
    return transports


def transport_for(host: Host) -> Transport:
    candidates=transports_for(host)
    if not candidates: raise TransportError(f"host {host.name!r} has no supported connections")
    return candidates[0] if len(candidates)==1 else FallbackTransport(host,candidates)
