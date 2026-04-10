import sys
import json
import pickle
from pathlib import Path

from PySide6.QtCore import Qt, QAbstractTableModel, QSortFilterProxyModel, QModelIndex
from PySide6.QtWidgets import (
    QApplication,
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


class DictTableModel(QAbstractTableModel):
    def __init__(self, rows=None, view_name=""):
        super().__init__()
        self._rows = rows or []
        self.view_name = view_name
        self._columns = self._build_columns(self._rows)

    @staticmethod
    def _build_columns(rows):
        if not rows:
            return []

        columns = []
        seen = set()

        # keep first row key order first
        for k in rows[0].keys():
            columns.append(k)
            seen.add(k)

        # add any extra keys from later rows
        for row in rows[1:]:
            for k in row.keys():
                if k not in seen:
                    columns.append(k)
                    seen.add(k)

        return columns

    def set_rows(self, rows, view_name=""):
        self.beginResetModel()
        self._rows = rows or []
        self.view_name = view_name
        self._columns = self._build_columns(self._rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            if 0 <= section < len(self._columns):
                return self._columns[section]
        else:
            return str(section)
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        row = self._rows[index.row()]
        col_name = self._columns[index.column()]
        value = row.get(col_name, "")

        if role == Qt.DisplayRole:
            if isinstance(value, int):
                return str(value)
            return safe_repr(value)

        if role == Qt.TextAlignmentRole:
            if isinstance(value, int):
                return Qt.AlignRight | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter

        return None

    def row_dict(self, row_index):
        if 0 <= row_index < len(self._rows):
            return self._rows[row_index]
        return {}

    def columns(self):
        return self._columns


class DictFilterProxyModel(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self._needle = ""

    def set_search_text(self, text):
        self._needle = normalize_text(text)
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if not self._needle:
            return True

        model = self.sourceModel()
        row = model.row_dict(source_row)

        # try to infer device index from view name like device_traces[0]
        fallback_device = None
        vn = getattr(model, "view_name", "")
        if "[" in vn and vn.endswith("]"):
            try:
                fallback_device = vn.split("[", 1)[1][:-1]
            except Exception:
                fallback_device = None

        blob = build_search_blob(row, fallback_device=fallback_device)
        return self._needle in blob


class MainWindow(QMainWindow):
    def __init__(self, pickle_path=None):
        super().__init__()
        self.setWindowTitle("Pickle Trace Viewer")
        self.resize(1400, 800)

        self.data = None
        self.views = {}

        self.model = DictTableModel()
        self.proxy = DictFilterProxyModel()
        self.proxy.setSourceModel(self.model)

        self._build_ui()

        if pickle_path:
            self.load_pickle(pickle_path)

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        main_layout = QVBoxLayout(root)

        # top bar
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

    def show_current_row_details(self, *args):
        index = self.table.currentIndex()
        if not index.isValid():
            self.details.clear()
            return

        src_index = self.proxy.mapToSource(index)
        row = self.model.row_dict(src_index.row())

        pretty = json.dumps(row, indent=2, ensure_ascii=False, default=str)
        self.details.setPlainText(pretty)


def main():
    app = QApplication(sys.argv)

    pickle_path = None
    if len(sys.argv) > 1:
        pickle_path = sys.argv[1]

    win = MainWindow(pickle_path=pickle_path)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
