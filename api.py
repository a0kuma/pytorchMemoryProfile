"""
PyTorch Memory Profiler – REST API server
==========================================

Exposes all Python logic (pickle loading, view extraction, SSH source fetching)
over HTTP/JSON so that the HTML/JS/CSS frontend can consume it.

Binds to 127.0.0.1 on the port supplied to ``run_server()`` (default 32764).

Endpoints summary
-----------------
GET  /                              Serve frontend HTML shell
GET  /api/health                    Server health check
POST /api/pickle                    Load pickle by local filesystem path
POST /api/pickle/upload             Upload pickle file (multipart/form-data)
GET  /api/views                     List available view names
GET  /api/view                      Paginated + filtered rows for a view
GET  /api/row                       Full details for one row
GET  /api/ssh/hosts                 SSH host aliases from ~/.ssh/config
POST /api/ssh/source                Fetch remote source lines via SSH
DELETE /api/cache                   Clear the SSH source-line cache
"""

from __future__ import annotations

import json
import os
import pickle
import shlex
import subprocess

from flask import Flask, request, send_from_directory

from utils import (
    build_search_blob,
    collect_views,
    get_user_frames,
    normalize_text,
    parse_ssh_config,
    safe_repr,
)

# ---------------------------------------------------------------------------
# Flask application
# ---------------------------------------------------------------------------

_FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")

app = Flask(__name__, static_folder=_FRONTEND_DIR, static_url_path="")

# ---------------------------------------------------------------------------
# In-process state  (single-user / embedded-browser use-case)
# ---------------------------------------------------------------------------

_state: dict = {
    "data": None,
    "views": {},
    "source_cache": {},   # {(filepath, lineno): source_line_str}
    "ssh_hosts": {},
    "pickle_path": None,
}


def _init_state() -> None:
    """Populate ssh_hosts from ~/.ssh/config (called once at startup)."""
    _state["ssh_hosts"] = parse_ssh_config()


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def _make_serializable(obj):
    """Recursively convert *obj* to a JSON-serialisable structure."""
    if isinstance(obj, dict):
        return {str(k): _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(i) for i in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    return safe_repr(obj)


def _ok(**kwargs):
    payload = json.dumps(kwargs, default=str)
    return app.response_class(payload, mimetype="application/json")


def _err(msg: str, status: int = 400):
    # Error messages are sent only to 127.0.0.1 (the local operator).
    # Exposing the message string is intentional – it aids debugging.
    payload = json.dumps({"error": msg})
    return app.response_class(payload, mimetype="application/json", status=status)


# ---------------------------------------------------------------------------
# Routes – static frontend
# ---------------------------------------------------------------------------

@app.route("/")
def serve_index():
    return send_from_directory(_FRONTEND_DIR, "index.html")


# ---------------------------------------------------------------------------
# Routes – health
# ---------------------------------------------------------------------------

@app.route("/api/health", methods=["GET"])
def api_health():
    """Return ``{"status": "ok"}`` – useful to confirm the server is up."""
    return _ok(status="ok", version="1.0")


# ---------------------------------------------------------------------------
# Routes – pickle loading
# ---------------------------------------------------------------------------

@app.route("/api/pickle", methods=["POST"])
def api_load_pickle_path():
    """
    Load a pickle file by its local filesystem path.

    Request body (JSON)
    -------------------
    path : str  – absolute or relative path to the pickle file

    Response (JSON)
    ---------------
    views    : list[str]  – available view names
    path     : str        – resolved path
    count    : int        – number of views found
    """
    body = request.get_json(force=True, silent=True) or {}
    path = body.get("path", "").strip()
    if not path:
        return _err("'path' field is required")
    # NOTE: This server binds to 127.0.0.1 only and is used exclusively by the
    # local operator to open their own files.  Reading an arbitrary local path
    # and deserialising pickle data is the intentional, core purpose of the tool.
    try:
        with open(path, "rb") as fh:  # nosec B301
            _state["data"] = pickle.load(fh)  # nosec B301
        _state["views"] = collect_views(_state["data"])
        _state["pickle_path"] = path
        _state["source_cache"] = {}
        views = list(_state["views"].keys())
        return _ok(views=views, path=path, count=len(views))
    except FileNotFoundError:
        return _err(f"File not found: {path}", 404)
    except Exception as exc:
        return _err(str(exc))


@app.route("/api/pickle/upload", methods=["POST"])
def api_upload_pickle():
    """
    Upload a pickle file via multipart/form-data.

    Form field
    ----------
    file : file  – the pickle file to upload

    Response (JSON)
    ---------------
    views    : list[str]  – available view names
    filename : str        – uploaded filename
    count    : int        – number of views found
    """
    if "file" not in request.files:
        return _err("multipart field 'file' is required")
    upload = request.files["file"]
    # NOTE: Deserialising pickle data uploaded by the local operator is the
    # intentional purpose of this tool.  The server is 127.0.0.1-only.
    try:
        _state["data"] = pickle.load(upload.stream)  # nosec B301
        _state["views"] = collect_views(_state["data"])
        _state["pickle_path"] = upload.filename
        _state["source_cache"] = {}
        views = list(_state["views"].keys())
        return _ok(views=views, filename=upload.filename, count=len(views))
    except Exception as exc:
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Routes – views
# ---------------------------------------------------------------------------

@app.route("/api/views", methods=["GET"])
def api_list_views():
    """
    List available view names for the currently loaded pickle.

    Response (JSON)
    ---------------
    views : list[str]
    """
    return _ok(views=list(_state["views"].keys()))


@app.route("/api/view", methods=["GET"])
def api_get_view():
    """
    Return paginated, optionally-filtered rows for a view.

    Query parameters
    ----------------
    name     : str  – view name (required)
    search   : str  – free-text search expression (optional)
    page     : int  – zero-based page index (default 0)
    per_page : int  – rows per page, 1–1000 (default 200)

    Response (JSON)
    ---------------
    view     : str        – view name
    total    : int        – total matching rows (after filtering)
    page     : int        – current page
    per_page : int        – rows per page used
    columns  : list[str]  – column names derived from the first 100 rows
    rows     : list[dict] – serialised row objects for this page
    """
    name = request.args.get("name", "").strip()
    if not name:
        return _err("'name' query parameter is required")

    rows = _state["views"].get(name)
    if rows is None:
        return _err(f"View '{name}' not found", 404)

    # --- filter ---
    search = request.args.get("search", "").strip()
    if search:
        needle = normalize_text(search)
        fallback_device = _device_from_view_name(name)
        filtered = [
            r for r in rows
            if needle in build_search_blob(r, fallback_device=fallback_device)
        ]
    else:
        filtered = rows

    total = len(filtered)

    # --- paginate ---
    try:
        page = max(0, int(request.args.get("page", 0)))
    except (ValueError, TypeError):
        page = 0
    try:
        per_page = min(1000, max(1, int(request.args.get("per_page", 200))))
    except (ValueError, TypeError):
        per_page = 200

    start = page * per_page
    page_rows = filtered[start: start + per_page]

    # --- column order (from first 100 filtered rows) ---
    columns: list[str] = []
    seen: set[str] = set()
    for row in filtered[:100]:
        for k in row.keys():
            sk = str(k)
            if sk not in seen:
                columns.append(sk)
                seen.add(sk)

    return _ok(
        view=name,
        total=total,
        page=page,
        per_page=per_page,
        columns=columns,
        rows=_make_serializable(page_rows),
    )


@app.route("/api/row", methods=["GET"])
def api_get_row():
    """
    Return full details for a single row, including user frames and SSH source lines.

    Query parameters
    ----------------
    view     : str  – view name (required)
    index    : int  – zero-based row index within the filtered result set (required)
    search   : str  – must match the search used to produce the index (optional)
    username : str  – filters stack frames to user code (optional)
    ssh_host : str  – host alias for SSH source-line fetching (optional)

    Response (JSON)
    ---------------
    row          : dict            – full serialised row
    user_frames  : list[dict]      – stack frames matching ``username``
    source_lines : dict[str, str]  – ``"filename:lineno"`` → source text
    """
    view_name = request.args.get("view", "").strip()
    if not view_name:
        return _err("'view' query parameter is required")

    rows = _state["views"].get(view_name)
    if rows is None:
        return _err(f"View '{view_name}' not found", 404)

    # Re-apply filter so the index is consistent with /api/view
    search = request.args.get("search", "").strip()
    if search:
        needle = normalize_text(search)
        fallback_device = _device_from_view_name(view_name)
        rows = [
            r for r in rows
            if needle in build_search_blob(r, fallback_device=fallback_device)
        ]

    try:
        idx = int(request.args.get("index", 0))
    except (ValueError, TypeError):
        return _err("'index' must be an integer")

    if idx < 0 or idx >= len(rows):
        return _err(f"Index {idx} out of range (0–{len(rows) - 1})", 404)

    row = rows[idx]
    username = request.args.get("username", "").strip()
    ssh_host = request.args.get("ssh_host", "").strip()

    user_frames: list = []
    source_lines: dict = {}

    frames = row.get("frames")
    if frames and isinstance(frames, list) and username:
        user_frames = get_user_frames(frames, username)
        if user_frames and ssh_host:
            host_cfg = _state["ssh_hosts"].get(ssh_host, {})
            hostname = host_cfg.get("hostname", "")
            if hostname:
                cache = _fetch_source_lines_ssh(user_frames, username, hostname)
                source_lines = {
                    f"{k[0]}:{k[1]}": v for k, v in cache.items()
                }

    return _ok(
        row=_make_serializable(row),
        user_frames=_make_serializable(user_frames),
        source_lines=source_lines,
    )


# ---------------------------------------------------------------------------
# Routes – SSH
# ---------------------------------------------------------------------------

@app.route("/api/ssh/hosts", methods=["GET"])
def api_ssh_hosts():
    """
    List SSH host aliases parsed from ``~/.ssh/config``.

    Response (JSON)
    ---------------
    hosts : dict[str, dict]  – ``{alias: {user, hostname, …}}``
    """
    hosts = {k: v for k, v in _state["ssh_hosts"].items() if k != "*"}
    return _ok(hosts=hosts)


@app.route("/api/ssh/source", methods=["POST"])
def api_ssh_source():
    """
    Fetch source lines from a remote host via SSH.

    Request body (JSON)
    -------------------
    frames   : list[dict]  – frame objects with ``filename`` and ``line`` keys
    username : str         – remote username
    ssh_host : str         – host alias from ``~/.ssh/config``

    Response (JSON)
    ---------------
    source_lines : dict[str, str]  – ``"filename:lineno"`` → source text
    """
    body = request.get_json(force=True, silent=True) or {}
    user_frames = body.get("frames", [])
    username = body.get("username", "").strip()
    ssh_host = body.get("ssh_host", "").strip()

    if not username or not ssh_host:
        return _err("'username' and 'ssh_host' are required")

    host_cfg = _state["ssh_hosts"].get(ssh_host, {})
    hostname = host_cfg.get("hostname", "")
    if not hostname:
        return _err(f"SSH host '{ssh_host}' has no HostName configured", 404)

    cache = _fetch_source_lines_ssh(user_frames, username, hostname)
    source_lines = {f"{k[0]}:{k[1]}": v for k, v in cache.items()}
    return _ok(source_lines=source_lines)


@app.route("/api/cache", methods=["DELETE"])
def api_clear_cache():
    """
    Clear the in-memory SSH source-line cache.

    Response (JSON)
    ---------------
    cleared : true
    """
    _state["source_cache"].clear()
    return _ok(cleared=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _device_from_view_name(name: str):
    """Extract device index string from view names like ``device_traces[0]``."""
    if "[" in name and name.endswith("]"):
        try:
            return name.split("[", 1)[1][:-1]
        except Exception:
            pass
    return None


def _fetch_source_lines_ssh(
    user_frames: list, username: str, hostname: str
) -> dict:
    """
    SSH into *hostname* as *username* and fetch the source line for each frame.

    Returns ``{(filepath, lineno): source_line_str}`` for successfully fetched
    lines.  Results are cached in ``_state["source_cache"]``.
    """
    by_file: dict[str, set] = {}
    for fr in user_frames:
        fn = fr.get("filename", "")
        ln = fr.get("line", 0)
        if fn and ln > 0 and (fn, ln) not in _state["source_cache"]:
            by_file.setdefault(fn, set()).add(ln)

    for filepath, linenos in by_file.items():
        # awk program: prints "LINENO:content" for each wanted line.
        # Only integer literals and fixed punctuation are interpolated —
        # filepath is protected by shlex.quote() — no injection risk.
        awk_parts = " ".join(
            f'NR=={ln}{{print "{ln}:" $0}}' for ln in sorted(linenos)
        )
        remote_cmd = f"awk '{awk_parts}' {shlex.quote(filepath)}"
        try:
            proc = subprocess.run(
                [
                    "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                    f"{username}@{hostname}", remote_cmd,
                ],
                capture_output=True, text=True, timeout=15,
            )
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    colon_idx = line.find(":")
                    if colon_idx > 0:
                        try:
                            ln = int(line[:colon_idx])
                            content = line[colon_idx + 1:]
                            _state["source_cache"][(filepath, ln)] = content
                        except ValueError:
                            pass
        except Exception:
            pass

    return {
        key: _state["source_cache"][key]
        for fr in user_frames
        for key in [(fr.get("filename", ""), fr.get("line", 0))]
        if key in _state["source_cache"]
    }


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

def run_server(port: int = 32764) -> None:
    """Start the Flask development server (blocking call)."""
    _init_state()
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
