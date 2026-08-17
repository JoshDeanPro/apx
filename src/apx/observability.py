# SPDX-License-Identifier: MIT
"""Minimal human/JSON logging configuration; payloads are metadata-only by design."""
from __future__ import annotations

import json,logging,sys
from datetime import datetime,timezone


class JSONFormatter(logging.Formatter):
    def format(self,record: logging.LogRecord)->str:
        value={"timestamp":datetime.now(timezone.utc).isoformat(),"level":record.levelname.lower(),"message":record.getMessage()}
        for key in ("event","request_id","receipt_id","actor","action","provider","status","duration_ms"):
            item=getattr(record,key,None)
            if item is not None: value[key]=item
        return json.dumps(value,separators=(",",":"),default=str)


def configure_logging(*,json_output: bool=False,level: int=logging.INFO)->logging.Logger:
    logger=logging.getLogger("apx"); logger.handlers.clear(); handler=logging.StreamHandler(sys.stderr)
    handler.setFormatter(JSONFormatter() if json_output else logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(handler); logger.setLevel(level); logger.propagate=False; return logger


def event_log(name: str,source: str,correlation_id: str|None=None)->None:
    logging.getLogger("apx").info(name,extra={"event":name,"provider":source,"request_id":correlation_id})
