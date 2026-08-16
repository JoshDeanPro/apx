import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HOME = Path.home()

OUTER = HOME / ".local" / "bin" / "apx"

NATIVE = Path(
    os.environ.get(
        "APX_NATIVE_BINARY",
        str(
            HOME
            / ".local"
            / "share"
            / "apx"
            / "runtime"
            / "bin"
            / "apx"
        ),
    )
)

VOICE_CONFIG = HOME / ".config" / "apx" / "voice.json"
VOICE_PID = (
    HOME
    / ".local"
    / "state"
    / "apx"
    / "voice"
    / "daemon.pid"
)


def _cmd(target_path: Path) -> list[str]:
    if target_path.exists():
        return [str(target_path)]
    found = shutil.which("apx")
    if found:
        return [found]
    return [sys.executable, "-m", "apx.cli"]


def native(*args: str) -> None:
    subprocess.run(
        [*_cmd(NATIVE), *args],
        check=False,
    )


def outer(*args: str) -> None:
    subprocess.run(
        [*_cmd(OUTER), *args],
        check=False,
    )



def voice_badge() -> str:
    try:
        cfg = json.loads(
            VOICE_CONFIG.read_text()
        )
    except Exception:
        return "OFF"

    if not cfg.get("enabled"):
        return "OFF"

    try:
        pid = int(
            VOICE_PID.read_text().strip()
        )
        os.kill(pid, 0)
        running = True
    except Exception:
        running = False

    mode = str(
        cfg.get("mode", "off")
    ).replace("_", " ")

    return (
        f"{mode} • {'RUNNING' if running else 'READY'}"
    )


def pause() -> None:
    try:
        input("\nPress Return...")
    except (EOFError, KeyboardInterrupt):
        pass


def main() -> int:
    while True:
        print("\033[2J\033[H", end="")

        print("APX")
        print("===")
        print()
        print(
            f"1   Voice Agent"
            f"                  [{voice_badge()}]"
        )
        print("2   Computers")
        print("3   AI Agents")
        print("4   Connections / APIs / MCP")
        print("5   Projects")
        print("6   Passwords & API Keys")
        print("7   Plugins")
        print("8   Prompts")
        print("9   Scripts & Automation")
        print("10  Security")
        print("11  System")
        print("12  Native APX menu")
        print()
        print("q   Quit")
        print()

        try:
            choice = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if choice in ("q", "quit", "exit"):
            return 0

        if choice == "1":
            outer("voice", "interactive")

        elif choice == "2":
            native("hosts")
            pause()

        elif choice == "3":
            native("agent", "--help")
            pause()

        elif choice == "4":
            native("mcp", "--help")
            pause()

        elif choice == "5":
            native("projects")
            pause()

        elif choice == "6":
            native("secret", "health")
            pause()

        elif choice == "7":
            native("plugins")
            pause()

        elif choice == "8":
            native("prompts")
            pause()

        elif choice == "9":
            native("services")
            pause()

        elif choice == "10":
            native("security")
            pause()

        elif choice == "11":
            native("doctor")
            pause()

        elif choice == "12":
            native("menu")


if __name__ == "__main__":
    raise SystemExit(main())
