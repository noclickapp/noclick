"""Stateful in-memory R2 fake for CAS tests.

The pure-MagicMock S3 in mock_boto3 can't hold bytes, so it can't verify
"a ref points at a live object", "R2 deleted before the DB row", or the
delete-vs-rePUT race. This fake is dict-backed with working put/get/delete, a
per-key delete counter, and fault injection — so CAS write→GC→read is exercised
for real. It patches the native helpers in ``utils.r2_cloudflare`` (which the
CAS store calls by module attribute), so the store's real 404/missing handling
runs unchanged.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Dict, List, Set
from unittest.mock import patch

import httpx


class FakeR2:
    def __init__(self):
        self.objects: Dict[str, bytes] = {}            # key -> compressed bytes
        self.delete_counts: Dict[str, int] = {}        # key -> times deleted
        self.put_counts: Dict[str, int] = {}           # key -> times PUT
        self.get_counts: Dict[str, int] = {}           # key -> times downloaded
        self.fail_put_keys: Set[str] = set()           # raise on PUT of these
        self.fail_delete_keys: Set[str] = set()        # raise on DELETE of these

    async def upload_bytes_to_r2_async(self, *, bucket: str, key: str,
                                       body: bytes, content_type: str) -> None:
        self.put_counts[key] = self.put_counts.get(key, 0) + 1
        if key in self.fail_put_keys:
            raise RuntimeError(f"injected R2 PUT failure for {key}")
        self.objects[key] = body

    async def download_bytes_from_r2_async_native(self, bucket: str, key: str):
        self.get_counts[key] = self.get_counts.get(key, 0) + 1
        if key not in self.objects:
            request = httpx.Request("GET", f"https://fake-r2/{bucket}/{key}")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("404 Not Found", request=request, response=response)
        return self.objects[key], "application/zstd"

    async def delete_files_from_r2_async_native(self, bucket: str, keys: List[str]) -> int:
        for key in keys:
            self.delete_counts[key] = self.delete_counts.get(key, 0) + 1
            if key in self.fail_delete_keys:
                raise RuntimeError(f"injected R2 DELETE failure for {key}")
            self.objects.pop(key, None)
        return len(keys)

    # convenience for assertions
    def exists(self, key: str) -> bool:
        return key in self.objects


@contextmanager
def patch_r2(fake: "FakeR2"):
    """Patch the native R2 helpers used by the CAS store to route through ``fake``."""
    with patch("utils.r2_cloudflare.upload_bytes_to_r2_async", fake.upload_bytes_to_r2_async), \
         patch("utils.r2_cloudflare.download_bytes_from_r2_async_native", fake.download_bytes_from_r2_async_native), \
         patch("utils.r2_cloudflare.delete_files_from_r2_async_native", fake.delete_files_from_r2_async_native):
        yield fake
