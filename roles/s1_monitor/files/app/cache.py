"""Per-endpoint TTL cache. Serves the last good payload, flagged stale, when the builder fails."""
import datetime as dt
import threading
import time


class Cache:
    MAX_ENTRIES = 256   # keys carry ids from the URL; cap the map so it cannot grow without bound

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._entries = {}   # key -> (built_at_monotonic, built_at_utc_iso, payload)

    def get_or_build(self, key, ttl, builder):
        now = self._clock()
        with self._lock:
            e = self._entries.get(key)
            if e and now - e[0] <= ttl:
                return e[2]
        try:
            payload = builder()
        except Exception:
            if e:
                if not isinstance(e[2], dict):
                    return e[2]
                stale = dict(e[2]); stale["stale"] = True; stale["stale_since"] = e[1]
                return stale
            raise
        with self._lock:
            self._entries[key] = (now, dt.datetime.now(dt.timezone.utc).replace(microsecond=0, tzinfo=None).isoformat() + "Z", payload)
            while len(self._entries) > self.MAX_ENTRIES:
                del self._entries[min(self._entries, key=lambda k: self._entries[k][0])]
        return payload


cache = Cache()
