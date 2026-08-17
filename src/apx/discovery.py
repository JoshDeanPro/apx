# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import textwrap
from typing import Any

from .models import Host
from .transports import transport_for


PROBE = textwrap.dedent(r'''
import json, os, platform, re, shutil, socket, subprocess
def run(argv):
    try:
        p=subprocess.run(argv,capture_output=True,text=True,timeout=8)
        return {"ok":p.returncode==0,"out":p.stdout.strip()[:12000],"error":p.stderr.strip()[:1000]}
    except Exception as e: return {"ok":False,"out":"","error":str(e)}
commands={"ssh":"ssh","ssh_agent":"ssh-agent","tailscale":"tailscale","aws":"aws","git":"git","rsync":"rsync","fast_search":"rg","curl":"curl","scp":"scp","sftp":"sftp","systemd":"systemctl","launchd":"launchctl","cron":"crontab","docker":"docker","podman":"podman","postgres":"psql","pg_dump":"pg_dump","pg_restore":"pg_restore","mysql":"mysql","mysqldump":"mysqldump","sqlite":"sqlite3","caddy":"caddy","nginx":"nginx","apache":"apachectl","node":"node","python":"python3","redis":"redis-cli","grafana":"grafana-server","prometheus":"prometheus","n8n":"n8n","nvidia":"nvidia-smi"}
if not shutil.which("tailscale"):
 for candidate in ("/Applications/Tailscale.app/Contents/MacOS/Tailscale","/usr/local/bin/tailscale"):
  if os.path.isfile(candidate) and os.access(candidate,os.X_OK): commands["tailscale"]=candidate; break
caps={name:{"available":bool(shutil.which(cmd)),"command":shutil.which(cmd)} for name,cmd in commands.items()}
version_args={"ssh":["-V"],"git":["--version"],"rsync":["--version"],"fast_search":["--version"],"curl":["--version"],"systemd":["--version"],"docker":["--version"],"podman":["--version"],"postgres":["--version"],"pg_dump":["--version"],"pg_restore":["--version"],"mysql":["--version"],"mysqldump":["--version"],"sqlite":["--version"],"caddy":["version"],"nginx":["-v"],"apache":["-v"],"node":["--version"],"python":["--version"],"redis":["--version"],"grafana":["-v"],"prometheus":["--version"],"n8n":["--version"],"tailscale":["version"],"aws":["--version"]}
for name,args in version_args.items():
 if caps[name]["available"]:
  version=run([commands[name],*args]); text=(version["out"] or version["error"]).splitlines()
  caps[name]["version"]=text[0][:300] if text else None
system=platform.system()
memory=run(["free","-b"]) if system=="Linux" else run(["sysctl","-n","hw.memsize"])
gpu=run(["nvidia-smi","--query-gpu=name,memory.total","--format=csv,noheader"]) if caps["nvidia"]["available"] else {"ok":False,"out":""}
disk=run(["df","-h","/"])
cpu=run(["sysctl","-n","machdep.cpu.brand_string"]) if system=="Darwin" else run(["lscpu"])
apple_silicon=system=="Darwin" and platform.machine()=="arm64"
def battery():
 if system=="Darwin":
  r=run(["pmset","-g","batt"])
  if not r["ok"] or "InternalBattery" not in r["out"]: return {"present":False}
  line=next((l for l in r["out"].splitlines() if "InternalBattery" in l),"")
  charging="AC Power" in r["out"] and "discharging" not in line
  match=re.search(r"(\d{1,3})%",line)
  return {"present":True,"percent":int(match.group(1)) if match else None,"charging":charging}
 base="/sys/class/power_supply"
 if system=="Linux" and os.path.isdir(base):
  for entry in os.listdir(base):
   if entry.startswith("BAT"):
    try:
     percent=int(open(f"{base}/{entry}/capacity").read().strip())
     status=open(f"{base}/{entry}/status").read().strip().lower()
     return {"present":True,"percent":percent,"charging":status=="charging"}
    except Exception: continue
  return {"present":False}
 return {"present":None}
browsers={name:bool((cmd and shutil.which(cmd)) or (system=="Darwin" and os.path.isdir(f"/Applications/{app}.app"))) for name,cmd,app in (("chrome","google-chrome","Google Chrome"),("chromium","chromium","Chromium"),("edge","microsoft-edge","Microsoft Edge"),("firefox","firefox","Firefox"),("safari",None,"Safari"))}
try:
 import importlib.util as _ilu
 browsers["playwright"]=_ilu.find_spec("playwright") is not None
except Exception: browsers["playwright"]=False
local_ai={"ollama":bool(shutil.which("ollama")),"lmstudio":system=="Darwin" and os.path.isdir(os.path.expanduser("~/Applications/LM Studio.app")),"llama_cpp":bool(shutil.which("llama-cli") or shutil.which("main"))}
service_manager="systemd" if caps["systemd"]["available"] else "launchd" if caps["launchd"]["available"] else None
print(json.dumps({"hostname":socket.gethostname(),"os":system,"release":platform.release(),"architecture":platform.machine(),"apple_silicon":apple_silicon,"python":platform.python_version(),"user":os.environ.get("USER") or os.environ.get("LOGNAME"),"cpu":cpu["out"],"memory":memory["out"],"gpu":gpu["out"],"disk":disk["out"],"battery":battery(),"browsers":browsers,"local_ai":local_ai,"service_manager":service_manager,"ssh":{"known_hosts":os.path.exists(os.path.expanduser("~/.ssh/known_hosts")),"config":os.path.exists(os.path.expanduser("~/.ssh/config"))},"capabilities":caps}))
''')


def inspect_host(host: Host) -> dict[str, Any]:
    result = transport_for(host).run(["python3", "-c", PROBE], timeout=25)
    if not result.ok:
        raise RuntimeError(result.stderr.strip() or f"discovery failed with exit {result.exit_code}")
    data = json.loads(result.stdout)
    data.update(name=host.name, transport=host.transport, target=host.target)
    return data
