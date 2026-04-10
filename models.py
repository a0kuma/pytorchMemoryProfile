from PySide6.QtCore import Qt, QAbstractTableModel, QSortFilterProxyModel, QModelIndex
from PySide6.QtGui import QColor

from utils import safe_repr, normalize_text, build_search_blob


class DictTableModel(QAbstractTableModel):
    _HIGHLIGHT_COLOR = QColor(255, 255, 0)  # yellow

    def __init__(self, rows=None, view_name=""):
        super().__init__()
        self._rows = rows or []
        self.view_name = view_name
        self._columns = self._build_columns(self._rows)
        self._highlighted_addrs: set = set()

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

    def set_highlighted_addrs(self, addrs: set):
        self._highlighted_addrs = addrs
        if self._rows:
            top_left = self.index(0, 0)
            bottom_right = self.index(len(self._rows) - 1, len(self._columns) - 1)
            self.dataChanged.emit(top_left, bottom_right, [Qt.BackgroundRole])

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

        if role == Qt.BackgroundRole:
            if self._highlighted_addrs:
                addr = row.get("addr")
                if addr is not None and addr in self._highlighted_addrs:
                    return self._HIGHLIGHT_COLOR
            return None

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
