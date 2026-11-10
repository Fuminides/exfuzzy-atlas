"""A response cache bounded by approximate bytes, not by number of entries.

Rule maps weigh from a few KiB (60 stations) to ~0.5 MiB (263 polygons), so a count says little about memory. The size
of an entry is the length of its JSON times ``PYDANTIC_OVERHEAD``: the cached objects are pydantic models, and 300
copies of a 31 KiB (60 points) and of a 499 KiB (263 polygons) rule map grew the process by 6.3x their JSON length
(AT-061), so a budget of 64 MB is about 64 MB of resident memory, not 64 MB of JSON. Approximate by design. Not
thread-safe: the caller holds its own lock.
"""

from __future__ import annotations

from collections import OrderedDict

DEFAULT_CACHE_BYTES = 64 * 2**20
PYDANTIC_OVERHEAD = 6  # resident bytes of a cached response per byte of its JSON (measured 6.3, see above)


def approx_bytes(value) -> int:
    """Approximate resident size of a pydantic response: its JSON length times ``PYDANTIC_OVERHEAD``."""
    return PYDANTIC_OVERHEAD * len(value.model_dump_json())


class ByteLRU:
    """Least-recently-used cache that evicts until the summed size is within ``max_bytes``.

    An entry bigger than the whole budget is not stored (it would evict everything for one reply).
    """

    def __init__(self, max_bytes: int = DEFAULT_CACHE_BYTES):
        if max_bytes < 0:
            raise ValueError("max_bytes must be >= 0")
        self.max_bytes = max_bytes
        self.bytes = 0
        self._items: OrderedDict[tuple, tuple[object, int]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._items)

    def get(self, key: tuple):
        item = self._items.get(key)
        if item is None:
            return None
        self._items.move_to_end(key)
        return item[0]

    def put(self, key: tuple, value, size: int | None = None) -> None:
        size = approx_bytes(value) if size is None else size
        old = self._items.pop(key, None)
        if old is not None:
            self.bytes -= old[1]
        if size > self.max_bytes:
            return
        self._items[key] = (value, size)
        self.bytes += size
        while self.bytes > self.max_bytes:
            _, (_, evicted) = self._items.popitem(last=False)
            self.bytes -= evicted
