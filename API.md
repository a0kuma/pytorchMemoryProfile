# PyTorch Memory Profiler – REST API Reference

The application exposes a local HTTP/JSON REST API that the embedded browser
frontend consumes.  It is **bound to `127.0.0.1` only** (localhost) and never
accessible from the network.

## Starting the server

```
python index.py [--port PORT] [pickle_path]
```

| Argument | Default | Description |
|---|---|---|
| `--port PORT` | `32764` | TCP port the API listens on |
| `pickle_path` | *(none)* | Optional pickle file to load on startup |

The server URL is always `http://127.0.0.1:<PORT>`.  
The frontend HTML is served at `GET /` (same origin as the API).

---

## Common conventions

* All request bodies are **JSON** (`Content-Type: application/json`) unless noted.
* All successful responses are **JSON** with HTTP `200`.
* Error responses are JSON `{"error": "<message>"}` with an appropriate 4xx status.
* Non-JSON-serialisable values in pickle data (numpy arrays, bytes, etc.) are
  converted to their string representation.

---

## Endpoints

### `GET /api/health`

Returns a simple liveness signal.

**Response**

```json
{ "status": "ok", "version": "1.0" }
```

---

### `POST /api/pickle`

Load a pickle file from a local filesystem path.

**Request body**

```json
{ "path": "/absolute/or/relative/path/to/file.pkl" }
```

**Response**

```json
{
  "views": ["segments", "device_traces[0]", "device_traces[1]"],
  "path": "/absolute/path/to/file.pkl",
  "count": 3
}
```

| Field | Type | Description |
|---|---|---|
| `views` | `string[]` | Names of table-like views extracted from the pickle |
| `path` | `string` | Resolved path that was loaded |
| `count` | `int` | Number of views found |

**Error codes**

| Status | Meaning |
|---|---|
| `400` | `path` field missing or pickle failed to parse |
| `404` | File not found at the given path |

---

### `POST /api/pickle/upload`

Upload a pickle file as multipart form data.

**Request** — `multipart/form-data`, field name `file`

**Response**

```json
{
  "views": ["segments", "device_traces[0]"],
  "filename": "memory_snapshot.pkl",
  "count": 2
}
```

**Error codes**

| Status | Meaning |
|---|---|
| `400` | `file` field missing or pickle failed to parse |

---

### `GET /api/views`

List the available view names for the currently loaded pickle.

**Response**

```json
{ "views": ["segments", "device_traces[0]", "device_traces[1]"] }
```

Returns `{"views": []}` when no pickle is loaded.

---

### `GET /api/view`

Return paginated, optionally-filtered rows for a named view.

**Query parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | `string` | *(required)* | View name (e.g. `device_traces[0]`) |
| `search` | `string` | `""` | Free-text filter expression |
| `page` | `int` | `0` | Zero-based page index |
| `per_page` | `int` | `200` | Rows per page (1 – 1 000) |

The search expression is matched against a normalised blob built from every
field in each row, including hex address variants and `b'…'`-style byte-string
representations (identical logic to the original Qt filter model).

**Response**

```json
{
  "view":     "device_traces[0]",
  "total":    15420,
  "page":     0,
  "per_page": 200,
  "columns":  ["action", "addr", "size", "stream", "frames", "device"],
  "rows": [
    { "action": "alloc", "addr": 140123456789504, "size": 1048576, "stream": 0, "frames": [...], "device": 0 },
    ...
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `total` | `int` | Total matching rows after filtering |
| `columns` | `string[]` | Column names (derived from first 100 filtered rows) |
| `rows` | `object[]` | Serialised row objects for the current page |

**Error codes**

| Status | Meaning |
|---|---|
| `400` | `name` parameter missing |
| `404` | View not found |

---

### `GET /api/row`

Return full details for a single row, including user stack frames and
optionally SSH-fetched source lines.

**Query parameters**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `view` | `string` | *(required)* | View name |
| `index` | `int` | *(required)* | Zero-based row index in the **filtered** result set |
| `search` | `string` | `""` | Must match the search used when fetching the page |
| `username` | `string` | `""` | Filters `frames` to paths containing this username |
| `ssh_host` | `string` | `""` | SSH host alias for source-line fetching |

> **Note:** `index` is absolute within the filtered result set (not the page).
> Pass the value from `rows[i]`'s position: `page * per_page + pageIndex`.

**Response**

```json
{
  "row": {
    "action": "alloc",
    "addr": 140123456789504,
    "size": 1048576,
    "frames": [
      { "filename": "/home/andy/project/train.py", "line": 42, "name": "forward" },
      ...
    ]
  },
  "user_frames": [
    { "filename": "/home/andy/project/train.py", "line": 42, "name": "forward" }
  ],
  "source_lines": {
    "/home/andy/project/train.py:42": "    out = self.conv(x)"
  }
}
```

| Field | Type | Description |
|---|---|---|
| `row` | `object` | Full serialised row |
| `user_frames` | `object[]` | Frames whose path contains `username` |
| `source_lines` | `object` | `"filename:lineno"` → source text (populated only when `ssh_host` and `username` are set) |

**Error codes**

| Status | Meaning |
|---|---|
| `400` | `view` missing or `index` not an integer |
| `404` | View or row index not found |

---

### `GET /api/ssh/hosts`

List SSH host aliases parsed from `~/.ssh/config`.

**Response**

```json
{
  "hosts": {
    "gpu-server": { "user": "andy", "hostname": "10.0.0.42", "port": "22" },
    "devbox":     { "user": "alice", "hostname": "devbox.internal" }
  }
}
```

Returns `{"hosts": {}}` when `~/.ssh/config` is absent or unreadable.

---

### `POST /api/ssh/source`

Fetch source lines from a remote host via SSH.
Results are cached for the lifetime of the server process.

**Request body**

```json
{
  "frames":   [{ "filename": "/home/andy/project/train.py", "line": 42 }],
  "username": "andy",
  "ssh_host": "gpu-server"
}
```

**Response**

```json
{
  "source_lines": {
    "/home/andy/project/train.py:42": "    out = self.conv(x)"
  }
}
```

**Error codes**

| Status | Meaning |
|---|---|
| `400` | `username` or `ssh_host` missing |
| `404` | SSH host alias not found or has no `HostName` configured |

---

### `DELETE /api/cache`

Clear the in-memory SSH source-line cache (e.g. after changing SSH host).

**Response**

```json
{ "cleared": true }
```

---

## Data model – pickle views

`collect_views` (in `utils.py`) extracts the following shapes from a pickle:

| Pickle structure | View name |
|---|---|
| `{"segments": [dict, …]}` | `segments` |
| `{"device_traces": [[dict, …], [dict, …]]}` | `device_traces[0]`, `device_traces[1]`, … |
| Top-level `[dict, …]` | `root` |

---

## Installing dependencies

```bash
pip install flask PySide6
# For the embedded browser (optional but recommended):
pip install pyside6-webengine
```

When `pyside6-webengine` is not installed the app opens the URL in the
system default browser instead.
