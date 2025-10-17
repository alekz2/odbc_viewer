# ui/header.py
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtWidgets import (
    QHeaderView, QMenu, QWidgetAction, QLineEdit, QAction, QWidget, QVBoxLayout, QLabel
)

class PopupHeader(QHeaderView):
    """
    Right-click a header section to open a menu:
      - Inline editor to filter this column (Enter applies)
      - Sort ascending/descending
      - Hide this column
      - Columns submenu to show/hide any column
      - Clear all filters (new)
    """
    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setSectionsClickable(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self._get_current_filter = None      # injected
        self._set_column_filter = None       # injected
        self._toggle_column_visible = None   # injected
        self._columns_provider = None        # injected
        self._sort_request = None            # injected
        self._clear_all_filters = None       # injected  <-- NEW

    # include clear_all_filters in the binding API
    def bind(
        self,
        get_current_filter_callable,
        set_column_filter_callable,
        toggle_column_visible_callable,
        columns_provider_callable,
        sort_request_callable,
        clear_all_filters_callable   # NEW
    ):
        self._get_current_filter = get_current_filter_callable
        self._set_column_filter = set_column_filter_callable
        self._toggle_column_visible = toggle_column_visible_callable
        self._columns_provider = columns_provider_callable
        self._sort_request = sort_request_callable
        self._clear_all_filters = clear_all_filters_callable  # NEW

    def _on_context_menu(self, pos: QPoint):
        logical = self.logicalIndexAt(pos)
        if logical < 0:
            return

        menu = QMenu(self)

        # Inline editor widget action
        w = QWidget(self)
        vbox = QVBoxLayout(w); vbox.setContentsMargins(8, 6, 8, 6)
        vbox.addWidget(QLabel("Filter this column:"))
        le = QLineEdit(w)
        if self._get_current_filter:
            le.setText(self._get_current_filter(logical) or "")
        le.setPlaceholderText("text | re:^A.* | < 1000 | 100..200 | >= 2024-01-01")
        vbox.addWidget(le)
        wa = QWidgetAction(menu)
        wa.setDefaultWidget(w)
        menu.addAction(wa)

        # Press Enter in the inline editor => apply column filter
        le.returnPressed.connect(lambda: self._apply_filter(logical, le.text()))  # <-- NEW

        # --- Actions under the editor ---

        # Clear column filter (renamed)
        clear_col_act = QAction("Clear column filter", menu)  # <-- RENAMED
        clear_col_act.triggered.connect(lambda: self._apply_filter(logical, ""))
        menu.addAction(clear_col_act)

        # Clear all filters (replaces "Apply filter")
        clear_all_act = QAction("Clear all filters", menu)    # <-- NEW
        clear_all_act.triggered.connect(self._do_clear_all_filters)
        menu.addAction(clear_all_act)

        menu.addSeparator()

        # Sorting
        asc_act = QAction("Sort ascending", menu)
        asc_act.triggered.connect(lambda: self._sort(logical, Qt.AscendingOrder))
        menu.addAction(asc_act)
        desc_act = QAction("Sort descending", menu)
        desc_act.triggered.connect(lambda: self._sort(logical, Qt.DescendingOrder))
        menu.addAction(desc_act)

        menu.addSeparator()

        # Hide this column
        hide_act = QAction("Hide this column", menu)
        hide_act.triggered.connect(lambda: self._toggle_column_visible(logical, False) if self._toggle_column_visible else None)
        menu.addAction(hide_act)

        # Columns submenu (show/hide any)
        cols_menu = QMenu("Columns", menu)
        if self._columns_provider:
            for idx, title, visible in self._columns_provider():
                act = QAction(title, cols_menu)
                act.setCheckable(True)
                act.setChecked(visible)
                act.toggled.connect(lambda checked, i=idx: self._toggle_column_visible(i, checked) if self._toggle_column_visible else None)
                cols_menu.addAction(act)
        menu.addMenu(cols_menu)

        # Show under cursor
        global_pos = self.mapToGlobal(pos)
        menu.exec_(global_pos)

    def _apply_filter(self, column, text):
        if self._set_column_filter:
            self._set_column_filter(column, text)

    def _sort(self, section, order):
        if self._sort_request:
            self._sort_request(section, order)

    def _do_clear_all_filters(self):
        if self._clear_all_filters:
            self._clear_all_filters()

