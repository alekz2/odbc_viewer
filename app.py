# app.py
import sys
from PyQt5.QtWidgets import QApplication
from odbc_viewer.core.config import Config, ConfigError
from odbc_viewer.ui.main_window import MainWindow

def main():
    import argparse, os
    p = argparse.ArgumentParser(description="ODBC Viewer (cached, pandas)")
    p.add_argument("--config", default="queries.json")
    p.add_argument("--views",  default="views.json")
    p.add_argument("--cache-size", type=int, default=10, help="Cached views capacity (LRU)")
    args = p.parse_args()

    # (optional) normalize paths; omitted for brevity

    try:
        cfg = Config(args.config, args.views)
    except ConfigError as e:
        print("Configuration error:", e); sys.exit(2)

    app = QApplication(sys.argv)
    win = MainWindow(cfg, cache_capacity=args.cache_size)
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()

