from PyQt5.QtCore import (
    QAbstractTableModel, Qt, QVariant,
    QSortFilterProxyModel, QRegExp, QModelIndex
)
from datetime import datetime
import re


class DataFrameModel(QAbstractTableModel):
    """Read-only Qt model backed by a pandas DataFrame."""

    def __init__(self, df):
        super().__init__()
        self._df = df

    def rowCount(self, parent=None):
        return 0 if self._df is None else int(self._df.shape[0])

    def columnCount(self, parent=None):
        return 0 if self._df is None else int(self._df.shape[1])

    def data(self, index, role=Qt.DisplayRole):
        if role != Qt.DisplayRole or not index.isValid():
            return QVariant()
        val = self._df.iat[index.row(), index.column()]
        return "" if val is None else str(val)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole or self._df is None:
            return QVariant()
        if orientation == Qt.Horizontal:
            return str(self._df.columns[section])
        return section + 1


# -------------------------------------------------------------------------
class ColumnFilterProxyModel(QSortFilterProxyModel):
    """
    Per-column filters with support for:
      - substring
      - regex (re:)
      - numeric compare (<, <=, >, >=, ==, !=)
      - numeric range (a..b)
      - date/time compare and range
    """

    _cmp_re = re.compile(r"^\s*(<=|>=|<|>|==|=|!=)\s*(.+?)\s*$")
    _num_rng_re = re.compile(r"^\s*(-?\d[\d,]*(?:\.\d+)?)\s*\.\.\s*(-?\d[\d,]*(?:\.\d+)?)\s*$")
    _any_rng_re = re.compile(r"^\s*(.+?)\s*\.\.\s*(.+?)\s*$")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filters = {}  # col_index -> parsed rule tuple
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        return self.sourceModel().headerData(section, orientation, role)

    # ---------------------------------------------------------------------

    def setColumnFilter(self, column, pattern):
        """Parse and store a filter expression for the given column."""
        if not pattern:
            self._filters.pop(column, None)
            self.invalidateFilter()
            return

        s = str(pattern).strip()
        if not s:
            self._filters.pop(column, None)
            self.invalidateFilter()
            return

        # Regex mode
        if s.lower().startswith("re:"):
            self._filters[column] = ("regex", s[3:])
            self.invalidateFilter()
            return

        # Force date parsing
        force_date = False
        if s.lower().startswith(("date:", "dt:")):
            force_date = True
            s = s.split(":", 1)[1].strip()

        # Comparison (<, <=, etc.)
        m = self._cmp_re.match(s)
        if m:
            op, rhs = m.groups()
            if force_date or self._looks_like_date(rhs):
                dt = self._parse_datetime(rhs)
                if dt is not None:
                    self._filters[column] = ("dt_cmp", op, dt)
                    self.invalidateFilter()
                    return
            num = self._parse_number(rhs)
            if num is not None:
                self._filters[column] = ("num_cmp", op, num)
                self.invalidateFilter()
                return
            self._filters[column] = ("substr", s)
            self.invalidateFilter()
            return

        # Range detection
        mnum = self._num_rng_re.match(s)
        if mnum:
            a = self._parse_number(mnum.group(1))
            b = self._parse_number(mnum.group(2))
            if a is not None and b is not None:
                lo, hi = sorted((a, b))
                self._filters[column] = ("num_rng", lo, hi)
                self.invalidateFilter()
                return

        many = self._any_rng_re.match(s)
        if many and (force_date or self._looks_like_date(many.group(1)) or self._looks_like_date(many.group(2))):
            a = self._parse_datetime(many.group(1))
            b = self._parse_datetime(many.group(2))
            if a and b:
                lo, hi = sorted((a, b))
                self._filters[column] = ("dt_rng", lo, hi)
                self.invalidateFilter()
                return

        # Default substring
        self._filters[column] = ("substr", s)
        self.invalidateFilter()

    # ---------------------------------------------------------------------

    def clearColumnFilter(self, column):
        self._filters.pop(column, None)
        self.invalidateFilter()

    def clearAllFilters(self):
        self._filters.clear()
        self.invalidateFilter()

    # ---------------------------------------------------------------------

    def filterAcceptsRow(self, source_row, source_parent):
        src = self.sourceModel()
        if src is None:
            return True
        for col, rule in self._filters.items():
            idx = src.index(source_row, col, source_parent)
            val = src.data(idx) if idx.isValid() else None
            if not self._matches(rule, val):
                return False
        return True

    # ---------------------------------------------------------------------

    def _matches(self, rule, value):
        kind = rule[0]
        text = "" if value is None else str(value)

        if kind == "substr":
            return rule[1].lower() in text.lower()

        if kind == "regex":
            rx = QRegExp(rule[1], Qt.CaseInsensitive)
            return rx.indexIn(text) >= 0

        if kind == "num_cmp":
            op, thresh = rule[1], rule[2]
            v = self._parse_number(text)
            return self._compare(v, op, thresh) if v is not None else False

        if kind == "num_rng":
            lo, hi = rule[1], rule[2]
            v = self._parse_number(text)
            return (lo <= v <= hi) if v is not None else False

        if kind == "dt_cmp":
            op, t0 = rule[1], rule[2]
            v = self._parse_datetime(text)
            return self._compare_dt(v, op, t0) if v is not None else False

        if kind == "dt_rng":
            lo, hi = rule[1], rule[2]
            v = self._parse_datetime(text)
            return (lo <= v <= hi) if v is not None else False

        return True

    # ---------------------------------------------------------------------
    # Parsing helpers

    @staticmethod
    def _parse_number(s):
        try:
            return float(str(s).replace(",", "").strip())
        except Exception:
            return None

    @staticmethod
    def _looks_like_date(s):
        s = s.strip().lower()
        return bool(
            re.search(r"\d{1,4}[-/]\d{1,2}[-/]\d{1,4}", s)
            or re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b", s)
            or "t" in s
        )

    @staticmethod
    def _parse_datetime(s):
        s = s.strip()
        fmts = [
            "%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S",
            "%d/%m/%Y", "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S",
            "%m/%d/%Y", "%m/%d/%Y %H:%M", "%m/%d/%Y %H:%M:%S",
            "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S",
        ]
        s_norm = s.replace("t", "T").replace("T ", "T")
        for fmt in fmts:
            try:
                return datetime.strptime(s_norm, fmt)
            except Exception:
                pass
        # Python 3.6's fromisoformat is limited; guard with try/except
        try:
            return datetime.fromisoformat(s_norm)
        except Exception:
            return None

    @staticmethod
    def _compare(v, op, t):
        if op in ("=", "=="):
            return v == t
        if op == "!=":
            return v != t
        if op == "<":
            return v < t
        if op == "<=":
            return v <= t
        if op == ">":
            return v > t
        if op == ">=":
            return v >= t
        return False

    @staticmethod
    def _compare_dt(v, op, t):
        if op in ("=", "=="):
            return v == t
        if op == "!=":
            return v != t
        if op == "<":
            return v < t
        if op == "<=":
            return v <= t
        if op == ">":
            return v > t
        if op == ">=":
            return v >= t
        return False

