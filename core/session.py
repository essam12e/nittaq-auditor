"""Session persistence (in-task memory: state, approvals, changes).

Sessions live under ``$NITTAQ_HOME/sessions`` (default ``./.nittaq``) with
0600 permissions. They never contain credentials: observations are redacted
before being written (core.discovery.observation.sanitize_observation).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ID = re.compile(r"^[a-z0-9-]{6,64}$")


def home() -> Path:
    return Path(os.environ.get("NITTAQ_HOME", ".nittaq")).resolve()


def sessions_dir() -> Path:
    d = home() / "sessions"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def new_session_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)


def session_path(session_id: str) -> Path:
    if not _ID.match(session_id):
        raise ValueError("invalid session id")
    return sessions_dir() / f"{session_id}.json"


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_session(session_id: str) -> dict[str, Any]:
    p = session_path(session_id)
    if not p.exists():
        raise FileNotFoundError(f"session {session_id} not found")
    return json.loads(p.read_text(encoding="utf-8"))


def save_session(data: dict[str, Any]) -> None:
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_json_atomic(session_path(data["id"]), data)


def save_observation(session_id: str, kind: str, obs: dict[str, Any]) -> str:
    d = sessions_dir() / session_id
    n = len(list(d.glob("*.json"))) if d.exists() else 0
    p = d / f"{n + 1:02d}-{kind}.json"
    write_json_atomic(p, obs)
    return str(p)
