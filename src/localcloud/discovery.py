from __future__ import annotations

import json
import textwrap
from typing import Any

from .models import Host
from .transports import transport_for


PROBE = textwrap.dedent(r'''
import json, os, platform, shutil, socket, subprocess
def run(argv):
    try:
        p=subprocess.run(argv,capture_output=True,text=True,timeout=8)
        return {"ok":p.returncode==0,"out":p.stdout.strip()[:12000],"error":p.stderr.strip()[:1000]}
    except Exception as e: return {"ok":False,"out":"","error":str(e)}
commands={"ssh":"ssh","git":"git","rsync":"rsync","scp":"scp","sftp":"sftp","systemd":"systemctl","launchd":"launchctl","docker":"docker","podman":"podman","postgres":"psql","mysql":"mysql","sqlite":"sqlite3","caddy":"caddy","nginx":"nginx","apache":"apachectl","node":"node","python":"python3","nvidia":"nvidia-smi","grafana":"grafana-server","prometheus":"prometheus"}
caps={name:{"available":bool(shutil.which(cmd)),"command":shutil.which(cmd)} for name,cmd in commands.items()}
system=platform.system()
memory=run(["free","-b"]) if system=="Linux" else run(["sysctl","-n","hw.memsize"])
gpu=run(["nvidia-smi","--query-gpu=name,memory.total","--format=csv,noheader"]) if caps["nvidia"]["available"] else {"ok":False,"out":""}
disk=run(["df","-h","/"])
cpu=run(["sysctl","-n","machdep.cpu.brand_string"]) if system=="Darwin" else run(["lscpu"])
print(json.dumps({"hostname":socket.gethostname(),"os":system,"release":platform.release(),"architecture":platform.machine(),"python":platform.python_version(),"user":os.environ.get("USER") or os.environ.get("LOGNAME"),"cpu":cpu["out"],"memory":memory["out"],"gpu":gpu["out"],"disk":disk["out"],"capabilities":caps}))
''')


def inspect_host(host: Host) -> dict[str, Any]:
    result = transport_for(host).run(["python3", "-c", PROBE], timeout=25)
    if not result.ok:
        raise RuntimeError(result.stderr.strip() or f"discovery failed with exit {result.exit_code}")
    data = json.loads(result.stdout)
    data.update(name=host.name, transport=host.transport, target=host.target)
    return data

