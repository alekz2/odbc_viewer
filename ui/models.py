from PyQt5.QtCore import QAbstractTableModel, Qt, QVariant
from PyQt5.QtCore import QSortFilterProxyModel, Qt, QRegExp, QModelIndex
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
        if role != Qt.DisplayRole:
            return QVariant()
        if self._df is None:
            return QVariant()
        if orientation == Qt.Horizontal:
            return str(self._df.columns[section])
        else:
            return section + 1


class ColumnFilterProxyModel(QSortFilterProxyModel):
    """
    Per-column filters:
      - substring (default, case-insensitive)
      - regex:       re:<pattern>
      - number cmp:  <, <=, >, >=, =/==, !=          e.g.,  < 1000
      - number rng:  a..b (inclusive)                e.g.,  100..200
      - date cmp:    <, <=, >, >=, =/==, !=          e.g.,  >= 2024-01-01
      - date rng:    a..b (inclusive)                e.g.,  2024-01-01 .. 2024-12-31
      Hints:
        - thousands separators are OK in numbers: 1,234.56
        - to force date parsing, prefix with date: or dt:  e.g., date:>= 01/02/2024
    """
    # operators and patterns
    _cmp_re     = re.compile(r"^\s*(<=|>=|<|>|==|=|!=)\s*(.+?)\s*$")
    _num_rng_re = re.compile(r"^\s*(-?\d[\d,]*(?:\.\d+)?)\s*\.\.\s*(-?\d[\d,]*(?:\.\d+)?)\s*$")
    _any_rng_re = re.compile(r"^\s*(.+?)\s*\.\.\s*(.+?)\s*$")  # for date/time ranges

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filters = {}  # col_index -> ("substr", patt) | ("regex", patt) | ("num_cmp", op, val) | ("num_rng", a, b) | ("dt_cmp", op, dt) | ("dt_rng", a, b)
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        return self.sourceModel().headerData(section, orientation, role)


    # ---------- public API ----------
    def setColumnFilter(self, column, pattern):
        if pattern is None:
            self._filters.pop(column, None); self.invalidateFilter(); return

        s = str(pattern).strip()
        if s == "":
            self._filters.pop(column, None); self.invalidateFilter(); return

        # regex
        if s.lower().startswith("re:"):
            self._filters[column] = ("regex", s[3:])
            self.invalidateFilter(); return

        # explicit date mode (strip date:/dt: prefix for parsing hints)
        force_date = False
        if s.lower().startswith("date:") or s.lower().startswith("dt:"):
            force_date = True
            s = s.split(":", 1)[1].strip()

        # comparison?  (< <= > >= = == !=) target could be number or date
        m = self._cmp_re.match(s)
        if m:
            op, rhs = m.groups()
            if force_date or self._looks_like_date(rhs):
                dt = self._parse_datetime(rhs)
                if dt is not None:
                    self._filters[column] = ("dt_cmp", op, dt)
                    self.invalidateFilter(); return
            # numeric compare
            num = self._parse_number(rhs)
            if num is not None:
                self._filters[column] = ("num_cmp", op, num)
                self.invalidateFilter(); return
            # fallback: substring
            self._filters[column] = ("substr", s)
            self.invalidateFilter(); return

        # range?  try numeric range first
        mnum = self._num_rng_re.match(s)
        if mnum:
            a = self._parse_number(mnum.group(1))
            b = self._parse_number(mnum.group(2))
            if a is not None and b is not None:
                lo, hi = (a, b) if a <= b else (b, a)
                self._filters[column] = ("num_rng", lo, hi)
                self.invalidateFilter(); return

        # generic range (likely date/time)
        many = self._any_rng_re.match(s)
        if many and (force_date or self._looks_like_date(many.group(1)) or self._looks_like_date(many.group(2))):
            a = self._parse_datetime(many.group(1))
            b = self._parse_datetime(many.group(2))
            if a is not None and b is not None:
                lo, hi = (a, b) if a <= b else (b, a)
                self._filters[column] = ("dt_rng", lo, hi)
                self.invalidateFilter(); return

        # default substring
        self._filters[column] = ("substr", s)
        self.invalidateFilter()

    def clearColumnFilter(self, column):
        self._filters.pop(column, None); self.invalidateFilter()

    def clearAllFilters(self):
        self._filters.clear(); self.invalidateFilter()

    # ---------- core filtering ----------
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

    def _matches(self, rule, value):
        kind = rule[0]
        text = "" if value is None else str(value)

        if kind == "substr":
            patt = rule[1]
            return patt.lower() in text.lower()

        if kind == "regex":
            patt = rule[1]
            rx = QRegExp(patt, Qt.CaseInsensitive)
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

    # ---------- helpers: parsing & compare ----------
    @staticmethod
    def _parse_number(s):
        try:
            s = s.replace(",", "").strip()
            return float(s)
        except Exception:
            return None

    @staticmethod
    def _looks_like_date(s):
        s = s.strip().lower()
        # quick heuristics: digits + separators, month names, 't' between date time
        return bool(re.search(r"\d{1,4}[-/]\d{1,2}[-/]\d{1,4}", s) or
                    re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b", s) or
                    "t" in s)

    @staticmethod
    def _parse_datetime(s):
        s = s.strip()
        # Try a set of common formats (extend as needed)
        fmts = [
            "%Y-%m-%d",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%d/%m/%Y",
            "%d/%m/%Y %H:%M",
            "%d/%m/%Y %H:%M:%S",
            "%m/%d/%Y",
            "%m/%d/%Y %H:%M",
            "%m/%d/%Y %H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%dT%H:%M:%S",
        ]
        # Normalize “T” separator variants
        s_norm = s.replace("t", "T").replace("T ", "T")
        for fmt in fmts:
            try:
                return datetime.strptime(s_norm, fmt)
            except Exception:
                pass
        # Try forgiving: if only date provided with time text "00:00"
        try:
            return datetime.fromisoformat(s_norm)  # Python 3.6.9 doesn't have full fromisoformat for 'Z'
        except Exception:
            return None

    @staticmethod
    def _compare(v, op, t):
        if op in ("=", "=="): return v == t
        if op == "!=":        return v != t
        if op == "<":         return v <  t
        if op == "<=":        return v <= t
        if op == ">":         return v >  t
        if op == ">=":        return v >= t
        return False

    @staticmethod
    def _compare_dt(v, op, t):
        if op in ("=", "=="): return v == t
        if op == "!=":        return v != t
        if op == "<":         return v <  t
        if op == "<=":        return v <= t
        if op == ">":         return v >  t
        if op == ">=":        return v >= t
        return False

