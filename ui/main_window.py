# ui/main_window.py
# Python 3.6.9
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QSplitter, QPushButton, QFileDialog, QMessageBox, QTableView, QStatusBar
)

from odbc_viewer.core.datasource import DataSource
from odbc_viewer.core.sqlbuilder import SQLBuilder
from odbc_viewer.core.config import Config
from odbc_viewer.core.cache import DFCache
from odbc_viewer.ui.filter_form import FilterForm
from odbc_viewer.ui.models import DataFrameModel, ColumnFilterProxyModel
from odbc_viewer.ui.header import PopupHeader


class MainWindow(QMainWindow):
    """Main UI for the ODBC Viewer app with caching and enhanced table features."""
    def __init__(self, cfg, cache_capacity=10):
        super().__init__()
        self.setWindowTitle("PyQt5 ODBC Viewer (cached + filterable)")
        self.resize(1200, 750)

        self._cfg = cfg
        self._builder = SQLBuilder(cfg.queries)
        self._views = cfg.views
        self._view_by_id = {v["id"]: v for v in self._views}
        self._current_view = None

        # Runtime state
        self._cache = DFCache(capacity=cache_capacity)
        self._last_key_by_view = {}     # view_id -> last DFCache key
        self._col_filters = {}          # col_index -> pattern string
        self._hidden_cols = set()       # set of hidden column indices

        self._build_ui()

        # Populate left panel with all views
        for v in self._views:
            it = QListWidgetItem("{}  ({})".format(v.get("title", v["id"]), v["id"]))
            it.setData(Qt.UserRole, v["id"])
            self.list_views.addItem(it)

        # Select first view by default
        if self.list_views.count() > 0:
            self.list_views.setCurrentRow(0)
            self._load_current_view()
            self._try_show_cached_current()

    # ---------------- UI construction ----------------
    def _build_ui(self):
        splitter = QSplitter(self)
        self.setCentralWidget(splitter)

        # ---------- Left panel (Views list) ----------
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Views"))
        self.list_views = QListWidget()
        self.list_views.currentItemChanged.connect(self._on_selection_changed)
        self.list_views.itemDoubleClicked.connect(self._on_double_click)
        left_layout.addWidget(self.list_views)
        splitter.addWidget(left)

        # ---------- Right panel (Filters + Buttons + Table) ----------
        right = QWidget()
        right_layout = QVBoxLayout(right)

        # Dynamic filter form
        self.filters_form = FilterForm()
        right_layout.addWidget(self.filters_form)

        # Button row
        btn_row = QHBoxLayout()
        self.btn_run = QPushButton("Run")
        self.btn_run.clicked.connect(self._run_current_view)
        btn_row.addWidget(self.btn_run)

        self.btn_load_cfg = QPushButton("Load queries.json…")
        self.btn_load_cfg.clicked.connect(self._open_cfg)
        btn_row.addWidget(self.btn_load_cfg)

        self.btn_load_views = QPushButton("Load views…")
        self.btn_load_views.clicked.connect(self._open_views)
        btn_row.addWidget(self.btn_load_views)

        btn_row.addStretch(1)
        right_layout.addLayout(btn_row)

        # Table + header
        self.table = QTableView()
        self.table.setSortingEnabled(True)
        # Right-align vertical numbers for readability
        self.table.verticalHeader().setDefaultAlignment(Qt.AlignRight | Qt.AlignVCenter)

        # Proxy model for per-column filtering/sorting (+ stable row labels)
        self._proxy = ColumnFilterProxyModel(self)
        self.table.setModel(self._proxy)

        # Popup header
        hdr = PopupHeader(Qt.Horizontal, self.table)
        hdr.setSectionsMovable(True)       # allow drag-to-reorder columns
        hdr.setStretchLastSection(False)
        self.table.setHorizontalHeader(hdr)
        hdr.bind(
            get_current_filter_callable=lambda col: self._col_filters.get(col),
            set_column_filter_callable=self._on_set_column_filter,
            toggle_column_visible_callable=self._on_toggle_column_visible,
            columns_provider_callable=self._columns_provider,
            sort_request_callable=self._on_sort_request,
            clear_all_filters_callable=self._on_clear_all_filters
        )

        right_layout.addWidget(self.table)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)

    # ---------------- View selection handlers ----------------
    def _on_selection_changed(self, cur, prev):
        self._load_current_view()
        self._try_show_cached_current()

    def _on_double_click(self, item):
        # Show last cached data, don't query DB
        self._try_show_cached_current()

    def _current_view_id(self):
        it = self.list_views.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _load_current_view(self):
        vid = self._current_view_id()
        self._current_view = self._view_by_id.get(vid)
        filters = (self._current_view or {}).get("filters", [])
        self.filters_form.build(filters)
        self.status.showMessage("Selected view: {}".format(vid or ""), 4000)

    # ---------------- Show cached snapshot ----------------
    def _try_show_cached_current(self):
        vid = self._current_view_id()
        if not vid:
            return
        key = self._last_key_by_view.get(vid)
        if not key:
            return
        df = self._cache.get(key)
        if df is not None:
            self._set_table_df(df)
            self.status.showMessage(
                "Loaded last cached data | Rows: {} | View: {}".format(df.shape[0], vid), 5000
            )

    # ---------------- Core Run logic (cache → DB) ----------------
    def _run_current_view(self):
        if not self._current_view:
            return
        try:
            params = self.filters_form.collect_params()
            sql, binds, headers, conn_name = self._builder.build(self._current_view, params)
            key = DFCache.make_key(self._current_view.get("id"), sql, binds)

            # Cache hit
            df = self._cache.get(key)
            if df is not None:
                self._last_key_by_view[self._current_view.get("id")] = key
                if len(df.columns) == len(headers) and list(df.columns) != headers:
                    df = df.copy(); df.columns = headers
                self._set_table_df(df)
                self.status.showMessage(
                    "Loaded from cache | Rows: {} | View: {}".format(df.shape[0], self._current_view.get("id")), 6000
                )
                return

            # Query DB on demand
            conn_cfg = self._cfg.get_connection_by_name(conn_name)
            ds = DataSource(conn_cfg)
            self.status.showMessage("Querying database…", 3000)
            df = ds.fetch_df(sql, binds)

            if len(df.columns) == len(headers) and list(df.columns) != headers:
                df.columns = headers

            # Cache and show
            self._cache.set(key, df)
            self._last_key_by_view[self._current_view.get("id")] = key
            self._set_table_df(df)
            self.status.showMessage(
                "Fetched from DB | Rows: {} | Dialect: {} | View: {}".format(
                    df.shape[0], conn_cfg["dialect"], self._current_view.get("id")
                ), 6000
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    # ---------------- Table setup and header integration ----------------
    def _set_table_df(self, df):
        """Set DataFrame on proxy model and reapply filters/visibility with stable row labels."""
        base = DataFrameModel(df)

        # Stable vertical labels: prefer df.index if present; otherwise 1..N
        try:
            # Use the index values as labels
            labels = [str(i) for i in df.index]
        except Exception:
            labels = [str(i + 1) for i in range(len(df))]

        self._proxy.setSourceModel(base)
        # self._proxy.setSourceRowLabels(labels)  # ensures vertical header is stable
        self.table.setModel(self._proxy)

        self.table.resizeColumnsToContents()
        self._reapply_visibility(df)
        # re-apply filters
        for col, patt in self._col_filters.items():
            self._proxy.setColumnFilter(col, patt)

    def _reapply_visibility(self, df):
        self._hidden_cols = {c for c in self._hidden_cols if 0 <= c < df.shape[1]}
        for c in range(df.shape[1]):
            self.table.setColumnHidden(c, c in self._hidden_cols)

    def _on_set_column_filter(self, col, text):
        if not text:
            self._col_filters.pop(col, None)
        else:
            self._col_filters[col] = text
        self._proxy.setColumnFilter(col, text)

    def _on_clear_all_filters(self):
        self._col_filters.clear()
        self._proxy.clearAllFilters()
        self.status.showMessage("Cleared all column filters", 3000)

    def _on_toggle_column_visible(self, col, visible):
        if visible:
            self._hidden_cols.discard(col)
        else:
            self._hidden_cols.add(col)
        self.table.setColumnHidden(col, not visible)

    def _columns_provider(self):
        src = self._proxy.sourceModel()
        if src is None:
            return []
        cols = []
        for c in range(src.columnCount()):
            title = src.headerData(c, Qt.Horizontal)
            visible = (c not in self._hidden_cols)
            cols.append((c, str(title), visible))
        return cols

    def _on_sort_request(self, section, order):
        self.table.sortByColumn(section, order)

    # ---------------- Loaders for queries/views ----------------
    def _open_cfg(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open queries.json", "", "JSON Files (*.json)")
        if not path:
            return
        try:
            import json, os
            with open(path, "r", encoding="utf-8") as f:
                self._cfg._queries = json.load(f)
            self._builder = SQLBuilder(self._cfg.queries)
            self._cache.clear()
            self._last_key_by_view.clear()
            self.status.showMessage("Loaded config: {}".format(os.path.abspath(path)), 5000)
        except Exception as e:
            QMessageBox.critical(self, "Error", "Failed to load config:\n{}".format(e))

    def _open_views(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open views.json (or Cancel to pick a directory)", "", "JSON Files (*.json)")
        if path:
            self._reload_views_from(path)
            return
        dir_path = QFileDialog.getExistingDirectory(self, "Open views directory")
        if dir_path:
            self._reload_views_from(dir_path)

    def _reload_views_from(self, path_or_dir):
        try:
            loader = ConfigLoaderShim(self._cfg.queries, path_or_dir)
            self._views = loader.views
            self._view_by_id = {v["id"]: v for v in self._views}
            self.list_views.clear()
            for v in self._views:
                it = QListWidgetItem("{}  ({})".format(v.get("title", v["id"]), v["id"]))
                it.setData(Qt.UserRole, v["id"])
                self.list_views.addItem(it)
            self._cache.clear()
            self._last_key_by_view.clear()
            if self.list_views.count() > 0:
                self.list_views.setCurrentRow(0)
                self._load_current_view()
                self._try_show_cached_current()
            import os
            self.status.showMessage("Loaded views from: {}".format(os.path.abspath(path_or_dir)), 5000)
        except Exception as e:
            QMessageBox.critical(self, "Error", "Failed to load views:\n{}".format(e))


# ---------------- Helper: reload only views ----------------
class ConfigLoaderShim(object):
    def __init__(self, queries_dict, views_path):
        self._queries = queries_dict
        tmp = Config.__new__(Config)
        tmp._load_json = Config._load_json
        tmp._load_views_any = Config._load_views_any
        self.views = tmp._load_views_any(views_path)

