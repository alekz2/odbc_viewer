# core/datasource.py
import os
import pyodbc
import pandas as pd  # NEW

class DataSource:
    """Manages pyodbc connections and query execution."""
    def __init__(self, conn_cfg):
        self._conn_cfg = conn_cfg

    def connect(self):
        parts = []
        if self._conn_cfg.get("dsn"):
            parts.append("DSN={}".format(self._conn_cfg["dsn"]))
        else:
            parts.append("DRIVER={}".format(self._conn_cfg["driver"]))
            if self._conn_cfg.get("server"):   parts.append("SERVER={}".format(self._conn_cfg["server"]))
            if self._conn_cfg.get("port"):     parts.append("PORT={}".format(self._conn_cfg["port"]))
            if self._conn_cfg.get("database"): parts.append("DATABASE={}".format(self._conn_cfg["database"]))
        uid = os.getenv(self._conn_cfg.get("user_env", ""), "")
        pwd = os.getenv(self._conn_cfg.get("password_env", ""), "")
        if uid: parts.append("UID={}".format(uid))
        if pwd: parts.append("PWD={}".format(pwd))
        if self._conn_cfg.get("options", {}).get("encoding") == "UTF-8":
            parts.append("CHARSET=UTF8")
        return pyodbc.connect(";".join(parts))

    # Keep the old tuple fetch if you want; add DataFrame fetch:
    def fetch_df(self, sql, binds):
        cn = self.connect()
        try:
            # pandas will use the DBAPI cursor under the hood; pyodbc supports qmark params
            return pd.read_sql(sql, cn, params=list(binds or []))
        finally:
            try: cn.close()
            except Exception: pass

