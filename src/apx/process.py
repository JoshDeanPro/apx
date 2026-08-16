# SPDX-License-Identifier: MPL-2.0
"""One bounded, shell-free subprocess boundary for core and plugins."""
from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping,Sequence

DEFAULT_TIMEOUT=30
MAX_OUTPUT_BYTES=1024*1024


class ProcessError(RuntimeError): pass
class ProcessTimeout(ProcessError): pass


@dataclass(frozen=True)
class ProcessResult:
    argv: tuple[str,...]
    exit_code: int
    stdout: str
    stderr: str
    truncated: bool=False
    @property
    def ok(self)->bool: return self.exit_code==0


def run(argv: Sequence[str], *, timeout: int=DEFAULT_TIMEOUT, cwd: str|Path|None=None,
        input_text: str|None=None, env: Mapping[str,str]|None=None,
        inherit_env: bool=True, max_output_bytes: int=MAX_OUTPUT_BYTES) -> ProcessResult:
    if not argv or not all(isinstance(value,str) and "\x00" not in value for value in argv): raise ProcessError("argv must be non-empty strings without NUL bytes")
    environment=dict(os.environ) if inherit_env else {}
    if env: environment.update(env)
    with tempfile.TemporaryFile() as stdout_file,tempfile.TemporaryFile() as stderr_file:
        try:
            process=subprocess.Popen(list(argv),cwd=cwd,stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                stdout=stdout_file,stderr=stderr_file,text=False,env=environment,shell=False)
            process.communicate(input_text.encode() if input_text is not None else None,timeout=max(1,timeout))
        except FileNotFoundError as error: raise ProcessError(f"{argv[0]} is not installed") from error
        except subprocess.TimeoutExpired as error:
            process.kill(); process.wait()
            raise ProcessTimeout(f"command timed out after {timeout}s") from error
        except (PermissionError, OSError) as error: raise ProcessError(f"{argv[0]} execution failed: {error}") from error

        stdout_file.seek(0); stderr_file.seek(0)
        stdout_raw=stdout_file.read(max_output_bytes+1); stderr_raw=stderr_file.read(max_output_bytes+1)
        truncated=len(stdout_raw)>max_output_bytes or len(stderr_raw)>max_output_bytes
        return ProcessResult(tuple(argv),process.returncode,stdout_raw[:max_output_bytes].decode(errors="replace"),stderr_raw[:max_output_bytes].decode(errors="replace"),truncated)
