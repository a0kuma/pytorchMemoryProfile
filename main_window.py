import json
import pickle
import shlex
import subprocess

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QFileDialog,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QTableView,
    QPlainTextEdit,
    QLineEdit,
    QPushButton,
    QLabel,
    QComboBox,
    QMessageBox,
    QHeaderView,
)

from utils import (
    _NO_SSH_HOST,
    parse_ssh_config,
    get_user_frames,
    collect_views,
)
from models import DictTableModel, DictFilterProxyModel


class MainWindow(QMainWindow):
    def __init__(self, pickle_path=None):
        super().__init__()
        self.setWindowTitle("Pickle Trace Viewer")
        self.resize(1400, 800)

        self.data = None
        self.views = {}

        # SSH config ----------------------------------------------------------
        self.ssh_hosts = parse_ssh_config()  # { alias: {User: ..., ...} }
        self._ssh_hostname: str = ""          # HostName of currently selected SSH host
        self._source_cache: dict = {}         # { (filepath, lineno): source_line_str }

        self.model = DictTableModel()
        self.proxy = DictFilterProxyModel()
        self.proxy.setSourceModel(self.model)

        self._build_ui()
        self._populate_ssh_combo()

        if pickle_path:
            self.load_pickle(pickle_path)

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        main_layout = QVBoxLayout(root)

        # top bar — row 1: open / view / search
        top = QHBoxLayout()

        self.open_btn = QPushButton("Open pickle")
        self.open_btn.clicked.connect(self.open_pickle_dialog)
        top.addWidget(self.open_btn)

        top.addWidget(QLabel("View:"))
        self.view_combo = QComboBox()
        self.view_combo.currentIndexChanged.connect(self.change_view)
        top.addWidget(self.view_combo, 1)

        top.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "Filter rows... e.g. alloc, 133564859416576, 0x7979fe000000, b'7979fe000000_0'"
        )
        self.search_edit.textChanged.connect(self.on_search_changed)
        top.addWidget(self.search_edit, 2)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.search_edit.clear)
        top.addWidget(self.clear_btn)

        self.count_label = QLabel("0 rows")
        top.addWidget(self.count_label)

        main_layout.addLayout(top)

        # top bar — row 2: SSH host + frame-user filter
        ssh_bar = QHBoxLayout()

        ssh_bar.addWidget(QLabel("SSH Host:"))
        self.ssh_combo = QComboBox()
        self.ssh_combo.setMinimumWidth(160)
        self.ssh_combo.setToolTip(
            "Select a host from ~/.ssh/config to set the frame-user filter automatically"
        )
        self.ssh_combo.currentIndexChanged.connect(self._on_ssh_host_changed)
        ssh_bar.addWidget(self.ssh_combo)

        ssh_bar.addWidget(QLabel("Frame user filter:"))
        self.frame_user_edit = QLineEdit()
        self.frame_user_edit.setPlaceholderText(
            "Username to highlight in frames (e.g. andy)"
        )
        self.frame_user_edit.setToolTip(
            "Only Python frames whose path contains this username are shown in "
            "'User Code Frames'. Auto-set from the SSH host's User field."
        )
        self.frame_user_edit.textChanged.connect(self.show_current_row_details)
        ssh_bar.addWidget(self.frame_user_edit, 1)

        ssh_bar.addStretch()
        main_layout.addLayout(ssh_bar)

        # main splitter
        splitter = QSplitter()

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.verticalHeader().setVisible(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.clicked.connect(self.show_current_row_details)
        self.table.selectionModel().selectionChanged.connect(self.show_current_row_details)

        splitter.addWidget(self.table)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        splitter.addWidget(self.details)

        splitter.setSizes([950, 450])
        main_layout.addWidget(splitter)

    def _populate_ssh_combo(self):
        """Fill the SSH host combo box from the parsed ~/.ssh/config."""
        self.ssh_combo.blockSignals(True)
        self.ssh_combo.clear()
        self.ssh_combo.addItem(_NO_SSH_HOST)
        for alias in sorted(self.ssh_hosts.keys()):
            if alias == "*":
                continue  # skip wildcard catch-all
            self.ssh_combo.addItem(alias)
        self.ssh_combo.blockSignals(False)
        # Pre-select the first real host if any
        if self.ssh_combo.count() > 1:
            self.ssh_combo.setCurrentIndex(1)
        else:
            self.ssh_combo.setCurrentIndex(0)

    def _on_ssh_host_changed(self, _index):
        """When the SSH host changes, update the frame-user filter and hostname."""
        alias = self.ssh_combo.currentText()
        self._source_cache.clear()
        if alias == _NO_SSH_HOST:
            self.frame_user_edit.clear()
            self._ssh_hostname = ""
            return
        host_cfg = self.ssh_hosts.get(alias, {})
        user = host_cfg.get("user", "")
        self._ssh_hostname = host_cfg.get("hostname", "")
        self.frame_user_edit.setText(user)

    def open_pickle_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open pickle file",
            "",
            "Pickle files (*.pkl *.pickle *.pt *.bin);;All files (*)",
        )
        if path:
            self.load_pickle(path)

    def load_pickle(self, path):
        try:
            with open(path, "rb") as f:
                self.data = pickle.load(f)

            self.views = collect_views(self.data)

            if not self.views:
                QMessageBox.warning(
                    self,
                    "No table-like data found",
                    "Could not find any list[dict] or nested device_traces list[dict] data in this pickle.",
                )
                return

            self.view_combo.blockSignals(True)
            self.view_combo.clear()
            for name in self.views.keys():
                self.view_combo.addItem(name)
            self.view_combo.blockSignals(False)

            # Prefer device_traces[0] if present, else first view
            default_index = 0
            for i in range(self.view_combo.count()):
                if self.view_combo.itemText(i) == "device_traces[0]":
                    default_index = i
                    break

            self.view_combo.setCurrentIndex(default_index)
            self.change_view()

            self.statusBar().showMessage(f"Loaded: {path}")

        except Exception as e:
            QMessageBox.critical(self, "Load error", f"Failed to load pickle:\n{e}")

    def change_view(self):
        name = self.view_combo.currentText()
        rows = self.views.get(name, [])
        self.model.set_rows(rows, view_name=name)
        self.proxy.invalidate()
        self.update_count_label()

        if rows:
            self.table.resizeColumnsToContents()
            self.table.selectRow(0)
            self.show_current_row_details()
        else:
            self.details.clear()

    def on_search_changed(self, text):
        self.proxy.set_search_text(text)
        self.update_count_label()
        if self.proxy.rowCount() > 0:
            self.table.selectRow(0)
            self.show_current_row_details()
        else:
            self.details.clear()

    def update_count_label(self):
        total = self.model.rowCount()
        shown = self.proxy.rowCount()
        if shown == total:
            self.count_label.setText(f"{shown} rows")
        else:
            self.count_label.setText(f"{shown}/{total} rows")

    def _fetch_source_lines_via_ssh(self, user_frames: list) -> dict:
        """
        SSH into the currently selected host and fetch the actual source line for
        each frame in *user_frames*.

        Returns a dict ``{(filename, lineno): source_line_str}``.
        Frames whose lines cannot be fetched are simply absent from the result.
        """
        username = self.frame_user_edit.text().strip()
        hostname = self._ssh_hostname
        if not username or not hostname:
            return {}

        # Group needed (filename, lineno) pairs by file, skipping cached ones
        by_file: dict[str, set[int]] = {}
        for fr in user_frames:
            fn = fr.get("filename", "")
            ln = fr.get("line", 0)
            if fn and ln > 0 and (fn, ln) not in self._source_cache:
                by_file.setdefault(fn, set()).add(ln)

        for filepath, linenos in by_file.items():
            # Build an awk program that prints "LINENO:content" for each wanted line.
            # awk_parts contains only integer literals and fixed punctuation — no
            # user-supplied strings — so there is no shell/awk injection risk.
            # filepath is guarded by shlex.quote().
            awk_parts = " ".join(
                f'NR=={ln}{{print "{ln}:" $0}}' for ln in sorted(linenos)
            )
            remote_cmd = f"awk '{awk_parts}' {shlex.quote(filepath)}"
            try:
                proc = subprocess.run(
                    ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                     f"{username}@{hostname}", remote_cmd],
                    capture_output=True, text=True, timeout=15,
                )
                if proc.returncode == 0:
                    for output_line in proc.stdout.splitlines():
                        colon_idx = output_line.find(":")
                        if colon_idx > 0:
                            try:
                                ln = int(output_line[:colon_idx])
                                content = output_line[colon_idx + 1:]
                                self._source_cache[(filepath, ln)] = content
                            except ValueError:
                                pass
            except Exception:
                pass

        return {
            key: self._source_cache[key]
            for fr in user_frames
            for key in [(fr.get("filename", ""), fr.get("line", 0))]
            if key in self._source_cache
        }

    def show_current_row_details(self, *args):
        index = self.table.currentIndex()
        if not index.isValid():
            self.details.clear()
            return

        src_index = self.proxy.mapToSource(index)
        row = self.model.row_dict(src_index.row())

        lines = []

        # --- User Code Frames section ----------------------------------------
        frames = row.get("frames")
        username = self.frame_user_edit.text().strip()
        if frames and isinstance(frames, list):
            user_frames = get_user_frames(frames, username)
            if user_frames:
                ssh_alias = self.ssh_combo.currentText()
                if ssh_alias != _NO_SSH_HOST:
                    header = f"=== User Code Frames  [{ssh_alias} / {username}] ==="
                else:
                    header = f"=== User Code Frames  [{username}] ==="
                lines.append(header)
                source_lines = self._fetch_source_lines_via_ssh(user_frames)
                for i, fr in enumerate(user_frames, 1):
                    fn = fr.get("filename", "?")
                    ln = fr.get("line", 0)
                    name = fr.get("name", "")
                    lines.append(f"  [{i}] {fn}:{ln}  —  {name}")
                    src = source_lines.get((fn, ln))
                    if src is not None:
                        lines.append(f"       |  {src}")
                lines.append("")
            elif username:
                lines.append(f"=== User Code Frames  (no match for '{username}') ===")
                lines.append("")

        # --- Full row data ---------------------------------------------------
        lines.append("=== Full Row Data ===")
        lines.append(json.dumps(row, indent=2, ensure_ascii=False, default=str))

        self.details.setPlainText("\n".join(lines))
