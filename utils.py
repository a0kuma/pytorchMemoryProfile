import json
import os
import platform
import re
from pathlib import Path


_NO_SSH_HOST = "-- no filter --"


def get_ssh_config_path() -> Path:
    """Return the platform-appropriate path to ~/.ssh/config."""
    if platform.system() == "Windows":
        home_str = os.environ.get("USERPROFILE") or os.environ.get("HOMEPATH") or ""
        home = Path(home_str) if home_str else Path.home()
    else:
        home = Path.home()
    return home / ".ssh" / "config"


def parse_ssh_config() -> dict:
    """
    Parse ~/.ssh/config and return a dict::

        { host_alias: {"User": "...", "HostName": "...", ...}, ... }

    The special wildcard host ``*`` is included if present.
    Returns an empty dict when the file is missing or unreadable.
    """
    config_path = get_ssh_config_path()
    hosts: dict = {}
    if not config_path.is_file():
        return hosts
    try:
        with open(config_path, "r", encoding="utf-8", errors="replace") as fh:
            current_host: str | None = None
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                m = re.match(r"^(\S+)\s+(.*)", line)
                if not m:
                    continue
                key, value = m.group(1), m.group(2).strip()
                if key.lower() == "host":
                    current_host = value
                    hosts.setdefault(current_host, {})
                elif current_host is not None:
                    hosts[current_host][key.lower()] = value
    except OSError:
        pass
    return hosts


def get_user_frames(frames: list, username: str) -> list:
    """
    Return the subset of *frames* that are Python files whose path
    contains *username* as a directory component (e.g. ``/home/andy/...``).

    Both POSIX (``/username/``) and Windows (``\\username\\``) separators
    are matched.  Returns an empty list when *username* is blank.
    """
    if not frames or not username:
        return []
    needle_posix = f"/{username}/"
    needle_win = f"\\{username}\\"
    result = []
    for frame in frames:
        fn = frame.get("filename") or ""
        if fn.endswith(".py") and (needle_posix in fn or needle_win in fn):
            result.append(frame)
    return result


def safe_repr(value):
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            return repr(value)
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:
            return repr(value)
    return str(value)


def normalize_text(s: str) -> str:
    if s is None:
        return ""
    s = str(s).strip().lower()

    # support things like b'7978ce000000_0'
    if s.startswith("b'") or s.startswith('b"'):
        s = s[2:]

    s = s.strip("'\"")
    s = s.replace("0x", "")
    s = s.replace("_", "")
    s = s.replace(" ", "")
    return s


def int_like(v):
    try:
        return int(v)
    except Exception:
        return None


def build_search_blob(row: dict, fallback_device=None) -> str:
    parts = []

    for k, v in row.items():
        parts.append(str(k))
        parts.append(safe_repr(v))

        if k in ("addr", "address"):
            iv = int_like(v)
            if iv is not None:
                hx = format(iv, "x")
                parts.append(hx)
                parts.append("0x" + hx)

                dev = row.get("device", fallback_device)
                if dev is not None:
                    dev_str = str(dev)
                    parts.append(f"{hx}_{dev_str}")
                    parts.append(f"b'{hx}_{dev_str}'")
                    parts.append(f'b"{hx}_{dev_str}"')

    return normalize_text(" | ".join(parts))


def collect_views(obj):
    """
    Extract useful table-like lists from the pickle data.
    Works well for structures like:
      {
        "segments": [...],
        "device_traces": [[...], [...], ...],
        ...
      }
    """
    views = {}

    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, list):
                if value and all(isinstance(x, dict) for x in value):
                    views[key] = value
                elif value and all(isinstance(x, list) for x in value):
                    for i, sub in enumerate(value):
                        if sub and all(isinstance(x, dict) for x in sub):
                            views[f"{key}[{i}]"] = sub

    elif isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
        views["root"] = obj

    return views
