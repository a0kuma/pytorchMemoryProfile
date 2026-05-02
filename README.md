# PyTorch Memory Profiler

A desktop GUI application for inspecting PyTorch memory-snapshot pickle files.  
It combines a local **Flask REST API** with an embedded **Qt/WebEngine browser** so you can explore allocation traces, segment tables, and raw device events without leaving a single window.

---

## Features

- **Load pickle files** – open a `.pkl` snapshot by file path or via file-upload dialog
- **Table view** – browse `segments`, `device_traces[N]`, and other list-of-dict views extracted from the snapshot
- **Full-text search** – filter rows with a free-text query that matches field values, hex addresses, and `b'…'`-style byte strings
- **Pagination** – large traces are served 200 rows per page (configurable)
- **Row detail pane** – click any row to inspect the full record and its Python call-stack frames
- **User-code frame filter** – enter a username to highlight only the frames that belong to your project paths
- **SSH source fetching** – pull the exact source line for each stack frame from a remote GPU server over SSH
- **Integrated visualiser** – a second browser tab loads [pytorchMemoryViz](https://a0kuma.github.io/pytorchMemoryViz/) for timeline/graph views

---

## Requirements

| Dependency | Purpose |
|---|---|
| Python ≥ 3.10 | Runtime |
| [PySide6](https://pypi.org/project/PySide6/) | Qt desktop window |
| [PySide6-WebEngine](https://pypi.org/project/PySide6-WebEngine/) | Embedded browser *(optional but recommended)* |
| [Flask](https://pypi.org/project/Flask/) | Local REST API server |

> Without `PySide6-WebEngine` the app falls back to opening the two URLs in your system default browser.

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/a0kuma/pytorchMemoryProfile.git
cd pytorchMemoryProfile

# 2. Install dependencies
pip install flask PySide6 PySide6-WebEngine
```

### Conda (optional)

A reference environment name is listed in `DEFAULT_CONDA_ENV_LOCAL.txt`.  
Create a fresh environment and install the same packages:

```bash
conda create -n pytorch-mem-profiler python=3.11
conda activate pytorch-mem-profiler
pip install flask PySide6 PySide6-WebEngine
```

---

## Generating a memory snapshot

Use PyTorch's built-in memory recorder to capture a snapshot during training:

```python
import torch

torch.cuda.memory._record_memory_history(max_entries=100_000)

# ... your model training code ...

torch.cuda.memory._dump_snapshot("memory_snapshot.pkl")
torch.cuda.memory._record_memory_history(enabled=None)
```

---

## Usage

```bash
python index.py [--port PORT] [pickle_path]
```

| Argument | Default | Description |
|---|---|---|
| `--port PORT` | `32764` | TCP port for the local REST API |
| `pickle_path` | *(none)* | Optional `.pkl` file to load on startup |

### Examples

```bash
# Open the GUI with no file pre-loaded
python index.py

# Load a snapshot immediately on startup
python index.py memory_snapshot.pkl

# Use a custom port
python index.py --port 8080 memory_snapshot.pkl
```

### Windows

A convenience launcher is provided:

```bat
start.bat
```

### In-app workflow

1. Click **Open Pickle** to load a `.pkl` snapshot (or pass it as a command-line argument).
2. Select a **View** from the dropdown (`segments`, `device_traces[0]`, …).
3. Use the **Search** box to filter rows (supports hex addresses, action names, sizes, etc.).
4. Click any row to see full details and the raw call-stack frames in the right-hand pane.
5. Set **Frame user filter** to your username to highlight only your project's frames.
6. Select an **SSH Host** (parsed from `~/.ssh/config`) to automatically fetch source lines from a remote server.
7. Switch to the **browser_Viz** tab for the memory timeline visualiser.

---

## Project structure

```
pytorchMemoryProfile/
├── index.py          # Entry point – argument parsing, Flask thread, Qt window
├── api.py            # Flask REST API server (all /api/* endpoints)
├── main_window.py    # Qt MainWindow with embedded WebEngine tabs
├── models.py         # Qt table/filter models (DictTableModel, DictFilterProxyModel)
├── utils.py          # Pure-Python helpers (SSH config, search, pickle parsing)
├── frontend/
│   ├── index.html    # Single-page HTML shell
│   ├── app.js        # Frontend JS – API calls, table rendering, pagination
│   └── style.css     # Styles
├── API.md            # Full REST API reference
└── start.bat         # Windows launcher
```

---

## REST API

The embedded frontend communicates with a local REST API bound to `127.0.0.1` only.  
See **[API.md](API.md)** for the complete endpoint reference.

Key endpoints:

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Server liveness check |
| `POST` | `/api/pickle` | Load pickle by local path |
| `POST` | `/api/pickle/upload` | Upload pickle via multipart form |
| `GET` | `/api/views` | List available view names |
| `GET` | `/api/view` | Paginated + filtered rows for a view |
| `GET` | `/api/row` | Full details for a single row |
| `GET` | `/api/ssh/hosts` | SSH host aliases from `~/.ssh/config` |
| `POST` | `/api/ssh/source` | Fetch source lines from remote host via SSH |
| `DELETE` | `/api/cache` | Clear the SSH source-line cache |

---

## Related projects

- **[pytorchMemoryViz](https://a0kuma.github.io/pytorchMemoryViz/)** – web-based memory timeline visualiser (loaded in the second browser tab)
- **[PyTorch Memory Profiling docs](https://pytorch.org/docs/stable/torch_cuda_memory.html)** – official guide for `torch.cuda.memory._dump_snapshot`
