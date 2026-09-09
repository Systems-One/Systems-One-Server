import pytest, cache as c


def test_caches_within_ttl_and_rebuilds_after():
    t = [100.0]; calls = []
    def b(): calls.append(1); return {"n": len(calls)}
    cc = c.Cache(clock=lambda: t[0])
    assert cc.get_or_build("k", 30, b)["n"] == 1
    assert cc.get_or_build("k", 30, b)["n"] == 1
    t[0] += 31
    assert cc.get_or_build("k", 30, b)["n"] == 2


def test_stale_on_error_and_raise_when_cold():
    t = [0.0]
    cc = c.Cache(clock=lambda: t[0])
    cc.get_or_build("k", 1, lambda: {"v": 1})
    t[0] += 5
    def boom(): raise RuntimeError("db down")
    r = cc.get_or_build("k", 1, boom)
    assert r["v"] == 1 and r["stale"] is True and "stale_since" in r
    with pytest.raises(RuntimeError):
        cc.get_or_build("other", 1, boom)


def test_stale_on_error_guards_non_dict_payloads():
    """After caching a builder that returns None under key 'n', a failing builder for 'n' returns None (no exception)."""
    t = [0.0]
    cc = c.Cache(clock=lambda: t[0])
    result = cc.get_or_build("n", 1, lambda: None)
    assert result is None
    t[0] += 5
    def boom(): raise RuntimeError("builder failed")
    r = cc.get_or_build("n", 1, boom)
    assert r is None


def test_entries_are_capped_and_the_oldest_is_evicted():
    t = [0.0]
    cc = c.Cache(clock=lambda: t[0])
    for i in range(c.Cache.MAX_ENTRIES + 20):
        t[0] += 1
        cc.get_or_build("k%d" % i, 1, lambda i=i: {"i": i})
    assert len(cc._entries) == c.Cache.MAX_ENTRIES
    assert "k0" not in cc._entries and "k19" not in cc._entries
    assert "k20" in cc._entries and "k%d" % (c.Cache.MAX_ENTRIES + 19) in cc._entries
