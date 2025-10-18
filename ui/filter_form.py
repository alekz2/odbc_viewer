import datetime
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QGroupBox, QHBoxLayout,
    QFormLayout, QCheckBox, QLabel, QLineEdit, QSpinBox,
    QDoubleSpinBox, QComboBox, QDateEdit
)


class FilterForm(QWidget):
    """
    Dynamic filter UI builder with per-parameter registry
    (collect_params / set_values / enable_if_present)
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        outer.addWidget(self._scroll)

        self._container = QWidget()
        self._vbox = QVBoxLayout(self._container)
        self._vbox.setContentsMargins(8, 8, 8, 8)
        self._vbox.setSpacing(8)
        self._scroll.setWidget(self._container)

        self._rows = []               # [{filter, chk, controls}]
        self._inputs_by_param = {}    # param_id -> (widget, reader, writer)

    # ---------------------------------------------------------------------

    def clear(self):
        while self._vbox.count():
            item = self._vbox.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._rows = []
        self._inputs_by_param = {}

    def build(self, filters):
        """Build form dynamically from view filters definition."""
        self.clear()
        for flt in (filters or []):
            group = QGroupBox(self._title_for(flt))
            vbox = QVBoxLayout(group)

            # Enable checkbox
            top = QHBoxLayout()
            chk = QCheckBox("Enable")
            chk.setChecked(bool(flt.get("enabled", False)))
            top.addWidget(chk)
            if (flt.get("clause") or "where").lower() == "having":
                tag = QLabel("(HAVING)")
                tag.setStyleSheet("color: gray;")
                top.addWidget(tag)
            top.addStretch(1)
            vbox.addLayout(top)

            # Params form
            form = QFormLayout()
            vbox.addLayout(form)
            pids = flt.get("param_order", [flt["id"]])
            controls = []
            defaults = flt.get("default", None)

            for pid in pids:
                ftype = (flt.get("type") or "string").lower()
                if isinstance(flt.get("types"), dict):
                    ftype = flt["types"].get(pid, ftype)
                dval = defaults.get(pid) if isinstance(defaults, dict) else defaults
                w, reader, writer = self._make_control(ftype, dval, flt)
                label = pid if len(pids) > 1 else flt.get("label", pid)
                form.addRow(QLabel(label + ":"), w)
                controls.append((pid, reader, writer))
                self._inputs_by_param[pid] = (w, reader, writer)

            self._rows.append({"filter": flt, "chk": chk, "controls": controls})
            self._vbox.addWidget(group)

        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().Expanding, spacer.sizePolicy().Expanding)
        self._vbox.addWidget(spacer)

    # ---------------------------------------------------------------------

    def collect_params(self):
        """Return dict of enabled parameter values."""
        params = {}
        for row in self._rows:
            flt = row["filter"]
            enabled = row["chk"].isChecked() or bool(flt.get("enabled", False))
            temp = {}
            any_val = False
            for pid, reader, _ in row["controls"]:
                val = reader()
                if isinstance(val, str) and val == "":
                    val = None
                if val is not None:
                    any_val = True
                    temp[pid] = val
            if enabled or any_val:
                defaults = flt.get("default", None)
                for pid in list(temp.keys()):
                    if temp[pid] is None:
                        if isinstance(defaults, dict) and pid in defaults:
                            temp[pid] = defaults[pid]
                        elif defaults is not None and len(row["controls"]) == 1:
                            temp[pid] = defaults
                for k, v in temp.items():
                    if v is not None:
                        params[k] = v
        return params

    def set_values(self, values, enable_if_present=True):
        """Restore widget values from a dict."""
        if not values:
            return
        # Write param values via writers
        for pid, val in values.items():
            entry = self._inputs_by_param.get(pid)
            if not entry:
                continue
            _w, _reader, writer = entry
            try:
                writer(val)
            except Exception:
                # Best effort
                pass
        if enable_if_present:
            present = set(values.keys())
            for row in self._rows:
                pids = [pid for (pid, _r, _w) in row["controls"]]
                if any(pid in present for pid in pids):
                    row["chk"].setChecked(True)

    # ---------------------------------------------------------------------
    # Helpers

    def _title_for(self, flt):
        return flt.get("label") or flt.get("id") or "Filter"

    def _make_control(self, ftype, default, flt):
        """
        Return (widget, reader, writer).
        Writer accepts a Python value and updates the widget appropriately.
        """
        # int
        if ftype == "int":
            w = QSpinBox()
            w.setRange(-2_147_483_648, 2_147_483_647)
            if isinstance(default, int):
                w.setValue(default)

            def reader(w=w):
                return w.value()

            def writer(val, w=w):
                try:
                    w.setValue(int(val))
                except Exception:
                    pass

            return w, reader, writer

        # float
        if ftype == "float":
            w = QDoubleSpinBox()
            w.setDecimals(6)
            w.setRange(-1e12, 1e12)
            if isinstance(default, (int, float)):
                w.setValue(float(default))

            def reader(w=w):
                return w.value()

            def writer(val, w=w):
                try:
                    w.setValue(float(val))
                except Exception:
                    pass

            return w, reader, writer

        # date
        if ftype == "date":
            w = QDateEdit()
            w.setCalendarPopup(True)
            if isinstance(default, (datetime.date, datetime.datetime)):
                w.setDate(QDate(default.year, default.month, default.day))
            else:
                w.setDate(QDate.currentDate())

            def reader(w=w):
                d = w.date()
                return datetime.date(d.year(), d.month(), d.day())

            def writer(val, w=w):
                try:
                    if isinstance(val, datetime.datetime):
                        val = val.date()
                    if isinstance(val, datetime.date):
                        w.setDate(QDate(val.year, val.month, val.day))
                    else:
                        # try parse yyyy-mm-dd
                        y, m, d = str(val).split("-")
                        w.setDate(QDate(int(y), int(m), int(d)))
                except Exception:
                    pass

            return w, reader, writer

        # bool
        if ftype == "bool":
            w = QCheckBox()
            w.setChecked(bool(default))

            def reader(w=w):
                return w.isChecked()

            def writer(val, w=w):
                w.setChecked(bool(val))

            return w, reader, writer

        # enum
        if ftype == "enum":
            w = QComboBox()
            choices = flt.get("choices", [])
            for c in choices:
                if isinstance(c, dict):
                    w.addItem(c.get("label", c.get("value")), c.get("value"))
                else:
                    w.addItem(str(c), c)
            # default selection
            if default is not None:
                for i in range(w.count()):
                    if w.itemData(i) == default or w.itemText(i) == str(default):
                        w.setCurrentIndex(i)
                        break

            def reader(w=w):
                return w.currentData()

            def writer(val, w=w):
                # try by data first, then by text
                for i in range(w.count()):
                    if w.itemData(i) == val or w.itemText(i) == str(val):
                        w.setCurrentIndex(i)
                        return

            return w, reader, writer

        # string (default)
        w = QLineEdit()
        if default is not None:
            w.setText(str(default))
        else:
            if " like" in (flt.get("where", "").lower()):
                w.setPlaceholderText("%")

        def reader(w=w):
            return w.text()

        def writer(val, w=w):
            w.setText("" if val is None else str(val))

        return w, reader, writer

