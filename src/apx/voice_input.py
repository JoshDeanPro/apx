"""Local-first APX input pipeline. No model, audio, or hotkey dependency in Core."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class IntentInput:
    kind: str
    text: str
    mode: str = "action"
    source: str = "local"
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str,Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IntentRoute:
    status: str
    action: str|None = None
    parameters: dict[str,Any] = field(default_factory=dict)
    target: str|None = None
    confidence: float = 0
    confirmation: str = "none"
    reason: str|None = None
    def to_dict(self): return asdict(self)


@dataclass(frozen=True)
class PressGesture:
    key: str
    duration_ms: float
    hold_threshold_ms: float=350
    @property
    def mode(self): return "action" if self.duration_ms>=self.hold_threshold_ms else "chat"


class InputProvider(Protocol):
    id: str
    def receive(self) -> IntentInput: ...
    def health(self) -> dict[str,Any]: ...


class TextInputProvider:
    id="text"
    def __init__(self,text: str,*,mode="action",kind="text"): self.text=text; self.mode=mode; self.kind=kind
    def receive(self): return IntentInput(self.kind,self.text,self.mode)
    def health(self): return {"component":"input:text","status":"healthy"}


class WhisperCppTranscriber:
    """Adapter for the optional official whisper.cpp CLI; models are user-selected."""
    def __init__(self,model: str|Path,command: str|None=None):
        self.model=Path(model).expanduser(); self.command=command or shutil.which("whisper-cli") or shutil.which("main") or ""
    def health(self):
        if not self.command: return {"status":"unavailable","reason":"whisper.cpp CLI not installed"}
        if not self.model.is_file(): return {"status":"misconfigured","reason":"voice model not configured"}
        return {"status":"healthy","engine":"whisper.cpp","model":self.model.name}
    def transcribe(self,audio_path: Path) -> str:
        health=self.health()
        if health["status"]!="healthy": raise RuntimeError(health["reason"])
        result=subprocess.run([self.command,"-m",str(self.model),"-f",str(audio_path),"-nt"],capture_output=True,text=True,timeout=120,check=False)
        if result.returncode: raise RuntimeError(result.stderr.strip() or "local transcription failed")
        return " ".join(line.strip() for line in result.stdout.splitlines() if line.strip())


class VoiceInputProvider:
    id="voice"
    def __init__(self,transcriber: WhisperCppTranscriber,*,capture_command: list[str]|None=None,keep_audio=False,gesture: PressGesture|None=None):
        self.transcriber=transcriber; self.keep_audio=keep_audio; self.gesture=gesture or PressGesture("F8",1000)
        self.capture_command=capture_command or self._default_capture_command()
    @staticmethod
    def _default_capture_command():
        ffmpeg=shutil.which("ffmpeg")
        if not ffmpeg: return []
        if os.uname().sysname=="Darwin": return [ffmpeg,"-nostdin","-loglevel","error","-f","avfoundation","-i",":0","-ac","1","-ar","16000"]
        return [ffmpeg,"-nostdin","-loglevel","error","-f","alsa","-i","default","-ac","1","-ar","16000"]
    def health(self):
        transcript=self.transcriber.health(); capture="healthy" if self.capture_command else "unavailable"
        status="healthy" if capture==transcript["status"]=="healthy" else "available_to_configure"
        return {"component":"input:voice","status":status,"capture":capture,"transcription":transcript,"raw_audio_retained":self.keep_audio}
    def receive(self) -> IntentInput:
        if not self.capture_command: raise RuntimeError("no local microphone capture command available")
        descriptor,name=tempfile.mkstemp(prefix="openpower-voice-",suffix=".wav"); os.close(descriptor); audio=Path(name)
        started=time.monotonic(); process=subprocess.Popen([*self.capture_command,str(audio)])
        try:
            input("Recording locally. Press Enter to stop… ")
            process.terminate(); process.wait(timeout=5)
            transcription_started=time.monotonic(); text=self.transcriber.transcribe(audio)
            return IntentInput("voice",text,self.gesture.mode,metadata={"key":self.gesture.key,"gesture_ms":self.gesture.duration_ms,"capture_ms":round((transcription_started-started)*1000,2),"transcription_ms":round((time.monotonic()-transcription_started)*1000,2),"audio_retained":self.keep_audio})
        finally:
            if process.poll() is None: process.kill()
            if not self.keep_audio: audio.unlink(missing_ok=True)


class FastIntentRouter:
    """Deterministic high-confidence routes. Ambiguity is returned to chat/reasoning."""
    patterns=(
        (re.compile(r"^(?:check|show|get)(?: the)? (?P<service>[a-zA-Z0-9_.@:-]+)(?: status)? on (?:the )?(?P<target>[a-zA-Z0-9_.-]+)$",re.I),"service.status","none"),
        (re.compile(r"^restart(?: the)? (?P<service>[a-zA-Z0-9_.@:-]+) on (?:the )?(?P<target>[a-zA-Z0-9_.-]+)$",re.I),"service.restart","confirm"),
        (re.compile(r"^(?:check|show|get)(?: the)? status of (?:the )?(?P<target>[a-zA-Z0-9_.-]+)$",re.I),"host.status","none"),
    )
    HIGH_RISK=re.compile(r"\b(send|pay|buy|purchase|transfer)\b.*?(?P<amount>\$?\d+(?:\.\d{1,2})?)",re.I)
    def route(self,value: IntentInput) -> IntentRoute:
        if value.mode=="chat": return IntentRoute("conversation_required",reason="tap/chat mode")
        text=" ".join(value.text.strip().rstrip(".?!").split())
        high=self.HIGH_RISK.search(text)
        if high: return IntentRoute("prepare_required","payment.send",{"utterance":text},confidence=.9,confirmation="transaction",reason="financial intent never executes from voice alone")
        for pattern,action,confirmation in self.patterns:
            match=pattern.match(text)
            if match:
                values={key:value.lower() if isinstance(value,str) else value for key,value in match.groupdict().items()}; target=values.pop("target",None)
                return IntentRoute("resolved",action,values,target,.98,confirmation)
        return IntentRoute("reasoning_required",confidence=0,reason="no deterministic Action mapping")


def route_input(provider: InputProvider,router: FastIntentRouter|None=None) -> dict[str,Any]:
    started=time.monotonic(); value=provider.receive(); routed_at=time.monotonic(); route=(router or FastIntentRouter()).route(value)
    return {"input":{"kind":value.kind,"mode":value.mode,"text":value.text,"metadata":value.metadata},"route":route.to_dict(),"metrics":{"routing_ms":round((time.monotonic()-routed_at)*1000,3),"total_ms":round((time.monotonic()-started)*1000,3),"reasoning_calls":0 if route.status in {"resolved","prepare_required"} else 1}}


def voice_health(model: str|None=None) -> dict[str,Any]:
    return VoiceInputProvider(WhisperCppTranscriber(model or "")).health()
