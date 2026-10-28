"""
Table node: rows in this automation's own tables.

Adds, reads, updates and deletes rows of a table the automation keeps (a
``dataset`` resource): the same table the Table block shows, Resources lists
under the automation's database and the SDK's ``dataset`` reaches. Rows go
through ``utils.dataset_store`` alone, which keeps their limits.

A table is named, not picked by id: the picker lists the automation's tables,
and a name it doesn't hold yet is made by the first Add. A table not made yet
holds no rows, so reading, updating or deleting by a match there finds none.
Only this automation's tables are reachable, from a run and from an agent the
node is wired into (``table__add_rows`` …).

Update merges the values given into each row it names (the other columns
stay); rows are named by id or by a match on a column, which reads the table
through to find them.
"""

import json
import logging
from typing import Annotated, Any, Dict, List, Literal, Optional, Type, Union

from pydantic import BaseModel, Discriminator, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode, _scalar_as_str
from utils import dataset_store
from utils.dataset_store import MAX_PAGE_ROWS

logger = logging.getLogger(__name__)


def _table_field() -> Any:
    return Field(
        ...,
        min_length=1,
        title="Table",
        description="The table's name: one of this automation's tables, or a new name, which the first Add makes.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "table",
                "placeholder": "Pick a table or name a new one",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Name a new table",
                "names_new": True,
            },
        },
    )


def _operation(name: str, display: str, keywords: List[str]) -> Any:
    return Field(
        name,
        title=display,
        json_schema_extra={"const": name, "ui:hidden": True, "x-category": "Rows", "x-is-trigger": False,
                           "x-display-name": display, "x-keywords": keywords},
    )


def _json_text(value: Any) -> Any:
    """A JSON text (what the canvas stores for a list or an object) as what it holds; anything else as given."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        raise ValueError("isn't JSON") from None


class _Named(BaseModel):
    table: str = _table_field()

    @field_validator("table")
    @classmethod
    def _strip(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name a table")
        return value.strip()


class _Matching(_Named):
    match_column: Optional[str] = Field(
        None, title="Match column",
        description="Only rows whose column holds Match value (text as written; a number or true/false as its text).",
        json_schema_extra={"ui:placeholder": "email"},
    )
    match_value: Optional[str] = Field(
        None, title="Match value", description="The value Match column holds in the rows meant.",
        json_schema_extra={"ui:placeholder": "{{ $('trigger').email }}"},
    )

    @model_validator(mode="after")
    def _match_is_whole(self):
        if (self.match_column is None) != (self.match_value is None):
            raise ValueError("a match names both a column and the value it holds")
        return self


class _Targeted(_Matching):
    row_id: Optional[str] = Field(
        None, title="Row ID",
        description="The row's id (every row read carries one). Leave empty to name rows by a match instead.",
        json_schema_extra={"ui:placeholder": "{{ $('read').rows[0].id }}"},
    )

    @model_validator(mode="after")
    def _one_target(self):
        if (self.row_id is None) == (self.match_column is None):
            raise ValueError("name the rows by Row ID or by Match column and Match value (one of them)")
        return self


class TableAddRowsConfig(_Named):
    """Add rows after the table's last row; the first Add to a new name makes the table."""
    operation: Literal["add_rows"] = _operation(
        "add_rows", "Add Rows", ["add row", "append rows", "insert rows", "save results", "log to table", "store row"])
    rows: List[Dict[str, Any]] = Field(
        ...,
        title="Rows",
        description=("The rows to add, in order: a list of objects whose keys are the columns. One object adds one "
                     "row; an upstream list passed whole adds a row per item."),
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 5,
                           "ui:placeholder": '[{"name": "Ada", "email": "ada@example.com"}]'},
    )

    @field_validator("rows", mode="before")
    @classmethod
    def _as_rows(cls, value: Any) -> Any:
        value = _json_text(value)
        return [value] if isinstance(value, dict) else value


class TableReadRowsConfig(_Matching):
    """Read rows in order, all of them or those matching a column, a page at a time."""
    operation: Literal["read_rows"] = _operation(
        "read_rows", "Read Rows", ["get rows", "list rows", "find rows", "lookup row", "query table", "search table"])
    limit: int = Field(100, ge=1, le=MAX_PAGE_ROWS, title="Limit", description="At most this many rows.")
    offset: int = Field(0, ge=0, title="Offset", description="Rows to skip first (for the next page).")


class TableUpdateRowsConfig(_Targeted):
    """Set columns of the rows named by id or by a match; their other columns stay."""
    operation: Literal["update_rows"] = _operation(
        "update_rows", "Update Rows", ["edit row", "change row", "set column", "update record", "mark row"])
    values: Dict[str, Any] = Field(
        ...,
        title="Values",
        description="The columns to set and their values, as an object; columns not named keep theirs.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 3, "ui:placeholder": '{"status": "done"}'},
    )

    @field_validator("values", mode="before")
    @classmethod
    def _as_object(cls, value: Any) -> Any:
        return _json_text(value)

    @field_validator("values")
    @classmethod
    def _some(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if not value:
            raise ValueError("name at least one column to set")
        return value


class TableDeleteRowsConfig(_Targeted):
    """Delete the rows named by id or by a match."""
    operation: Literal["delete_rows"] = _operation(
        "delete_rows", "Delete Rows", ["remove row", "delete record", "clear rows", "remove from table"])


TableConfig = Annotated[
    Union[TableAddRowsConfig, TableReadRowsConfig, TableUpdateRowsConfig, TableDeleteRowsConfig],
    Discriminator("operation"),
]


class TableNodeConfig(NodeConfig[TableConfig, None]):
    """Full configuration for the Table node (no credentials: the tables are the automation's own)."""


def _holds(data: Any, column: str, value: str) -> bool:
    cell = data.get(column) if isinstance(data, dict) else None
    return isinstance(cell, (str, bool, int, float)) and _scalar_as_str(cell) == value


def _iso(value: Any) -> Optional[str]:
    return value if value is None or isinstance(value, str) else value.isoformat()


def _row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": str(row["id"]), "data": row["data"], "created_at": _iso(row.get("created_at"))}


class TableNode(WorkflowNode):
    """Rows in the automation's own tables (see the module docstring)."""

    edit_examples = [
        "Save each result as a row in a Results table",
        "Only read the rows whose status is new",
        "Mark the row for this email as contacted",
        "Delete the rows older runs added for this order",
    ]

    _OUTPUT_KEYS = {
        "add_rows": ("table", "table_id", "created", "added"),
        "read_rows": ("table", "table_id", "rows", "total", "has_more"),
        "update_rows": ("table", "table_id", "updated"),
        "delete_rows": ("table", "table_id", "deleted"),
    }

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return TableNodeConfig

    @classmethod
    def declared_output_keys(cls, config: Dict[str, Any]) -> Optional[List[str]]:
        keys = cls._OUTPUT_KEYS.get(config.get("operation"))
        return list(keys) if keys else None

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """The automation's tables by name (``_workflow_id``: the server names it once the caller may see it)."""
        workflow_id = (context or {}).get("_workflow_id")
        if field_name != "table" or not workflow_id:
            return {"options": [], "next_page_token": None}
        from nodes.core.dynamic_options import filter_options_by_search
        from repositories.resources import ResourceRepo
        from utils.database_pool import get_native_pool

        options, seen = [], set()
        for table in await ResourceRepo(get_native_pool()).workflow_datasets(str(workflow_id)):
            if table["name"].strip().lower() not in seen:
                seen.add(table["name"].strip().lower())
                options.append({"value": table["name"], "label": table["name"]})
        return {"options": filter_options_by_search(options, search), "next_page_token": None}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        config = self.config.config if isinstance(self.config, TableNodeConfig) else None
        if config is None:
            raise ValueError("The Table step has no configuration.")
        if not self.workflow_id:
            raise ValueError("A table belongs to an automation: run this step inside one.")
        from repositories.resources import ResourceRepo
        from utils.database_pool import get_native_pool

        pool = get_native_pool()
        repo = ResourceRepo(pool)
        workflow_id = str(self.workflow_id)

        if isinstance(config, TableAddRowsConfig):
            dataset_store.check_rows(config.rows)
            table, created = await repo.make_dataset(workflow_id, config.table)
            if created:
                await dataset_store.create_dataset(pool, table)
            added = await dataset_store.append_rows(pool, table, config.rows)
            return {"table": table["name"], "table_id": str(table["id"]), "created": created, "added": added}

        table = await repo.dataset_named(workflow_id, config.table)
        named = {"table": table["name"] if table else config.table, "table_id": str(table["id"]) if table else None}

        if isinstance(config, TableReadRowsConfig):
            rows, total = await self._read(pool, table, config)
            return {**named, "rows": rows, "total": total, "has_more": config.offset + len(rows) < total}

        rows = await self._targets(pool, table, config)
        if isinstance(config, TableUpdateRowsConfig):
            updated = 0
            for row in rows:
                updated += await dataset_store.update_row(pool, table, row["id"], {**row["data"], **config.values})
            return {**named, "updated": updated}
        ids = [str(row["id"]) for row in rows]
        deleted = 0
        for start in range(0, len(ids), MAX_PAGE_ROWS):
            deleted += await dataset_store.delete_rows(pool, table, ids[start:start + MAX_PAGE_ROWS])
        return {**named, "deleted": deleted}

    @staticmethod
    async def _read(pool, table, config: TableReadRowsConfig):
        """``(rows, total)``: the page asked for, of every row or of the matching ones."""
        if table is None:
            return [], 0
        if config.match_column is None:
            rows, total = await dataset_store.read_rows(pool, table, limit=config.limit, offset=config.offset)
            return [_row(r) for r in rows], total
        rows, total = [], 0
        async for row in dataset_store.each_row(pool, table):
            if _holds(row["data"], config.match_column, config.match_value):
                if config.offset <= total < config.offset + config.limit:
                    rows.append(_row(row))
                total += 1
        return rows, total

    @staticmethod
    async def _targets(pool, table, config: _Targeted) -> List[Dict[str, Any]]:
        """The rows an update or delete names; a row id the table doesn't hold is refused."""
        found: List[Dict[str, Any]] = []
        if table is not None:
            async for row in dataset_store.each_row(pool, table):
                if config.row_id is not None:
                    if str(row["id"]) == config.row_id:
                        return [row]
                elif _holds(row["data"], config.match_column, config.match_value):
                    found.append(row)
        if config.row_id is not None:
            raise ValueError(f"Table {config.table!r} has no row {config.row_id}.")
        return found
