# core/cache.py
# Python 3.6.9
import hashlib
from collections import OrderedDict

class DFCache(object):
    """Simple LRU cache for pandas DataFrames."""
    def __init__(self, capacity=10):
        self.capacity = max(1, int(capacity))
        self._store = OrderedDict()  # key -> DataFrame

    @staticmethod
    def make_key(view_id, sql, binds):
        m = hashlib.sha1()
        m.update((view_id or "").encode("utf-8"))
        m.update(b"\0")
        m.update((sql or "").encode("utf-8"))
        m.update(b"\0")
        m.update(repr(tuple(binds or ())).encode("utf-8"))
        return m.hexdigest()

    def get(self, key):
        if key in self._store:
            df = self._store.pop(key)
            self._store[key] = df  # move to end (MRU)
            return df
        return None

    def set(self, key, df):
        if key in self._store:
            self._store.pop(key)
        self._store[key] = df
        if len(self._store) > self.capacity:
            self._store.popitem(last=False)  # evict LRU

    def clear(self):
        self._store.clear()

