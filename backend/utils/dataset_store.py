"""An automation's tables: the one way to their rows, and its limits.

A table is a ``workflow_resources`` row of type ``dataset``: its name, its
automation, and who may reach it (access is judged on that row, by the
caller). Its rows are JSON objects in order, each with an id of its own and a
position (``row_index``). Every reader and writer (the ``resource:dataset:*``
socket events the canvas, interface blocks and the SDK send, and the Table
node) comes through here, to the store this instance keeps rows in: the
engine keeps them in Postgres (``repositories.datasets``); a platform
registers its own at start-up (``register_dataset_store``).

A store creates a table's storage when the table is made (``create``),
answers pages in order with the table's row count, appends after the last
row, replaces a row's object by id, deletes rows by id, and drops a table, or
every table of an automation that is deleted for good. It keeps
``metadata.row_count`` on the resource row in step with what it holds.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

# What one page holds (an interface's Table block reads 10,000 rows, the Table node as many).
MAX_PAGE_ROWS = 10_000
# What one row's JSON may weigh.
MAX_ROW_BYTES = 1_000_000


class DatasetError(ValueError):
    """A request the limits refuse, in words for the person who made it."""


class DatasetStore(Protocol):
    async def create(self, resource: Mapping[str, Any]) -> None: ...

    async def rows(self, resource: Mapping[str, Any], *, limit: int,
                   offset: int) -> Tuple[List[Dict[str, Any]], int]: ...

    async def append(self, resource: Mapping[str, Any], rows: Sequence[Dict[str, Any]]) -> int: ...

    async def update_row(self, resource: Mapping[str, Any], row_id: str, data: Dict[str, Any]) -> bool: ...

    async def delete_rows(self, resource: Mapping[str, Any], row_ids: Sequence[str]) -> Tuple[int, int]: ...

    async def drop(self, resource: Mapping[str, Any]) -> None: ...

    async def drop_workflow(self, workflow_id: str) -> None: ...

    async def locations(self, resources: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, str]]: ...


_factory: Optional[Callable[[Any], DatasetStore]] = None


def register_dataset_store(factory: Callable[[Any], DatasetStore]) -> None:
    """Keep tables in the store ``factory(pool)`` makes, from now on."""
    global _factory
    _factory = factory


def dataset_store(pool) -> DatasetStore:
    if _factory is not None:
        return _factory(pool)
    from repositories.datasets import PostgresDatasets

    return PostgresDatasets(pool)


def _dataset(resource: Mapping[str, Any]) -> Mapping[str, Any]:
    if resource["resource_type"] != "dataset":
        raise DatasetError("Resource is not a dataset")
    return resource


def check_rows(rows: Any) -> List[Dict[str, Any]]:
    """Rows a table takes: JSON objects, each at most ``MAX_ROW_BYTES``."""
    if not isinstance(rows, list):
        raise DatasetError("rows is a list of objects.")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise DatasetError(f"Row {index + 1} isn't an object.")
        try:
            size = len(json.dumps(row, ensure_ascii=False).encode())
        except (TypeError, ValueError):
            raise DatasetError(f"Row {index + 1} isn't JSON.") from None
        if size > MAX_ROW_BYTES:
            raise DatasetError(f"Row {index + 1} is {size:,} bytes; a row holds at most {MAX_ROW_BYTES:,}.")
    return rows


def _page(limit: int, offset: int) -> Tuple[int, int]:
    if not 1 <= limit <= MAX_PAGE_ROWS:
        raise DatasetError(f"limit is 1 to {MAX_PAGE_ROWS:,} rows.")
    if offset < 0:
        raise DatasetError("offset is 0 or more.")
    return limit, offset


async def create_dataset(pool, resource: Mapping[str, Any]) -> None:
    await dataset_store(pool).create(_dataset(resource))


async def read_rows(pool, resource: Mapping[str, Any], *, limit: int = 100,
                    offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """``(rows, total)``: each row ``{id, row_index, data, created_at}``."""
    limit, offset = _page(limit, offset)
    return await dataset_store(pool).rows(_dataset(resource), limit=limit, offset=offset)


async def append_rows(pool, resource: Mapping[str, Any], rows: Any) -> int:
    """Append ``rows`` after the last one; how many were added."""
    rows = check_rows(rows)
    await dataset_store(pool).append(_dataset(resource), rows)
    return len(rows)


async def update_row(pool, resource: Mapping[str, Any], row_id: str, data: Any) -> bool:
    """Replace one row's object; False when the table has no such row."""
    [data] = check_rows([data])
    return await dataset_store(pool).update_row(_dataset(resource), str(row_id), data)


async def delete_rows(pool, resource: Mapping[str, Any], row_ids: Sequence[str]) -> int:
    """Delete rows by id; how many there were."""
    deleted, _ = await dataset_store(pool).delete_rows(_dataset(resource), [str(r) for r in row_ids])
    return deleted


async def drop_dataset(pool, resource: Mapping[str, Any]) -> None:
    """A table being deleted: its rows go."""
    await dataset_store(pool).drop(_dataset(resource))


async def drop_workflow_datasets(pool, workflow_id: str) -> None:
    """An automation being deleted for good: every table's rows go."""
    await dataset_store(pool).drop_workflow(str(workflow_id))


async def locations(pool, resources: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, str]]:
    """Where each table's rows live when that's a database of their own:
    ``{resource_id: {database_id, table}}`` (none in the engine's store)."""
    return await dataset_store(pool).locations([r for r in resources if r["resource_type"] == "dataset"])
