from __future__ import annotations

import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Any

HOME = Path.home()

CONFIG_DIR = HOME / ".config" / "apx"
STATE_DIR = HOME / ".local" / "state" / "apx" / "voice"
SHARE_DIR = HOME / ".local" / "share" / "apx"
VOICE_DIR = SHARE_DIR / "voice"
MODELS_DIR = VOICE_DIR / "models"

CONFIG_FILE = CONFIG_DIR / "voice.json"
PID_FILE = STATE_DIR / "daemon.pid"
LAST_FILE = STATE_DIR / "last.json"

CORE_APX = HOME / ".local" / "share" / "apx" / "runtime" / "bin" / "apx"

KWS_NAME = "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"
KWS_DIR = MODELS_DIR / KWS_NAME

ASR_NAME = "sherpa-onnx-moonshine-tiny-en-int8"
ASR_DIR = MODELS_DIR / ASR_NAME

VAD_MODEL = MODELS_DIR / "silero_vad.onnx"

VOICE_LABEL = "dev.openpower.apx.voice"
VOICE_PLIST = HOME / "Library" / "LaunchAgents" / f"{VOICE_LABEL}.plist"

SAMPLE_RATE = 16000

_CONFIG_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "mode": "wake_word",
    "wake_word": "buddy",
    "fallback_agent": "apx",
    "spoken_responses": True,
    "kws_threshold": 0.18,
    "kws_score": 2.0,
    "speech_start_timeout": 8.0,
    "max_listen_seconds": 25.0,
}

_asr = None


def _ensure_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def load_config() -> dict[str, Any]:
    _ensure_dirs()
    value = _load_json(CONFIG_FILE, {})

    if not isinstance(value, dict):
        value = {}

    result = dict(_CONFIG_DEFAULTS)
    result.update(value)
    return result


def save_config(config: dict[str, Any]) -> None:
    _atomic_json(CONFIG_FILE, config)


def update_last(**values: Any) -> None:
    current = _load_json(LAST_FILE, {})

    if not isinstance(current, dict):
        current = {}

    current.update(values)
    current["updated_at"] = datetime.now().astimezone().isoformat()
    _atomic_json(LAST_FILE, current)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def daemon_pid() -> int | None:
    try:
        pid = int(PID_FILE.read_text().strip())
    except Exception:
        return None

    return pid if _pid_alive(pid) else None


def launchd_loaded() -> bool:
    result = subprocess.run(
        [
            "/bin/launchctl",
            "print",
            f"gui/{os.getuid()}/{VOICE_LABEL}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def service_stop() -> None:
    subprocess.run(
        [
            "/bin/launchctl",
            "bootout",
            f"gui/{os.getuid()}/{VOICE_LABEL}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    pid = daemon_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass


def service_start() -> None:
    if not VOICE_PLIST.exists():
        raise RuntimeError(
            f"Voice LaunchAgent is missing: {VOICE_PLIST}"
        )

    service_stop()

    result = subprocess.run(
        [
            "/bin/launchctl",
            "bootstrap",
            f"gui/{os.getuid()}",
            str(VOICE_PLIST),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or "Could not load APX Voice LaunchAgent"
        )

    subprocess.run(
        [
            "/bin/launchctl",
            "kickstart",
            "-k",
            f"gui/{os.getuid()}/{VOICE_LABEL}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def model_files() -> dict[str, Path]:
    return {
        "kws_tokens": KWS_DIR / "tokens.txt",
        "kws_bpe": KWS_DIR / "bpe.model",
        "kws_encoder": KWS_DIR / "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
        "kws_decoder": KWS_DIR / "decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
        "kws_joiner": KWS_DIR / "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
        "kws_keywords": VOICE_DIR / "keywords.txt",
        "asr_preprocessor": ASR_DIR / "preprocess.onnx",
        "asr_encoder": ASR_DIR / "encode.int8.onnx",
        "asr_uncached": ASR_DIR / "uncached_decode.int8.onnx",
        "asr_cached": ASR_DIR / "cached_decode.int8.onnx",
        "asr_tokens": ASR_DIR / "tokens.txt",
        "vad": VAD_MODEL,
    }


def require_models() -> dict[str, Path]:
    files = model_files()
    missing = [
        f"{name}: {path}"
        for name, path in files.items()
        if not path.is_file()
    ]

    if missing:
        raise RuntimeError(
            "Voice models are incomplete:\n  "
            + "\n  ".join(missing)
        )

    return files


def create_kws(
    keywords_file: Path | None = None,
    *,
    threshold: float | None = None,
    score: float | None = None,
):
    import sherpa_onnx

    files = require_models()
    config = load_config()

    return sherpa_onnx.KeywordSpotter(
        tokens=str(files["kws_tokens"]),
        encoder=str(files["kws_encoder"]),
        decoder=str(files["kws_decoder"]),
        joiner=str(files["kws_joiner"]),
        num_threads=1,
        max_active_paths=4,
        keywords_file=str(
            keywords_file or files["kws_keywords"]
        ),
        keywords_score=float(
            score
            if score is not None
            else config.get("kws_score", 2.0)
        ),
        keywords_threshold=float(
            threshold
            if threshold is not None
            else config.get("kws_threshold", 0.18)
        ),
        num_trailing_blanks=1,
        provider="cpu",
    )


def create_asr():
    import sherpa_onnx

    files = require_models()

    return sherpa_onnx.OfflineRecognizer.from_moonshine(
        preprocessor=str(files["asr_preprocessor"]),
        encoder=str(files["asr_encoder"]),
        uncached_decoder=str(files["asr_uncached"]),
        cached_decoder=str(files["asr_cached"]),
        tokens=str(files["asr_tokens"]),
        num_threads=2,
        decoding_method="greedy_search",
        debug=False,
    )


def get_asr():
    global _asr

    if _asr is None:
        update_last(state="loading speech recognition")
        _asr = create_asr()

    return _asr


def create_vad():
    import sherpa_onnx

    files = require_models()

    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(files["vad"])
    config.silero_vad.threshold = 0.5
    config.silero_vad.min_silence_duration = 0.65
    config.silero_vad.min_speech_duration = 0.18
    config.silero_vad.max_speech_duration = float(
        load_config().get("max_listen_seconds", 25.0)
    )
    config.sample_rate = SAMPLE_RATE
    config.num_threads = 1
    config.provider = "cpu"

    return sherpa_onnx.VoiceActivityDetector(
        config,
        buffer_size_in_seconds=30,
    )


def say(text: str) -> None:
    if not load_config().get("spoken_responses", True):
        return

    text = re.sub(r"\s+", " ", str(text)).strip()

    if not text:
        return

    # Keep the spoken surface concise.
    if len(text) > 650:
        text = text[:647].rstrip() + "..."

    subprocess.run(
        ["/usr/bin/say", text],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=45,
        check=False,
    )


def chime() -> None:
    sound = Path("/System/Library/Sounds/Pop.aiff")

    if sound.exists():
        subprocess.run(
            ["/usr/bin/afplay", str(sound)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def record_utterance(
    *,
    start_timeout: float | None = None,
):
    import numpy as np
    import sounddevice as sd

    cfg = load_config()

    if start_timeout is None:
        start_timeout = float(
            cfg.get("speech_start_timeout", 8.0)
        )

    max_seconds = float(
        cfg.get("max_listen_seconds", 25.0)
    )

    vad = create_vad()
    window_size = int(vad.config.silero_vad.window_size)

    started = False
    start_clock = time.monotonic()
    absolute_deadline = start_clock + max_seconds + start_timeout

    update_last(state="listening")

    with sd.InputStream(
        channels=1,
        dtype="float32",
        samplerate=SAMPLE_RATE,
        blocksize=window_size,
    ) as mic:

        while time.monotonic() < absolute_deadline:
            samples, _ = mic.read(window_size)
            samples = np.asarray(samples).reshape(-1)

            vad.accept_waveform(samples)

            try:
                current = vad.current_segment
                if len(current.samples) > 0:
                    started = True
            except Exception:
                pass

            if not vad.empty():
                segment = vad.front
                result = np.asarray(
                    segment.samples,
                    dtype=np.float32,
                ).copy()
                vad.pop()
                return result

            if (
                not started
                and time.monotonic() - start_clock >= start_timeout
            ):
                return None

    try:
        vad.flush()
    except Exception:
        pass

    if not vad.empty():
        import numpy as np

        segment = vad.front
        result = np.asarray(
            segment.samples,
            dtype=np.float32,
        ).copy()
        vad.pop()
        return result

    return None


def transcribe(samples) -> str:
    if samples is None or len(samples) == 0:
        return ""

    recognizer = get_asr()
    stream = recognizer.create_stream()
    stream.accept_waveform(SAMPLE_RATE, samples)
    recognizer.decode_stream(stream)

    text = stream.result.text or ""
    return re.sub(r"\s+", " ", text).strip()


def run_core(args: list[str], timeout: int = 30) -> str:
    if not CORE_APX.exists():
        return "APX runtime is unavailable."

    p = subprocess.run(
        [str(CORE_APX), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        check=False,
    )

    value = p.stdout.strip()

    if not value:
        return (
            "That APX command completed."
            if p.returncode == 0
            else "That APX command failed."
        )

    return value


def open_terminal_command(command: str) -> None:
    terminal_dir = SHARE_DIR / "terminal"
    terminal_dir.mkdir(parents=True, exist_ok=True)

    path = terminal_dir / "voice-action.command"
    path.write_text(
        "#!/bin/bash\n"
        "clear\n"
        f"{command}\n"
    )
    os.chmod(path, 0o700)

    subprocess.Popen(
        ["/usr/bin/open", "-a", "Terminal", str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def set_fallback(agent: str) -> str:
    import shutil

    agent = agent.lower()
    cfg = load_config()

    if agent == "apx":
        cfg["fallback_agent"] = "apx"

    elif agent in ("", "codex"):
        if not shutil.which(agent):
            return f"{agent.title()} is not installed on this computer."

        cfg["fallback_agent"] = agent

    else:
        return "Choose APX, , or Codex."

    save_config(cfg)

    return (
        "I will use APX only."
        if agent == "apx"
        else f"I will use {agent.title()} when reasoning is needed."
    )


def reasoning_fallback(text: str) -> str:
    import shutil

    cfg = load_config()
    agent = str(cfg.get("fallback_agent", "apx")).lower()

    if agent == "apx":
        return (
            "I don't have a deterministic APX action for that yet. "
            "You can choose  or Codex as the reasoning fallback."
        )

    executable = shutil.which(agent)

    if not executable:
        return f"{agent.title()} is not installed."

    prompt = (
        "You are the reasoning fallback for APX Voice. "
        "Do not modify files, services, accounts, machines, repositories, "
        "or configuration. Do not execute destructive actions. "
        "Answer the user's spoken request concisely in at most three "
        "short sentences suitable for text-to-speech. "
        "If the request would require an action, explain what APX should "
        "do instead of performing it.\n\n"
        f"User: {text}"
    )

    try:
        if agent == "":
            help_text = subprocess.run(
                [executable, "--help"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=8,
                check=False,
            ).stdout

            cmd = [executable, "-p", prompt]

            if "--permission-mode" in help_text:
                cmd.extend(["--permission-mode", "plan"])

            if "--effort" in help_text:
                cmd.extend(["--effort", "low"])

        else:
            help_text = subprocess.run(
                [executable, "exec", "--help"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=8,
                check=False,
            ).stdout

            cmd = [executable, "exec"]

            if "--sandbox" in help_text:
                cmd.extend(["--sandbox", "read-only"])

            if "--skip-git-repo-check" in help_text:
                cmd.append("--skip-git-repo-check")

            cmd.append(prompt)

        p = subprocess.run(
            cmd,
            cwd=str(HOME),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=120,
            check=False,
        )

        answer = p.stdout.strip()

        # Keep final CLI decoration from becoming speech.
        lines = [
            line.strip()
            for line in answer.splitlines()
            if line.strip()
        ]

        answer = " ".join(lines)

        if not answer:
            return f"{agent.title()} did not return an answer."

        return answer[:1200]

    except subprocess.TimeoutExpired:
        return f"{agent.title()} took too long to answer."

    except Exception as exc:
        return f"{agent.title()} failed: {exc}"


def route(text: str) -> str:
    lower = text.lower().strip()

    if not lower:
        return "I didn't catch that."

    if any(
        phrase in lower
        for phrase in (
            "go to sleep",
            "stop listening",
            "voice off",
        )
    ):
        cfg = load_config()
        cfg["enabled"] = False
        cfg["mode"] = "off"
        save_config(cfg)
        return "Voice Agent is off."

    if "use " in lower:
        return set_fallback("")

    if "use codex" in lower:
        return set_fallback("codex")

    if (
        "apx only" in lower
        or "don't use ai" in lower
        or "do not use ai" in lower
    ):
        return set_fallback("apx")

    if any(
        phrase in lower
        for phrase in (
            "what time is it",
            "what's the time",
            "what is the time",
        )
    ):
        return datetime.now().strftime(
            "It is %-I:%M %p."
        )

    if any(
        phrase in lower
        for phrase in (
            "open apx",
            "show apx",
        )
    ):
        open_terminal_command(
            shlex.quote(str(HOME / ".local/bin/apx"))
        )
        return "Opening APX."

    if any(
        phrase in lower
        for phrase in (
            "start ",
            "open ",
        )
    ):
        open_terminal_command("exec ")
        return "Starting ."

    if any(
        phrase in lower
        for phrase in (
            "start codex",
            "open codex",
        )
    ):
        open_terminal_command("exec codex")
        return "Starting Codex."

    if any(
        phrase in lower
        for phrase in (
            "apx version",
            "what version",
        )
    ):
        result = run_core(["--version"])
        return result

    if any(
        phrase in lower
        for phrase in (
            "apx status",
            "system status",
        )
    ):
        result = run_core(["status"])
        return result[:700]

    if any(
        phrase in lower
        for phrase in (
            "doctor",
            "check apx",
            "health check",
        )
    ):
        result = run_core(["doctor"], timeout=60)
        return result[:700]

    if any(
        phrase in lower
        for phrase in (
            "list computers",
            "what computers",
            "show computers",
        )
    ):
        result = run_core(["hosts"])
        return result[:700]

    if "update apx" in lower:
        return (
            "APX has an update action, but I won't replace running "
            "software from a voice command. Use Update APX in the menu bar."
        )

    return reasoning_fallback(text)


def voice_turn(*, chime_first: bool = True) -> str:
    if chime_first:
        chime()

    samples = record_utterance()

    if samples is None:
        update_last(
            state="ready",
            transcript="",
            response="No speech detected",
        )
        return ""

    update_last(state="transcribing")

    text = transcribe(samples)

    if not text:
        answer = "I didn't catch that."
        update_last(
            state="ready",
            transcript="",
            response=answer,
        )
        say(answer)
        return answer

    update_last(
        state="thinking",
        transcript=text,
    )

    answer = route(text)

    update_last(
        state="speaking",
        transcript=text,
        response=answer,
    )

    say(answer)

    update_last(
        state="ready",
        transcript=text,
        response=answer,
    )

    return answer


def wake_loop() -> None:
    import sounddevice as sd

    update_last(state="loading wake word")

    spotter = create_kws()

    while True:
        cfg = load_config()

        if (
            not cfg.get("enabled", False)
            or cfg.get("mode") != "wake_word"
        ):
            return

        stream = spotter.create_stream()
        triggered = False

        update_last(state="waiting for wake word")

        with sd.InputStream(
            channels=1,
            dtype="float32",
            samplerate=SAMPLE_RATE,
            blocksize=int(0.1 * SAMPLE_RATE),
        ) as mic:

            while True:
                cfg = load_config()

                if (
                    not cfg.get("enabled", False)
                    or cfg.get("mode") != "wake_word"
                ):
                    return

                samples, _ = mic.read(
                    int(0.1 * SAMPLE_RATE)
                )

                samples = samples.reshape(-1)
                stream.accept_waveform(
                    SAMPLE_RATE,
                    samples,
                )

                while spotter.is_ready(stream):
                    spotter.decode_stream(stream)

                result = spotter.get_result(stream)

                if result:
                    triggered = True
                    update_last(
                        state="wake word detected",
                        keyword=str(result),
                    )
                    spotter.reset_stream(stream)
                    break

        if triggered:
            voice_turn(chime_first=True)
            time.sleep(0.25)


def always_loop() -> None:
    while True:
        cfg = load_config()

        if (
            not cfg.get("enabled", False)
            or cfg.get("mode") != "always_listening"
        ):
            return

        samples = record_utterance(
            start_timeout=3600.0
        )

        if samples is None:
            continue

        text = transcribe(samples)

        if not text:
            continue

        update_last(
            state="thinking",
            transcript=text,
        )

        answer = route(text)

        update_last(
            state="speaking",
            transcript=text,
            response=answer,
        )

        say(answer)

        update_last(
            state="ready",
            transcript=text,
            response=answer,
        )

        time.sleep(0.2)


def daemon() -> int:
    _ensure_dirs()

    PID_FILE.write_text(str(os.getpid()) + "\n")

    def finish(*_args: Any) -> None:
        try:
            PID_FILE.unlink()
        except Exception:
            pass
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, finish)
    signal.signal(signal.SIGINT, finish)

    cfg = load_config()

    try:
        if not cfg.get("enabled", False):
            update_last(state="off")
            return 0

        mode = cfg.get("mode")

        if mode == "wake_word":
            wake_loop()

        elif mode == "always_listening":
            always_loop()

        else:
            update_last(state=mode or "idle")

        return 0

    except Exception as exc:
        # Exit successfully so launchd does not spin in a crash loop.
        update_last(
            state="error",
            error=str(exc),
        )
        print(
            f"APX Voice: {exc}",
            file=sys.stderr,
        )
        return 0

    finally:
        try:
            PID_FILE.unlink()
        except Exception:
            pass


def regenerate_keyword(phrase: str) -> None:
    phrase = re.sub(
        r"\s+",
        " ",
        phrase.strip(),
    )

    if not phrase:
        raise ValueError("Wake word cannot be empty")

    cli = VOICE_DIR / "venv" / "bin" / "sherpa-onnx-cli"

    if not cli.exists():
        raise RuntimeError(
            "sherpa-onnx-cli is not installed"
        )

    files = require_models()

    raw = VOICE_DIR / "keywords_raw.txt"
    out = VOICE_DIR / "keywords.txt"

    upper = phrase.upper()

    rows = [
        f"{upper} :2.0 #0.18",
    ]

    if not upper.startswith("HEY "):
        rows.append(
            f"HEY {upper} :2.0 #0.18"
        )

    raw.write_text(
        "\n".join(rows) + "\n"
    )

    p = subprocess.run(
        [
            str(cli),
            "text2token",
            "--tokens",
            str(files["kws_tokens"]),
            "--tokens-type",
            "bpe",
            "--bpe-model",
            str(files["kws_bpe"]),
            str(raw),
            str(out),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )

    if p.returncode != 0 or not out.exists():
        raise RuntimeError(
            p.stdout.strip()
            or "Could not generate wake-word tokens"
        )


def _read_wave(path: Path):
    import numpy as np

    with wave.open(str(path), "rb") as f:
        channels = f.getnchannels()
        width = f.getsampwidth()
        rate = f.getframerate()
        frames = f.readframes(f.getnframes())

    if channels != 1 or width != 2:
        raise RuntimeError(
            f"Unsupported test WAV: {path}"
        )

    samples = np.frombuffer(
        frames,
        dtype=np.int16,
    ).astype(np.float32) / 32768.0

    return rate, samples


def self_test() -> int:
    import numpy as np
    import sherpa_onnx

    print("Voice runtime:")
    print(
        "  sherpa-onnx",
        getattr(sherpa_onnx, "__version__", "unknown"),
    )

    files = require_models()

    print("KWS canonical inference:")

    test_keywords = KWS_DIR / "test_wavs" / "test_keywords.txt"

    test_wavs = sorted(
        (KWS_DIR / "test_wavs").glob("*.wav")
    )

    if not test_keywords.exists() or not test_wavs:
        raise RuntimeError(
            "Official KWS test material is missing"
        )

    spotter = create_kws(
        test_keywords,
        threshold=0.25,
        score=1.0,
    )

    detected = []

    for wav_path in test_wavs[:2]:
        rate, samples = _read_wave(wav_path)
        stream = spotter.create_stream()
        chunk = max(1, int(rate * 0.1))

        padded = np.concatenate(
            [
                samples,
                np.zeros(int(rate * 1.0), dtype=np.float32),
            ]
        )

        for i in range(0, len(padded), chunk):
            part = padded[i:i + chunk]

            if len(part) < chunk:
                part = np.pad(
                    part,
                    (0, chunk - len(part)),
                )

            stream.accept_waveform(
                rate,
                part,
            )

            while spotter.is_ready(stream):
                spotter.decode_stream(stream)

            value = spotter.get_result(stream)

            if value:
                detected.append(str(value))
                spotter.reset_stream(stream)

    if not detected:
        raise RuntimeError(
            "KWS model loaded but failed its official audio self-test"
        )

    print(
        "  PASS —",
        ", ".join(detected[:4]),
    )

    print("Moonshine ASR canonical inference:")

    asr_tests = sorted(
        (ASR_DIR / "test_wavs").glob("*.wav")
    )

    if not asr_tests:
        raise RuntimeError(
            "Official Moonshine test WAV is missing"
        )

    rate, samples = _read_wave(asr_tests[0])
    recognizer = create_asr()
    stream = recognizer.create_stream()
    stream.accept_waveform(rate, samples)
    recognizer.decode_stream(stream)

    text = (
        stream.result.text or ""
    ).strip()

    if not text:
        raise RuntimeError(
            "Moonshine loaded but returned no transcript"
        )

    print("  PASS —", text[:120])

    print("Silero VAD model:")
    create_vad()
    print("  PASS")

    return 0


def doctor() -> int:
    import shutil

    result: dict[str, Any] = {
        "ok": True,
        "models": {},
        "packages": {},
        "microphone": None,
        "menu_bar_app": str(
            HOME / "Applications" / "APX.app"
        ),
    }

    for package in (
        "sherpa_onnx",
        "sounddevice",
        "numpy",
    ):
        try:
            module = __import__(package)
            result["packages"][package] = (
                getattr(module, "__version__", "installed")
            )
        except Exception as exc:
            result["packages"][package] = f"ERROR: {exc}"
            result["ok"] = False

    for name, path in model_files().items():
        result["models"][name] = path.exists()

        if not path.exists():
            result["ok"] = False

    try:
        import sounddevice as sd

        index = sd.default.device[0]
        devices = sd.query_devices()

        if index is not None and int(index) >= 0:
            result["microphone"] = devices[int(index)]["name"]
        else:
            result["microphone"] = "No default input device"
            result["ok"] = False

    except Exception as exc:
        result["microphone"] = f"ERROR: {exc}"
        result["ok"] = False

    result["voice_daemon_pid"] = daemon_pid()
    result["launchd_loaded"] = launchd_loaded()
    result["config"] = load_config()

    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


def status(as_json: bool = False) -> int:
    cfg = load_config()
    last = _load_json(LAST_FILE, {})

    data = {
        "enabled": bool(cfg.get("enabled")),
        "mode": cfg.get("mode"),
        "wake_word": cfg.get("wake_word"),
        "fallback_agent": cfg.get("fallback_agent"),
        "spoken_responses": cfg.get("spoken_responses"),
        "running": daemon_pid() is not None,
        "pid": daemon_pid(),
        "launchd_loaded": launchd_loaded(),
        "state": (
            last.get("state")
            if isinstance(last, dict)
            else None
        ),
        "last_transcript": (
            last.get("transcript")
            if isinstance(last, dict)
            else None
        ),
        "last_response": (
            last.get("response")
            if isinstance(last, dict)
            else None
        ),
        "error": (
            last.get("error")
            if isinstance(last, dict)
            else None
        ),
    }

    if as_json:
        print(json.dumps(data))
        return 0

    print()
    print("Voice Agent")
    print("===========")
    print(
        f"Status          "
        f"{'ON' if data['enabled'] else 'OFF'}"
    )
    print(
        f"Runtime         "
        f"{'Running' if data['running'] else 'Stopped'}"
    )
    print(
        f"Mode            "
        f"{str(data['mode']).replace('_', ' ')}"
    )
    print(
        f"Wake word       "
        f"{data['wake_word']}"
    )
    print(
        f"Reasoning       "
        f"{str(data['fallback_agent']).title()}"
    )

    if data.get("state"):
        print(
            f"State           "
            f"{data['state']}"
        )

    if data.get("error"):
        print(
            f"Last error      "
            f"{data['error']}"
        )

    if data.get("last_transcript"):
        print()
        print(
            "You: ",
            data["last_transcript"],
        )

    if data.get("last_response"):
        print(
            "APX: ",
            data["last_response"],
        )

    print()
    return 0


def set_mode(value: str) -> int:
    aliases = {
        "off": "off",
        "ptt": "push_to_talk",
        "push": "push_to_talk",
        "push-to-talk": "push_to_talk",
        "push_to_talk": "push_to_talk",
        "wake": "wake_word",
        "wake-word": "wake_word",
        "wake_word": "wake_word",
        "always": "always_listening",
        "24/7": "always_listening",
        "always-listening": "always_listening",
        "always_listening": "always_listening",
    }

    key = value.lower()

    if key not in aliases:
        raise SystemExit(
            "Use: off, push-to-talk, wake-word, or always"
        )

    cfg = load_config()
    cfg["mode"] = aliases[key]
    cfg["enabled"] = aliases[key] != "off"
    save_config(cfg)

    if aliases[key] in (
        "wake_word",
        "always_listening",
    ):
        if VOICE_PLIST.exists():
            service_start()
    else:
        service_stop()

    print(
        "Voice mode:",
        aliases[key].replace("_", " "),
    )
    return 0


def set_agent(value: str) -> int:
    answer = set_fallback(value)

    if "not installed" in answer.lower():
        print(answer)
        return 1

    print(answer)
    return 0


def interactive() -> int:
    while True:
        cfg = load_config()

        print()
        print("APX  ›  Voice Agent")
        print("===================")
        print()
        print(
            "Status:     ",
            "ON" if cfg.get("enabled") else "OFF",
        )
        print(
            "Mode:       ",
            str(cfg.get("mode")).replace("_", " "),
        )
        print(
            "Wake word:  ",
            cfg.get("wake_word"),
        )
        print(
            "Reasoning:  ",
            str(cfg.get("fallback_agent")).title(),
        )
        print()
        print("1  Talk now")
        print("2  Start wake-word listening")
        print("3  Push to talk")
        print("4  Always listening / 24/7")
        print("5  Stop Voice Agent")
        print("6  Change wake word")
        print("7  APX only")
        print("8   reasoning")
        print("9  Codex reasoning")
        print("10 Status")
        print("11 Doctor")
        print("12 Test speaker")
        print()
        print("b  Back")
        print()

        try:
            choice = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if choice == "b":
            return 0

        if choice == "1":
            voice_turn()

        elif choice == "2":
            set_mode("wake-word")

        elif choice == "3":
            set_mode("push-to-talk")

        elif choice == "4":
            set_mode("always")

        elif choice == "5":
            set_mode("off")

        elif choice == "6":
            phrase = input("Wake word: ").strip()

            if phrase:
                regenerate_keyword(phrase)
                cfg = load_config()
                cfg["wake_word"] = phrase
                save_config(cfg)

                if daemon_pid():
                    service_start()

        elif choice == "7":
            set_agent("apx")

        elif choice == "8":
            set_agent("")

        elif choice == "9":
            set_agent("codex")

        elif choice == "10":
            status()

        elif choice == "11":
            doctor()

        elif choice == "12":
            say("APX Voice is ready.")


def main(argv: list[str] | None = None) -> int:
    argv = list(
        sys.argv[1:]
        if argv is None
        else argv
    )

    command = argv[0] if argv else "status"
    args = argv[1:]

    if command in ("status", "show"):
        return status("--json" in args)

    if command == "doctor":
        return doctor()

    if command in ("self-test", "selftest"):
        return self_test()

    if command == "test-speak":
        say("APX Voice is ready.")
        print("Speaker test sent.")
        return 0

    if command == "interactive":
        return interactive()

    if command == "talk":
        voice_turn()
        return 0

    if command == "start":
        cfg = load_config()
        cfg["enabled"] = True

        if cfg.get("mode") == "off":
            cfg["mode"] = "wake_word"

        save_config(cfg)

        if cfg.get("mode") in (
            "wake_word",
            "always_listening",
        ):
            service_start()

        print("Voice Agent started.")
        return 0

    if command == "stop":
        cfg = load_config()
        cfg["enabled"] = False
        cfg["mode"] = "off"
        save_config(cfg)
        service_stop()
        print("Voice Agent stopped.")
        return 0

    if command == "restart":
        cfg = load_config()

        if (
            cfg.get("enabled")
            and cfg.get("mode")
            in ("wake_word", "always_listening")
        ):
            service_start()
        else:
            service_stop()

        return 0

    if command == "mode":
        if not args:
            raise SystemExit(
                "Usage: apx voice mode "
                "off|push-to-talk|wake-word|always"
            )
        return set_mode(args[0])

    if command == "wake-word":
        if not args:
            raise SystemExit(
                "Usage: apx voice wake-word PHRASE"
            )

        phrase = " ".join(args).strip()
        regenerate_keyword(phrase)

        cfg = load_config()
        cfg["wake_word"] = phrase
        save_config(cfg)

        if daemon_pid():
            service_start()

        print("Wake word:", phrase)
        return 0

    if command == "agent":
        if not args:
            raise SystemExit(
                "Usage: apx voice agent apx||codex"
            )
        return set_agent(args[0])

    if command == "_daemon":
        return daemon()

    print(
        "APX Voice\n\n"
        "  apx voice\n"
        "  apx voice talk\n"
        "  apx voice start\n"
        "  apx voice stop\n"
        "  apx voice mode wake-word\n"
        "  apx voice mode push-to-talk\n"
        "  apx voice mode always\n"
        "  apx voice wake-word buddy\n"
        "  apx voice agent apx||codex\n"
        "  apx voice doctor\n"
        "  apx voice self-test\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
