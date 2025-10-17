# core/config.py
# Python 3.6.9
import json
import os
import glob

class ConfigError(Exception):
    pass

class Config:
    """
    Loads:
      - queries.json (dialects, connections, catalog)
      - views.json or a folder of *.view.json files
    Provides accessors and basic validation hooks.
    """
    def __init__(self, queries_path, views_path):
        self._queries = self._load_json(queries_path)
        self._views = self._load_views_any(views_path)

        # Basic sanity checks
        if "connections" not in self._queries or not self._queries["connections"]:
            raise ConfigError("queries.json must define at least one connection")
        if "dialects" not in self._queries:
            raise ConfigError("queries.json must define dialects")

        self._view_by_id = {v["id"]: v for v in self._views}

    @staticmethod
    def _load_json(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _load_views_any(self, path_or_dir):
        if os.path.isdir(path_or_dir):
            files = sorted(glob.glob(os.path.join(path_or_dir, "*.json")))
            files.extend(sorted(glob.glob(os.path.join(path_or_dir, "*.view.json"))))
            views = []
            seen_ids = set()
            for fp in files:
                try:
                    doc = self._load_json(fp)
                    arr = [doc["view"]] if isinstance(doc, dict) and "view" in doc else (doc or {}).get("views", [])
                    for v in arr:
                        vid = v.get("id") or os.path.splitext(os.path.basename(fp))[0]
                        v["id"] = vid
                        if vid not in seen_ids:
                            views.append(v)
                            seen_ids.add(vid)
                except Exception:
                    # skip malformed view files
                    pass
            return views
        else:
            doc = self._load_json(path_or_dir)
            return [doc["view"]] if "view" in doc else (doc or {}).get("views", [])

    # --- public API ---
    @property
    def queries(self):
        return self._queries

    @property
    def views(self):
        return list(self._views)

    def get_view(self, view_id):
        return self._view_by_id.get(view_id)

    def get_connection_by_name(self, name):
        for c in self._queries["connections"]:
            if c["name"] == name:
                return c
        raise ConfigError("Unknown connection: {}".format(name))

    def default_connection_name(self):
        return self._queries.get("default_connection") or self._queries["connections"][0]["name"]

    def dialect_config(self, dialect):
        return self._queries["dialects"][dialect]

    def catalog(self):
        return self._queries.get("catalog", {})

