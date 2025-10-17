# core/sqlbuilder.py
# Python 3.6.9
import copy

class SQLBuilder:
    """
    Builds SELECT statements from a view dict + runtime params.

    Supports:
      - select kinds: column | expr (catalog expression) | agg
      - joins
      - where vs having filters (with param_order)
      - group_by, order_by
      - limit styles by dialect
      - overrides per dialect (filters/select/order_by/limit/connection/from)
    """
    def __init__(self, queries_cfg):
        self._queries_cfg = queries_cfg  # full queries.json dict

    # ---- public ----
    def build(self, view, params):
        conn_name, dialect, v = self._resolve_view(view)
        select_clause, select_headers = self._render_select(v, dialect)
        from_clause = self._render_from(v)
        where_clause, where_params, having_clause, having_params = self._render_filters(v, params)
        group_clause = self._render_group_by(v)
        order_clause = self._render_order_by(v)
        limit_suffix, top_prefix = self._render_limit(v, dialect)

        sql = "SELECT " + top_prefix + ", ".join(select_clause) + from_clause
        if where_clause:
            sql += " " + where_clause
        if group_clause:
            sql += " " + group_clause
        if having_clause:
            sql += " " + having_clause
        if order_clause:
            sql += " " + order_clause
        if limit_suffix:
            sql += " " + limit_suffix

        binds = where_params + having_params
        return sql, binds, select_headers, conn_name

    # ---- internals ----
    def _resolve_view(self, view):
        conn_name = view.get("connection", self._queries_cfg.get("default_connection"))
        conn_cfg = self._get_connection(conn_name)
        dialect = conn_cfg["dialect"]
        v = self._apply_overrides(view, dialect)
        return conn_name, dialect, v

    def _get_connection(self, name):
        for c in self._queries_cfg["connections"]:
            if c["name"] == name:
                return c
        raise KeyError("Connection not found: {}".format(name))

    def _apply_overrides(self, view, dialect):
        v = copy.deepcopy(view)
        ovr = (view.get("overrides") or {}).get(dialect)
        if not ovr:
            return v

        # filters: merge by id, append new
        if "filters" in ovr and isinstance(ovr["filters"], list):
            base_by_id = {f.get("id"): f for f in v.get("filters", []) if "id" in f}
            out = []
            used = set()
            for f in v.get("filters", []):
                fid = f.get("id")
                if fid and any(of.get("id") == fid for of in ovr["filters"]):
                    of = next(of for of in ovr["filters"] if of.get("id") == fid)
                    nf = copy.deepcopy(f)
                    nf.update(of)
                    out.append(nf)
                    used.add(fid)
                else:
                    out.append(f)
            for of in ovr["filters"]:
                fid = of.get("id")
                if not fid or fid in used or fid in base_by_id:
                    continue
                out.append(copy.deepcopy(of))
            v["filters"] = out

        # select
        if "select" in ovr and isinstance(ovr["select"], list):
            mode = ovr.get("select_mode", "merge")
            if mode == "replace":
                v["select"] = copy.deepcopy(ovr["select"])
            else:
                base = v.get("select", [])
                by_alias = {s.get("alias"): i for i, s in enumerate(base) if s.get("alias")}
                for s in ovr["select"]:
                    alias = s.get("alias")
                    if alias and alias in by_alias:
                        idx = by_alias[alias]
                        nb = copy.deepcopy(base[idx])
                        nb.update(s)
                        base[idx] = nb
                    else:
                        base.append(copy.deepcopy(s))
                v["select"] = base

        # simple replaces
        for key in ("order_by", "limit", "connection"):
            if key in ovr:
                v[key] = copy.deepcopy(ovr[key])

        # from graph replace
        if "from" in ovr:
            v["from"] = copy.deepcopy(ovr["from"])

        return v

    def _render_select(self, v, dialect):
        headers = []
        parts = []
        for it in v["select"]:
            headers.append(it.get("label", it.get("alias")))
            parts.append(self._render_select_item(it, dialect))
        return parts, headers

    def _render_select_item(self, expr_item, dialect):
        k = expr_item.get("kind")
        if k == "column":
            return "{} AS {}".format(expr_item["expr"], expr_item["alias"])
        if k == "expr":
            e = self._queries_cfg.get("catalog", {}).get("expressions", {})[expr_item["ref"]]
            template = e["by_dialect"][dialect]
            sql = template.format(*e["args"])
            return "{} AS {}".format(sql, expr_item["alias"])
        if k == "agg":
            func = expr_item["func"].upper()
            args = expr_item.get("args", [])
            distinct = "DISTINCT " if expr_item.get("distinct") else ""
            if not args:
                raise ValueError("agg select item requires 'args'")
            arg_sql = ", ".join(args)
            return "{}({}{}) AS {}".format(func, distinct, arg_sql, expr_item["alias"])
        raise ValueError("Unknown select kind: {}".format(k))

    def _render_from(self, v):
        from_items = v["from"]
        base = from_items[0]
        s = " FROM {} {}".format(base["table"], base["alias"])
        for f in from_items[1:]:
            j = f.get("join", {})
            jt = j.get("type", "INNER")
            s += " {} JOIN {} {} ON {}".format(jt, f["table"], f["alias"], j["on"])
        return s

    def _render_filters(self, v, params):
        where_parts, having_parts = [], []
        where_params, having_params = [], []

        for flt in v.get("filters", []):
            pids = flt.get("param_order", [flt["id"]])
            runtime_supplied = any(pid in params for pid in pids)
            if not flt.get("enabled") and not runtime_supplied:
                continue

            values = []
            for pid in pids:
                val = params.get(pid, None)
                if val is None:
                    defaults = flt.get("default", None)
                    if isinstance(defaults, dict):
                        val = defaults.get(pid, None)
                    else:
                        if len(pids) == 1:
                            val = defaults
                values.append(val)

            if all(vv is None for vv in values):
                continue

            clause = (flt.get("clause") or "where").lower()
            if clause == "having":
                having_parts.append("(" + flt["where"] + ")")
                for pid in pids:
                    having_params.append(params.get(pid, (flt.get("default", {}) if isinstance(flt.get("default", {}), dict) else flt.get("default"))))
            else:
                where_parts.append("(" + flt["where"] + ")")
                for pid in pids:
                    where_params.append(params.get(pid, (flt.get("default", {}) if isinstance(flt.get("default", {}), dict) else flt.get("default"))))

        where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
        having_clause = ("HAVING " + " AND ".join(having_parts)) if having_parts else ""
        return where_clause, where_params, having_clause, having_params

    def _render_group_by(self, v):
        group_by = v.get("group_by") or []
        return "GROUP BY " + ", ".join(group_by) if group_by else ""

    def _render_order_by(self, v):
        order_by = v.get("order_by") or []
        return "ORDER BY " + ", ".join(order_by) if order_by else ""

    def _render_limit(self, v, dialect):
        lim = v.get("limit")
        if not lim:
            return "", ""
        lim_cfg = self._queries_cfg["dialects"][dialect]["limit"]
        style = lim_cfg["style"]
        if style == "top":
            return "", lim_cfg["template"].format(n=lim["rows"]) + " "
        if style == "fetch_first":
            return lim_cfg["template"].format(n=lim["rows"]), ""
        if style == "limit":
            offset = lim.get("offset", 0)
            return lim_cfg["template"].format(n=lim["rows"], o=offset), ""
        return "", ""

