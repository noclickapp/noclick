"""Databases: SQL for an app or an agent, SQLite by default and Postgres when you outgrow it.

    db = noclick.Database.from_name("orders", create_if_missing=True)
    db.migrate("migrations/")
    db.execute("insert into orders (id, item, qty) values (?, ?, ?)", ["o1", "bun", 3])
    for row in db.query("select item, qty from orders where qty > ?", [2]):
        print(row["item"], row["qty"])

The same object serves an app (bound to a project) and an agent keeping its own
state. Placeholders are ``?`` with a list, or ``:name`` with a dict, on either engine.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Literal, Mapping, Optional, Sequence, Tuple, Union
from urllib.parse import quote

from ._client import Client, resolve_client
from ._object import (
    Page, _Object, bound_arguments, compact, field, iso_time, list_all, list_page, paginate, parse_time,
    ref_id, tool_entries,
)
from ._sync import synced
from .trash import TrashItem, trashed
from ._scope import AMBIENT, resolve_scope
from .exceptions import Conflict, NotFound
from .export import ExportBundle
from .operation import Operation, register_result

Engine = Literal["sqlite", "postgres"]
#: What a preview branch's copy of a SQLite database holds besides its schema: production's rows too.
BranchData = Literal["copy"]
# ``?`` placeholders take a list, ``:name`` placeholders a dict.
Params = Union[None, Sequence[Any], Mapping[str, Any]]
# One statement of a batch: the SQL alone, or the SQL and its parameters.
Statement = Union[str, Tuple[str, Params]]


def _value(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (datetime, date)) else value


def _params(params: Params) -> Any:
    if params is None:
        return None
    if isinstance(params, Mapping):
        return {str(k): _value(v) for k, v in params.items()}
    if isinstance(params, (str, bytes)):
        raise TypeError("Pass params as a list (for ?) or a dict (for :name), not a string.")
    return [_value(v) for v in params]


def _statement(sql: str, params: Params) -> Dict[str, Any]:
    return compact(sql=sql, params=_params(params))


@dataclass(frozen=True)
class QueryResult:
    """What one statement returned. ``rows`` holds a dict per row, keyed by the
    ``columns`` in order; iterating the result yields the rows. ``rows_read`` and
    ``rows_written`` are what the statement touched: on SQLite the rows it read
    and wrote, what it's billed on; on Postgres the rows it returned and changed,
    not billed. ``last_row_id`` is the rowid an ``insert`` made on SQLite
    (``None`` on Postgres, where ``returning`` gives it)."""

    columns: List[str]
    rows: List[Dict[str, Any]] = dc_field(repr=False)
    rows_read: int
    rows_written: int
    last_row_id: Optional[int]
    duration_ms: Optional[float]
    raw: Dict[str, Any] = dc_field(repr=False)

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    @classmethod
    def _from(cls, raw: Any) -> "QueryResult":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            columns=list(raw.get("columns") or []),
            rows=[row for row in raw.get("rows") or [] if isinstance(row, dict)],
            rows_read=int(raw.get("rows_read") or 0),
            rows_written=int(raw.get("rows_written") or 0),
            last_row_id=raw.get("last_row_id"),
            duration_ms=raw.get("duration_ms"),
            raw=raw,
        )


@dataclass(frozen=True)
class Migration:
    """A migration the database has applied: its ``name`` (the file name), when
    (``applied_at``), and the ``checksum`` of the SQL that ran. A later ``migrate``
    that sends the same name with different SQL is refused."""

    name: str
    applied_at: Any
    checksum: Optional[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "Migration":
        raw = raw if isinstance(raw, dict) else {}
        return cls(raw.get("name") or "", parse_time(raw.get("applied_at")), raw.get("checksum"), raw)


@dataclass(frozen=True)
class MigrationResult:
    """What ``migrate`` did: ``applied`` names the migrations it ran now, in order;
    ``pending`` names those still to run (empty after a real run, everything new
    after a ``dry_run``). Migrations applied before are in neither."""

    applied: List[str]
    pending: List[str]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "MigrationResult":
        raw = raw if isinstance(raw, dict) else {}
        return cls(list(raw.get("applied") or []), list(raw.get("pending") or []), raw)


@dataclass(frozen=True)
class Column:
    """One column of a table: its ``name``, its ``type`` as the engine spells it,
    whether it's ``nullable`` and part of the ``primary_key``, and its ``default``
    expression (``None`` when it has none)."""

    name: str
    type: str
    nullable: bool
    primary_key: bool
    default: Optional[str]

    @classmethod
    def _from(cls, raw: Any) -> "Column":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            raw.get("name") or "", raw.get("type") or "", bool(raw.get("nullable", True)),
            bool(raw.get("primary_key")), raw.get("default"),
        )


@dataclass(frozen=True)
class Table:
    """A table: its ``name``, its ``columns`` in order, and ``row_count`` (exact on
    SQLite, the planner's estimate on Postgres)."""

    name: str
    columns: List[Column]
    row_count: Optional[int]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "Table":
        raw = raw if isinstance(raw, dict) else {}
        columns = [Column._from(c) for c in raw.get("columns") or [] if isinstance(c, dict)]
        return cls(raw.get("name") or "", columns, raw.get("row_count"), raw)


def _read_database(result: Any, op: Operation) -> "Database":
    """A restore or a branch settles with the database's view."""
    return Database._new(raw=result if isinstance(result, dict) else {}, client=op._client, user=op._scope)


def _read_export(result: Any, op: Operation) -> ExportBundle:
    return ExportBundle._from(result)


register_result("database.restore", _read_database)
register_result("database.branch", _read_database)
register_result("database.export", _read_export)


def _migration_files(source: Union[str, "os.PathLike[str]", Mapping[str, str]]) -> List[Dict[str, str]]:
    """``{name, sql}`` for each migration, in name order: a dict's entries, or a directory's ``*.sql`` files."""
    if isinstance(source, Mapping):
        items = sorted((str(name), sql) for name, sql in source.items())
        where = "The migrations dict"
    else:
        folder = Path(source)
        if not folder.is_dir():
            raise NotADirectoryError(f"{folder} is not a directory of .sql files.")
        items = [(path.name, path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.sql"))]
        where = str(folder)
    if not items:
        raise ValueError(f"{where} holds no migrations (.sql files).")
    return [{"name": name, "sql": sql} for name, sql in items]


def _seed_sql(migrations: Union[str, "os.PathLike[str]", Mapping[str, str]],
              seed: Union[None, str, "os.PathLike[str]"]) -> Optional[str]:
    """The seed's SQL: ``seed``'s file, else a ``seed.sql`` beside a migrations directory (None without one)."""
    if seed is not None:
        return Path(seed).read_text(encoding="utf-8")
    if isinstance(migrations, Mapping):
        return None
    beside = Path(migrations).parent / "seed.sql"
    return beside.read_text(encoding="utf-8") if beside.is_file() else None


#: What an agent, a toolkit or a hosted MCP server may do with a database, each a tool of its own.
DATABASE_TOOLS = ("query", "execute", "schema")
#: Operations only ``only(...)`` gives: ``upsert`` writes one row of the table bound to it.
_ONLY_TOOLS = DATABASE_TOOLS + ("upsert",)


@dataclass(frozen=True)
class DatabaseOperations:
    """Some of a database's operations as tools (``db.only(...)``), with the
    arguments ``bind(...)`` fixed."""

    database: "Database"
    operations: List[str]
    #: The arguments NoClick fills on every call, out of the model's reach.
    bindings: Dict[str, Any] = dc_field(default_factory=dict)

    def bind(self, **arguments: Any) -> "DatabaseOperations":
        """Fix arguments of these operations, as ``ConnectionOperations.bind`` does: a
        bound parameter leaves the tool's schema and NoClick fills it on every call, from
        ``{{user.id}}``, ``{{user.email}}``, ``{{user.name}}`` or ``{{user.metadata.<key>}}``
        where a value names them. ``upsert`` needs ``table`` bound; bind a column too and
        every row it writes carries that value. Sends nothing.

        Returns:
            A new ref with these arguments bound on top of any bound before.

        Usage:
            One tool that writes one enriched company at a time, keyed by its primary key::

                db = noclick.Database.from_name("leads")
                researcher = noclick.Agent.from_name(
                    "researcher",
                    create_if_missing=True,
                    instructions="You research each company you're given and save what you find.",
                    tools=["exa.search", db.only("upsert").bind(table="enriched")],
                )

            Every row a user's agent writes is stamped with that user::

                db = noclick.Database.from_name("notes")
                notes = db.only("upsert").bind(table="notes", owner="{{user.id}}")
        """
        return DatabaseOperations(self.database, list(self.operations), {**self.bindings, **bound_arguments(arguments)})

    async def _tool_refs(self, scope: Any) -> List[Any]:
        if "upsert" in self.operations and "table" not in self.bindings:
            raise ValueError("upsert writes to one table: bind it, db.only('upsert').bind(table='enriched')")
        return tool_entries(f"database:{await ref_id(self.database)}", self.operations, self.bindings)


class Database(_Object):
    """A SQL database: SQLite (``engine="sqlite"``, the default, cheap while idle)
    or Postgres. ``query`` reads, ``execute`` and ``batch`` write, ``migrate``
    applies your schema. ``status`` is ``ready``, or ``restoring`` / ``branching``
    while an operation works on it. In an agent's or a toolkit's ``tools=`` it is
    three tools, ``{name}__query``, ``{name}__execute`` and ``{name}__schema``;
    ``only(...)`` picks some of them."""

    _repr_keys = ("id", "name", "engine")

    id: str = field("id")
    name: str = field("name")
    engine: str = field("engine", doc='``"sqlite"`` or ``"postgres"``.')
    status: str = field("status", doc="``ready``, ``restoring`` or ``branching``.")
    size_bytes: Optional[int] = field("size_bytes")
    table_count: Optional[int] = field("table_count")
    parent_id: Optional[str] = field("parent_id", doc="The database a branch was made from (None if it isn't one).")
    used_by: List[Dict[str, Any]] = field(
        "used_by",
        doc="Who uses it: apps that bind it (``kind`` ``project``, with the ``binding`` name) and agents "
        "with it in their tools (``kind`` ``agent``), each with its ``id`` and ``name``.",
    )
    region: Optional[str] = field(
        "region", doc="The region it keeps its data in (``noclick.regions()``), fixed when it was created; a branch "
        "is in its source's.",
    )
    user_id: Optional[str] = field("user_id")
    workflow: Optional[Dict[str, Any]] = field(
        "workflow", doc="``{id, name}`` of the automation whose tables it holds (NoClick makes one for each "
        "automation that keeps tables; None for every other database).",
    )
    created_at: Any = field("created_at", parse_time)

    def _init(self, **kwargs: Any) -> None:
        self._create_with: Optional[Dict[str, Any]] = None
        self._branch_data: Optional[BranchData] = None
        super()._init(**kwargs)

    @property
    def console_url(self) -> Optional[str]:
        """This database in the developer console (None off the hosted API)."""
        base = self._api.console_url("resources", "databases")
        return f"{base}?database={quote(str(self._known('id')), safe='')}" if base and self._known("id") else base

    def only(self, *operations: str) -> DatabaseOperations:
        """A tool ref to some of its operations, for ``tools=``: ``"query"`` (a
        read-only statement), ``"execute"`` (a statement that writes) and
        ``"schema"`` (its tables and columns). The database itself in ``tools=``
        gives all three. ``"upsert"`` writes one row of one table, inserting it or
        updating the row with its primary key; its parameters are that table's columns,
        so the model fills a form rather than writing SQL. Bind its table with
        ``.bind(table=...)``.

        Returns:
            A ref to just those operations, to list in ``tools=``; ``bind(...)`` fixes arguments.

        Usage:
            Let an agent read the bookings, but never change them::

                bookings = noclick.Database.from_name("booking-db")
                concierge = noclick.Agent.from_name(
                    "concierge", create_if_missing=True,
                    instructions="You book tables. Check the bookings before you promise one.",
                    tools=[bookings.only("query", "schema"), "search"],
                )

            Or let it save one row at a time to one table, and nothing else::

                leads = noclick.Database.from_name("leads")
                researcher = noclick.Agent.from_name(
                    "researcher", create_if_missing=True,
                    instructions="You research each company you're given and save what you find.",
                    tools=["exa.search", leads.only("upsert").bind(table="enriched")],
                )
        """
        unknown = [op for op in operations if op not in _ONLY_TOOLS]
        if not operations or unknown:
            raise ValueError(
                f"only() takes some of {', '.join(DATABASE_TOOLS)}, not {', '.join(unknown) or 'nothing'} "
                "(or upsert, with its table bound)"
            )
        return DatabaseOperations(self, list(operations))

    # --- construction ----------------------------------------------------

    @synced
    @classmethod
    async def create(
        cls, name: str, *, engine: Engine = "sqlite", region: Optional[str] = None, allow_existing: bool = False,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> "Database":
        """Create a database called ``name``, unique to its user (a taken name
        raises ``noclick.Conflict`` with ``existing_id``, or with ``allow_existing=True``
        returns the database already there, data and all). ``region``
        (``noclick.regions()``) is where its data is kept, for good; without one,
        your account's default region, else ``us-east``. A SQLite database outside
        ``eu`` is placed in its region as capacity allows (``us-east`` and
        ``us-west`` keep it in the United States). An agent or app in the same
        region reaches it fastest.

        Returns:
            The new database, ``ready`` and empty.

        Usage:
            SQLite unless you ask for Postgres::

                orders = noclick.Database.create("orders")
                analytics = noclick.Database.create("analytics", engine="postgres")

            Created inside ``as_user``, it belongs to (and bills) that user::

                with noclick.as_user("user_42"):
                    notes = noclick.Database.create("notes")

            Beside the agent that queries it::

                concierge = noclick.Agent.from_name("concierge")
                bookings = noclick.Database.create("bookings", region=concierge.region)
        """
        scope = resolve_scope(user)
        raw = await cls._create_named("/v1/databases", {"name": name, "engine": engine, **compact(region=region)},
                                      allow_existing=allow_existing, user=scope, client=client)
        return cls._new(raw=raw, client=client, user=scope)

    @classmethod
    def from_name(
        cls, name: str, *, create_if_missing: bool = False, engine: Engine = "sqlite", region: Optional[str] = None,
        branch_data: Optional[BranchData] = None, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> "Database":
        """A lazy reference to the database called ``name`` in the current (or
        given) user. With ``create_if_missing=True`` it's created on first use
        with ``engine`` in ``region`` (as ``create``); one that exists is used as
        it is, whatever its engine and region.

        Inside a deployed app (signed in by its deployment) the name is looked up in the app's own
        namespace for the environment the code runs in, and one made there is the app's: a name bound to
        the app by hand wins, and in a preview of an app whose ``preview_resources`` is ``branch`` the
        branch gets its own copy at its first write, reading production's as it is until then, so a
        preview never changes production's data. A Postgres copy is a copy-on-write branch of production's
        data. A SQLite copy holds the schema and migrations only (``migrate``'s ``seed`` fills it), unless
        ``branch_data="copy"`` asks for production's rows too: they're read at one moment while production
        keeps serving, from a database of up to 200,000 rows and 16 MB. Asked after the branch's copy was
        made without them, that copy goes to the trash and the next write makes one with them.
        ``branch_data`` changes nothing outside a preview.

        Returns:
            A database that loads (or is created) the first time it's used. Nothing is sent yet.

        Usage:
            Name it in your code, so the first run creates it::

                db = noclick.Database.from_name("orders", create_if_missing=True)
                db.migrate("migrations/")
                print(db.query("select count(*) as n from orders").rows[0]["n"])

            An agent's own state, one database per user::

                with noclick.as_user("user_42"):
                    memory = noclick.Database.from_name("assistant-state", create_if_missing=True)
                    memory.execute("create table if not exists notes (id integer primary key, body text)")

            A preview that tries a change against production's rows, never touching them::

                db = noclick.Database.from_name("orders", create_if_missing=True, branch_data="copy")
        """
        database = cls._new(hints={"name": name}, client=client, user=user)
        if create_if_missing:
            database._create_with = {"name": name, "engine": engine, **compact(region=region)}
        database._branch_data = branch_data
        return database

    @classmethod
    def from_id(cls, database_id: str, *, client: Optional[Client] = None, user: Any = AMBIENT) -> "Database":
        """A lazy reference to a database by id.

        Returns:
            A database that loads the first time you read a field. Nothing is sent yet.

        Usage::

            db = noclick.Database.from_id("6c2e9a41-7d3b-4f15-8e0a-2b9c4d7f1e63")
            print(db.query("select count(*) as n from bookings").rows[0]["n"])
        """
        return cls._new(hints={"id": database_id}, client=client, user=user)

    @synced
    @classmethod
    async def get(cls, database_id: str, *, user: Any = AMBIENT, client: Optional[Client] = None) -> "Database":
        """Load a database by id now; an unknown id raises ``noclick.NotFound``.

        Returns:
            The database, loaded: its engine, size, table count and status.

        Usage::

            db = noclick.Database.get("6c2e9a41-7d3b-4f15-8e0a-2b9c4d7f1e63")
            print(db.name, db.engine, db.size_bytes, db.status)
        """
        database = cls.from_id(database_id, client=client, user=user)
        await database._ensure()
        return database

    @synced
    @classmethod
    async def list(
        cls, *, engine: Optional[Engine] = None, limit: Optional[int] = None, user_filter: Any = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> List["Database"]:
        """The current user's databases (the account's own outside ``as_user``,
        or those ``user_filter`` covers), branches included.

        Returns:
            Every matching database, newest first, fetched page by page.

        Usage:
            Your account's databases::

                for db in noclick.Database.list():
                    print(db.name, db.engine, db.size_bytes)

            Every user's Postgres databases::

                big = noclick.Database.list(engine="postgres", user_filter=noclick.ALL_USERS)
        """
        return await list_all(
            "/v1/databases", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            params={"engine": engine}, user=user, user_filter=user_filter, limit=limit, client=client,
        )

    @synced
    @classmethod
    async def list_page(
        cls, *, cursor: Optional[str] = None, limit: Optional[int] = None, engine: Optional[Engine] = None,
        user_filter: Any = None, user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> Page:
        """One page of databases; pass ``next_cursor`` back as ``cursor``.

        Returns:
            A page whose ``data`` holds the databases and whose ``next_cursor`` is ``None`` on the last page.

        Usage::

            page = noclick.Database.list_page(limit=50, user_filter=noclick.ALL_USERS)
            while True:
                for db in page.data:
                    print(db.user_id, db.name, db.size_bytes)
                if page.next_cursor is None:
                    break
                page = noclick.Database.list_page(limit=50, user_filter=noclick.ALL_USERS, cursor=page.next_cursor)
        """
        return await list_page(
            "/v1/databases", lambda raw, scope: cls._new(raw=raw, client=client, user=scope),
            params={"engine": engine}, user=user, user_filter=user_filter, cursor=cursor, limit=limit,
            client=client,
        )

    # --- hydration -------------------------------------------------------

    async def _load(self) -> Dict[str, Any]:
        database_id = self._known("id")
        if database_id:
            return await self._request("GET", f"/v1/databases/{database_id}")
        name = self._hints["name"]
        found = await self._in_app("database", name, self._create_with, branch_data=self._branch_data)
        if found is not None:
            return found
        page = await self._request("GET", "/v1/databases", params={"name": name}) or {}
        rows = [row for row in page.get("data") or [] if row.get("name") == name]
        if rows:
            return rows[0]
        if self._create_with is None:
            raise NotFound(
                f"No database is named {name!r}.",
                next_step="Create it with noclick.Database.create(...) or pass create_if_missing=True.",
                details={"name": name, "kind": "database"},
            )
        try:
            return await self._request("POST", "/v1/databases", json=self._create_with)
        except Conflict as exc:  # created concurrently
            if not exc.existing_id:
                raise
            return await self._request("GET", f"/v1/databases/{exc.existing_id}")

    async def _url(self, suffix: str = "") -> str:
        """This database's route; a reference by name is looked up (or created) first."""
        if not self._known("id"):
            await self._ensure()
        return f"/v1/databases/{self._known('id')}{suffix}"

    # --- SQL -------------------------------------------------------------

    @synced
    async def query(self, sql: str, params: Params = None) -> QueryResult:
        """Run a read: one ``select`` (or ``with ... select``) that changes nothing.
        It runs read-only, so a statement that writes raises ``noclick.InvalidRequest``;
        use ``execute`` for those. A result is at most 10 MB and a statement stops
        after 30 seconds. On Postgres, ``noclick.embed(:q, model)`` turns a parameter
        or a quoted text into a ``halfvec`` before the statement runs (up to 100
        distinct texts a request; not over ``connection_url``), so a read, an agent's
        ``query`` tool among them, can search by meaning without your code embedding
        first (billed as AI to the database's user).

        Returns:
            The rows as dicts, in ``rows`` or by iterating the result, with ``columns``, ``rows_read``
            and ``duration_ms``.

        Usage:
            Pass values as parameters, never in the SQL string::

                db = noclick.Database.from_name("orders")
                for row in db.query("select id, item, qty from orders where qty > ?", [2]):
                    print(row["id"], row["item"], row["qty"])

            Named parameters take a dict::

                db = noclick.Database.from_name("booking-db")
                result = db.query(
                    "select * from bookings where venue = :venue and starts_at >= :day",
                    {"venue": "Harbor Room", "day": "2026-10-01"},
                )
                print(result.columns, len(result), result.rows_read)

            Search by meaning in one statement, embedding the question in SQL::

                kb = noclick.Database.from_name("help-center")
                for row in kb.query(
                    "select id, title from articles "
                    "order by embedding <=> noclick.embed(:q, 'openrouter/openai/text-embedding-3-small') limit 5",
                    {"q": "how long do refunds take"},
                ):
                    print(row["id"], row["title"])
        """
        body = {**_statement(sql, params), "read_only": True}
        return QueryResult._from(await self._request("POST", await self._url("/query"), json=body))

    @synced
    async def execute(self, sql: str, params: Params = None) -> QueryResult:
        """Run one statement that writes: ``insert``, ``update``, ``delete`` or DDL
        (several go in a ``batch``).
        A SQLite database that would pass 10 GB raises ``noclick.QuotaExceeded``,
        whose next step is branching into Postgres. SQLite refuses virtual tables,
        so every database exports as plain SQL.

        Returns:
            What it did: ``rows_written``, ``last_row_id`` for an insert on SQLite, and the ``rows``
            a ``returning`` clause gave back.

        Usage::

            db = noclick.Database.from_name("orders", create_if_missing=True)
            db.execute("create table if not exists orders (id text primary key, item text, qty integer)")
            done = db.execute("insert into orders (id, item, qty) values (?, ?, ?)", ["o1", "bun", 3])
            print(done.rows_written)   # 1
        """
        return QueryResult._from(await self._request("POST", await self._url("/query"), json=_statement(sql, params)))

    @synced
    async def batch(self, statements: Sequence[Statement]) -> List[QueryResult]:
        """Run up to 100 statements in one transaction: all of them apply or none
        do. Each is the SQL alone or a ``(sql, params)`` pair.

        Returns:
            One ``QueryResult`` per statement, in order.

        Usage::

            db = noclick.Database.from_name("booking-db")
            moved, freed = db.batch([
                ("update bookings set slot = ? where id = ?", ["18:30", "b_41"]),
                ("update slots set taken = 0 where time = ?", ["18:00"]),
            ])
            print(moved.rows_written, freed.rows_written)
        """
        wire = [
            _statement(item, None) if isinstance(item, str) else _statement(item[0], item[1] if len(item) > 1 else None)
            for item in statements
        ]
        response = await self._request("POST", await self._url("/query"), json={"statements": wire}) or {}
        return [QueryResult._from(result) for result in response.get("results") or []]

    # --- schema ----------------------------------------------------------

    @synced
    async def migrate(
        self, migrations: Union[str, "os.PathLike[str]", Mapping[str, str]], *, dry_run: bool = False,
        seed: Union[None, str, "os.PathLike[str]"] = None,
    ) -> MigrationResult:
        """Apply the migrations the database hasn't run yet, in name order:
        ``migrations`` is a local directory (its ``*.sql`` files, read here) or a
        ``{name: sql}`` dict. They run in one transaction, so a failing migration
        applies none of them and raises ``noclick.InvalidRequest`` naming it. A name
        that already ran with different SQL raises ``noclick.Conflict``.
        ``dry_run=True`` reports what would run and changes nothing.

        ``seed`` is a SQL file that runs once, after the migrations and in their
        transaction, on a preview branch's database that holds none of production's
        data (a SQLite copy made without its rows, or one only the branch has), so the
        preview has something to show; it shows in ``applied`` and the ledger as
        ``(seed)``. Production never runs it. Without ``seed``, a ``seed.sql`` beside
        the migrations directory is the seed (``supabase/seed.sql`` beside
        ``supabase/migrations/`` is).

        Returns:
            The migrations applied now, and those still pending (all the new ones after a dry run).

        Usage:
            Keep migrations next to your code, named so they sort in order (``0001_init.sql``,
            ``0002_add_slots.sql``), and run them on every deploy::

                db = noclick.Database.from_name("booking-db", create_if_missing=True)
                result = db.migrate("migrations/")
                print(result.applied)   # ['0002_add_slots.sql'], or [] when there was nothing new

            Or pass them inline, and check first::

                db = noclick.Database.from_name("orders", create_if_missing=True)
                plan = db.migrate({"0001_init.sql": "create table orders (id text primary key, qty integer)"}, dry_run=True)
                print(plan.pending)

            Sample rows for every preview, from ``db/seed.sql`` beside ``db/migrations/``::

                db.migrate("db/migrations/")
        """
        body = compact(migrations=_migration_files(migrations), dry_run=True if dry_run else None,
                       seed=None if dry_run else _seed_sql(migrations, seed))
        return MigrationResult._from(await self._request("POST", await self._url("/migrations"), json=body))

    @synced
    async def migrations(self) -> List[Migration]:
        """The migrations this database has applied.

        Returns:
            Each applied migration with when it ran, oldest first.

        Usage::

            db = noclick.Database.from_name("booking-db")
            for migration in db.migrations():
                print(migration.name, migration.applied_at)
        """
        rows = await paginate(self._api, await self._url("/migrations"), user=self._call_scope())
        return [Migration._from(row) for row in rows]

    @synced
    async def schema(self) -> List[Table]:
        """The database's tables, their columns and row counts.

        Returns:
            Every table by name, each with its ``columns`` in order and its ``row_count``.

        Usage::

            db = noclick.Database.from_name("booking-db")
            for table in db.schema():
                print(table.name, table.row_count, [column.name for column in table.columns])
        """
        response = await self._request("GET", await self._url("/schema")) or {}
        return [Table._from(row) for row in response.get("data") or []]

    # --- time and copies -------------------------------------------------

    @synced
    async def restore(self, *, at: Union[datetime, str]) -> Operation:
        """Put the database back as it was at ``at`` (a timezone-aware ``datetime``),
        in place: anything written since is taken out. ``at`` must be within its
        history: 30 days on SQLite, 7 on Postgres. What it held just before is kept
        in the trash for 30 days as a database copy (the operation's
        ``kept_copy_id``): ``undo()`` on the operation, or restoring that
        ``TrashItem``, puts it back. While it runs, ``status`` is ``restoring`` and
        queries raise ``noclick.Conflict``. To look at the past without changing
        the present, ``branch`` at that time instead.

        Returns:
            An operation whose ``wait()`` gives this database, restored.

        Usage::

            from datetime import datetime, timedelta, timezone

            db = noclick.Database.from_name("booking-db")
            before = datetime.now(timezone.utc) - timedelta(hours=2)
            restored = db.restore(at=before).wait()
            print(restored.status)   # ready
        """
        payload = await self._request("POST", await self._url("/restore"), json={"at": iso_time(at)})
        return Operation._from_payload(
            payload, client=self._client, user=self._call_scope(), kind="database.restore", reader=_read_database,
        )

    @synced
    async def branch(
        self, name: str, *, at: Union[None, datetime, str] = None, engine: Optional[Engine] = None,
    ) -> Operation:
        """Copy the database into a new one called ``name``: as it is now, or as
        it was at ``at`` (within its history: 30 days on SQLite, 7 on Postgres).
        ``engine="postgres"`` branches a SQLite database into Postgres, the way past
        SQLite's 10 GB. The branch is a database of its own (``parent_id`` names this
        one) for the same user. While a SQLite database is copied, its ``status`` is
        ``branching`` and queries raise ``noclick.Conflict``.

        Returns:
            An operation whose ``wait()`` gives the new ``Database``.

        Usage:
            A copy to test a migration against before it touches production::

                db = noclick.Database.from_name("booking-db")
                preview = db.branch("booking-db-preview").wait()
                preview.migrate("migrations/")

            Move to Postgres when SQLite is too small; point your app at the new one once it's ready::

                db = noclick.Database.from_name("booking-db")
                bigger = db.branch("booking-pg", engine="postgres").wait()
                print(bigger.engine, bigger.connection_url(ttl_s=600))
        """
        body = compact(name=name, at=iso_time(at), engine=engine)
        payload = await self._request("POST", await self._url("/branches"), json=body)
        return Operation._from_payload(
            payload, client=self._client, user=self._call_scope(), kind="database.branch", reader=_read_database,
        )

    @synced
    async def branches(self) -> List["Database"]:
        """The databases branched from this one.

        Returns:
            Each branch as a ``Database``, newest first.

        Usage::

            db = noclick.Database.from_name("booking-db")
            for branch in db.branches():
                print(branch.name, branch.engine, branch.created_at)
        """
        rows = await paginate(self._api, await self._url("/branches"), user=self._call_scope())
        return [Database._new(raw=row, client=self._client, user=self._call_scope()) for row in rows]

    # --- access and lifecycle --------------------------------------------

    @synced
    async def connection_url(self, *, ttl_s: int = 3600, read_only: bool = False) -> str:
        """A Postgres connection string for tools that speak the wire protocol
        (``psql``, an ORM, a BI tool), with a password that stops working after
        ``ttl_s`` seconds (60 to 86,400), when any session still open on it ends.
        ``read_only=True`` connects as a role that can only read. A SQLite database
        has no wire protocol and raises ``noclick.NotAvailable``.

        Returns:
            A ``postgresql://`` URL with its short-lived credentials inside; treat it as a secret.

        Usage::

            import psycopg

            db = noclick.Database.from_name("analytics")
            with psycopg.connect(db.connection_url(ttl_s=600, read_only=True)) as conn:
                print(conn.execute("select count(*) from events").fetchone())
        """
        body = {"ttl_s": ttl_s, **({"read_only": True} if read_only else {})}
        response = await self._request("POST", await self._url("/connection_url"), json=body) or {}
        return response["url"]

    @synced
    async def export(self) -> Operation:
        """Export the database as SQL that recreates its schema and rows in any
        database of its engine: ``sqlite3 booking.db < databases/booking-db.sql``,
        or a ``pg_dump`` script for ``psql`` (NoClick's own ``noclick`` schema,
        owners and grants left out). Exporting a Postgres database wakes it, and
        its compute is billed as any use is.

        Returns:
            An operation whose ``wait()`` gives an ``ExportBundle``: a zip at ``url`` holding the dump.

        Usage::

            db = noclick.Database.from_name("booking-db")
            bundle = db.export().wait()
            print(bundle.url, bundle.expires_at)
        """
        payload = await self._request("POST", await self._url("/export"))
        return Operation._from_payload(
            payload, client=self._client, user=self._call_scope(), kind="database.export", reader=_read_export,
        )

    @synced
    async def delete(self) -> TrashItem:
        """Delete the database and its data: it goes to the trash, restorable for 30 days (its storage billed
        until it's purged), and its connection URLs stop working. One with branches raises
        ``noclick.Conflict`` naming them until you delete them, as does one an agent has in its tools.
        One an app binds goes to the trash too: the app keeps its binding, reaching nothing until you
        restore the database.

        Returns:
            Its ``TrashItem``: ``restore()`` puts it back, tables and rows with it.

        Usage::

            db = noclick.Database.from_name("booking-db-preview")
            db.delete()
        """
        raw = await self._request("DELETE", await self._url())
        return trashed(raw, client=self._client, user=self._call_scope())
