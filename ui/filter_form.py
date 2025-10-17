# ui/filter_form.py
# Python 3.6.9
import datetime
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QGroupBox, QHBoxLayout, QFormLayout,
    QCheckBox, QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit
)

class FilterForm(QWidget):
    """
    Dynamic filter UI builder.
    Renders one group per filter; one control per param id in param_order.
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
        self._rows = []

    def clear(self):
        while self._vbox.count():
            item = self._vbox.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._rows = []

    def build(self, filters):
        self.clear()
        filters = filters or []
        for flt in filters:
            group = QGroupBox(self._title_for(flt))
            vbox = QVBoxLayout(group)
            top = QHBoxLayout()
            chk = QCheckBox("Enable")
            chk.setChecked(bool(flt.get("enabled", False)))
            top.addWidget(chk)
            # tag HAVING visually
            if (flt.get("clause") or "where").lower() == "having":
                tag = QLabel("(HAVING)")
                tag.setStyleSheet("color: gray;")
                top.addWidget(tag)
            top.addStretch(1)
            vbox.addLayout(top)

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
                w, reader = self._make_control(ftype, dval, flt)
                label = pid if len(pids) > 1 else flt.get("label", pid)
                form.addRow(QLabel(label + ":"), w)
                controls.append((pid, reader))

            self._rows.append({"filter": flt, "chk": chk, "controls": controls})
            self._vbox.addWidget(group)

        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().Expanding, spacer.sizePolicy().Expanding)
        self._vbox.addWidget(spacer)

    def collect_params(self):
        params = {}
        for row in self._rows:
            flt = row["filter"]
            enabled = row["chk"].isChecked() or bool(flt.get("enabled", False))
            temp = {}
            any_val = False
            for pid, reader in row["controls"]:
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

    # --- helpers ---
    def _title_for(self, flt):
        return flt.get("label") or flt.get("id") or "Filter"

    def _make_control(self, ftype, default, flt):
        if ftype == "int":
            w = QSpinBox(); w.setRange(-2_147_483_648, 2_147_483_647)
            w.setValue(default if isinstance(default, int) else 0)
            return w, (lambda w=w: w.value())

        if ftype == "float":
            w = QDoubleSpinBox(); w.setDecimals(6); w.setRange(-1e12, 1e12)
            w.setValue(float(default) if isinstance(default, (int, float)) else 0.0)
            return w, (lambda w=w: w.value())

        if ftype == "date":
            w = QDateEdit(); w.setCalendarPopup(True)
            if isinstance(default, (datetime.date, datetime.datetime)):
                w.setDate(QDate(default.year, default.month, default.day))
            else:
                w.setDate(QDate.currentDate())
            return w, (lambda w=w: datetime.date(w.date().year(), w.date().month(), w.date().day()))

        if ftype == "bool":
            w = QCheckBox(); w.setChecked(bool(default))
            return w, (lambda w=w: w.isChecked())

        if ftype == "enum":
            w = QComboBox()
            choices = flt.get("choices", [])
            for c in choices:
                if isinstance(c, dict):
                    w.addItem(c.get("label", c.get("value")), c.get("value"))
                else:
                    w.addItem(str(c), c)
            if default is not None:
                for i in range(w.count()):
                    if w.itemData(i) == default or w.itemText(i) == str(default):
                        w.setCurrentIndex(i); break
            return w, (lambda w=w: w.currentData())

        # default string
        w = QLineEdit()
        if default is not None:
            w.setText(str(default))
        else:
            if " like" in (flt.get("where", "").lower()):
                w.setPlaceholderText("%")
        return w, (lambda w=w: w.text())

