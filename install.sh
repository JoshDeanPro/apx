#!/bin/bash
set -u
set -o pipefail

REPO="JoshDeanPro/apx"
DATA="$HOME/.local/share/apx"
RUNTIME="$DATA/runtime"
NEXT="$DATA/runtime-next"
PREVIOUS="$DATA/runtime-previous"
BIN="$HOME/.local/bin"
TMP="$(mktemp -d)"

fail() {
  printf 'APX could not be installed: %s\n' "$1" >&2
  rm -rf "$TMP" "$NEXT" 2>/dev/null || true
  exit 1
}

find_python() {
  for c in \
    /opt/homebrew/opt/python@3.13/libexec/bin/python3 \
    /opt/homebrew/bin/python3.13 \
    /opt/homebrew/bin/python3.12 \
    /opt/homebrew/bin/python3.11 \
    python3.13 python3.12 python3.11 python3
  do
    if [ -x "$c" ]; then
      p="$c"
    elif command -v "$c" >/dev/null 2>&1; then
      p="$(command -v "$c")"
    else
      continue
    fi

    "$p" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1
    if [ "$?" -eq 0 ]; then
      printf '%s\n' "$p"
      return 0
    fi
  done
  return 1
}

PY="$(find_python || true)"

if [ -z "$PY" ]; then
  case "$(uname -s)" in
    Darwin)
      command -v brew >/dev/null 2>&1 || fail "Python 3.11 or newer is required."
      brew install python@3.13 >/dev/null 2>&1 || fail "Python could not be installed."
      ;;
    Linux)
      if [ "$(id -u)" -eq 0 ]; then
        SUDO=""
      elif command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
      else
        fail "Python 3.11 or newer is required."
      fi
      $SUDO apt-get update -qq || fail "Package information could not be updated."
      $SUDO apt-get install -y -qq python3 python3-venv curl ca-certificates >/dev/null || fail "Python could not be installed."
      ;;
    *)
      fail "Python 3.11 or newer is required."
      ;;
  esac
  PY="$(find_python || true)"
  [ -n "$PY" ] || fail "Python 3.11 or newer is required."
fi

NODE_OK=0
if command -v node >/dev/null 2>&1; then
  MAJOR="$(node -p 'Number(process.versions.node.split(".")[0])' 2>/dev/null || printf 0)"
  if [ "$MAJOR" -ge 22 ]; then
    NODE_OK=1
  fi
fi

if [ "$NODE_OK" -ne 1 ]; then
  case "$(uname -s)" in
    Darwin)
      command -v brew >/dev/null 2>&1 || fail "Node.js 22 or newer is required."
      brew install node >/dev/null 2>&1 || brew upgrade node >/dev/null 2>&1 || fail "Node.js could not be installed."
      ;;
    Linux)
      if [ "$(id -u)" -eq 0 ]; then
        SUDO=""
      elif command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
      else
        fail "Node.js 22 or newer is required."
      fi
      $SUDO apt-get update -qq || fail "Package information could not be updated."
      $SUDO apt-get install -y -qq ca-certificates curl gnupg >/dev/null || fail "Node.js requirements could not be installed."
      curl -fsSL https://deb.nodesource.com/setup_22.x -o "$TMP/node-setup.sh" || fail "Node.js setup could not be downloaded."
      $SUDO bash "$TMP/node-setup.sh" >/dev/null 2>&1 || fail "Node.js setup failed."
      $SUDO apt-get install -y -qq nodejs >/dev/null || fail "Node.js could not be installed."
      ;;
    *)
      fail "Node.js 22 or newer is required."
      ;;
  esac
fi

command -v npm >/dev/null 2>&1 || fail "npm is required."
MAJOR="$(node -p 'Number(process.versions.node.split(".")[0])' 2>/dev/null || printf 0)"
[ "$MAJOR" -ge 22 ] || fail "Node.js 22 or newer is required."

curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" -o "$TMP/release.json" || fail "The latest APX release could not be found."

"$PY" - "$TMP/release.json" "$TMP/info" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text())
tag = str(data.get("tag_name") or "").strip()
if not tag:
    raise SystemExit(1)
version = tag.removeprefix("v")
wheel = f"apx-{version}-py3-none-any.whl"
asset = next((a for a in data.get("assets", []) if a.get("name") == wheel), None)
if not asset or not asset.get("browser_download_url"):
    raise SystemExit(1)
Path(sys.argv[2]).write_text(
    version + "\n" + wheel + "\n" + str(asset["browser_download_url"]) + "\n" + str(asset.get("digest") or "") + "\n"
)
PY
[ "$?" -eq 0 ] || fail "The latest APX release is incomplete."

VERSION="$(sed -n '1p' "$TMP/info")"
WHEEL="$(sed -n '2p' "$TMP/info")"
URL="$(sed -n '3p' "$TMP/info")"
DIGEST="$(sed -n '4p' "$TMP/info")"

curl -fL "$URL" -o "$TMP/$WHEEL" || fail "The APX package could not be downloaded."

if [ -n "$DIGEST" ]; then
  EXPECTED="$(printf '%s' "$DIGEST" | sed 's/^sha256://')"
  ACTUAL=""

  if command -v shasum >/dev/null 2>&1; then
    ACTUAL="$(shasum -a 256 "$TMP/$WHEEL" | awk '{print $1}')"
  elif command -v sha256sum >/dev/null 2>&1; then
    ACTUAL="$(sha256sum "$TMP/$WHEEL" | awk '{print $1}')"
  fi

  if [ -n "$ACTUAL" ]; then
    if [ "$ACTUAL" != "$EXPECTED" ]; then
      fail "The APX package failed its integrity check."
    fi
  fi
fi

rm -rf "$NEXT"
"$PY" -m venv "$NEXT" || fail "The APX runtime could not be prepared."
"$NEXT/bin/python" -m pip install --quiet --upgrade pip setuptools wheel || fail "The APX runtime could not be prepared."
"$NEXT/bin/python" -m pip install --quiet "$TMP/$WHEEL" || fail "APX could not be installed."

UI="$("$NEXT/bin/python" -c 'from pathlib import Path; import apx; print(Path(apx.__file__).resolve().parent / "_ui")')"
for f in index.mjs package.json package-lock.json; do
  [ -f "$UI/$f" ] || fail "The APX terminal runtime is incomplete."
done

(cd "$UI" && npm ci --omit=dev --no-audit --no-fund) >/dev/null || fail "The APX terminal runtime could not be prepared."
NODE_ENV=production DEV=false APX_PYTHON="$NEXT/bin/python" node "$UI/index.mjs" --smoke >/dev/null 2>&1 || fail "The APX terminal interface could not start."
"$NEXT/bin/apx" --version >/dev/null || fail "The new APX version could not start."

mkdir -p "$DATA" "$BIN"
rm -rf "$PREVIOUS"

if [ -d "$RUNTIME" ]; then
  mv "$RUNTIME" "$PREVIOUS" || fail "The current APX version could not be preserved."
fi

if ! mv "$NEXT" "$RUNTIME"; then
  if [ -d "$PREVIOUS" ]; then
    mv "$PREVIOUS" "$RUNTIME" 2>/dev/null || true
  fi
  fail "The new APX version could not be activated."
fi

cat > "$BIN/apx" <<'LAUNCHER'
#!/bin/bash
exec "$HOME/.local/share/apx/runtime/bin/apx" "$@"
LAUNCHER

chmod 755 "$BIN/apx"
printf '● APX %s is ready\n' "$VERSION"
rm -rf "$TMP" 2>/dev/null || true
