#!/usr/bin/env python3
"""
query_tng — helper for querying the TNG SQLite database.

Dual-purpose: works as a CLI tool AND as an importable Python module.

Read-only by default. Pass --write (CLI) or write=True (module) to modify the
database; without it the connection is opened read-only and any write fails
before it can touch anything.

Quoting
-------
SQL passed as a shell argument has to survive two layers of quoting -- the
shell's and SQL's -- and the database has ten episode titles containing an
apostrophe ("Captain's Holiday", "Data's Day", ...). Prefer the paths that
remove the shell layer entirely:

    # best: no shell quoting at all
    python query_tng.py --stdin <<'SQL'
    SELECT season, episode_number FROM episodes
     WHERE title = 'Captain''s Holiday';
    SQL

    # also fine: SQL lives in a file
    python query_tng.py --sql-file my_query.sql

    # from Python, no shell involved
    from query_tng import query
    query("SELECT * FROM episodes WHERE title = \\"Data's Day\\"")

    # works, but you must escape for the shell AND for SQL
    python query_tng.py "SELECT 1"

Other CLI usage:
    python query_tng.py --table episodes
    python query_tng.py --table episodes --format json
    python query_tng.py --schema
    python query_tng.py --tables
    python query_tng.py "SELECT ..." --all          # no row cap

As a module:
    import sys; sys.path.insert(0, "<repo dir>")
    from query_tng import query, db_path, schema
    query("SELECT season, episode_number, title FROM episodes WHERE season=2")
    rows = query("SELECT ...", fetch='rows')    # list of dicts
    rows = query("SELECT ...", fetch='raw')     # list of sqlite3.Row
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

# Auto-detect database path: same directory as this script
SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = str(SCRIPT_DIR / "tng_data.db")

# Lower-case alias: the module's own documentation refers to `db_path`, so
# anything written against those docs imports this name.
db_path = DB_PATH

# CLI default. Dumping every row of line_counts (2,672) or keyword_counts
# (2,528) is rarely wanted and, for an LLM caller, is mostly wasted context.
DEFAULT_LIMIT = 100


def get_connection(db_path: str = DB_PATH, write: bool = False) -> sqlite3.Connection:
    """
    Open a SQLite connection.

    Read-only unless write=True. A read-only connection is a real guarantee
    from SQLite rather than a convention: an accidental DELETE or DROP fails
    instead of quietly succeeding.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")

    if write:
        conn = sqlite3.connect(db_path)
    else:
        conn = sqlite3.connect(f"file:{Path(db_path).as_uri()[7:]}?mode=ro", uri=True)

    conn.row_factory = sqlite3.Row  # enables dict-like access
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _is_noise(statement: str) -> bool:
    """True if a statement is only comments and whitespace."""
    stripped = re.sub(r'/\*.*?\*/', ' ', statement, flags=re.S)
    stripped = re.sub(r'--[^\n]*', ' ', stripped)
    return not stripped.strip()


def split_statements(sql: str) -> list:
    """
    Split SQL into individual statements.

    sqlite3.Connection.execute() refuses more than one statement, which makes
    any .sql file with a couple of queries -- or a trailing comment -- fail.
    Splitting on sqlite3.complete_statement respects semicolons inside string
    literals, which a naive sql.split(';') does not.
    """
    statements, buffer = [], ''
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if not _is_noise(buffer):
                statements.append(buffer)
            buffer = ''
    if buffer.strip() and not _is_noise(buffer):
        statements.append(buffer)
    return statements


def _render_table(rows, truncated: bool, elapsed: float, limit):
    """Print rows as an aligned text table."""
    if not rows:
        print("(no rows)")
        return

    headers = rows[0].keys()
    widths = {}
    for h in headers:
        longest = max((len(str(r[h])) if r[h] is not None else 4) for r in rows)
        widths[h] = max(min(max(len(str(h)), longest), 60), 3)

    print(" | ".join(str(h).ljust(widths[h]) for h in headers))
    print("-+-".join("-" * widths[h] for h in headers))

    for row in rows:
        cells = []
        for h in headers:
            value = str(row[h]) if row[h] is not None else "NULL"
            if len(value) > widths[h]:
                value = value[:widths[h] - 3] + "..."
            cells.append(value.ljust(widths[h]))
        print(" | ".join(cells))

    note = f"\n{len(rows)} row(s) in {elapsed:.3f}s"
    if truncated:
        note += f" — capped at {limit}; pass --all (or limit=None) for the rest"
    print(note)


def query(sql: str, db_path: str = DB_PATH, fetch: str = "print",
          write: bool = False, limit=None):
    """
    Execute SQL and return or print results.

    Args:
        sql:     One or more SQL statements.
        db_path: Path to the database file (auto-detected by default).
        fetch:   'print'  — formatted table, returns None (default)
                 'rows'   — list of dicts
                 'raw'    — list of sqlite3.Row
                 'json'   — print JSON, returns None
                 'csv'    — print CSV, returns None
                 'scalar' — first column of the first row
                 'none'   — execute only, returns rowcount
        write:   Open the database writable. Required for INSERT/UPDATE/DELETE.
        limit:   Cap the rows returned or printed. None means no cap.

    Results come from the last statement that produced any; earlier statements
    still execute, so setup-then-select in one file works.
    """
    conn = get_connection(db_path, write=write)
    try:
        statements = split_statements(sql)
        if not statements:
            raise ValueError("no SQL statement found (only comments?)")

        start = time.perf_counter()
        rows, truncated, rowcount, returned_rows = [], False, 0, False

        for statement in statements:
            cur = conn.execute(statement)
            # cur.description is None only when a statement returns no result
            # set. Testing this beats guessing from the leading keyword: a
            # comment, EXPLAIN, or VALUES ahead of a SELECT all defeat that.
            if cur.description is None:
                rowcount += max(cur.rowcount, 0)
                continue

            returned_rows = True
            if limit is None:
                rows = cur.fetchall()
                truncated = False
            else:
                rows = cur.fetchmany(limit + 1)
                truncated = len(rows) > limit
                rows = rows[:limit]

        elapsed = time.perf_counter() - start

        if not returned_rows:
            if write:
                conn.commit()
            if fetch == "none":
                return rowcount
            print(f"{rowcount} row(s) affected ({elapsed:.3f}s)")
            return rowcount

        if write:
            conn.commit()

        if fetch == "scalar":
            return rows[0][0] if rows else None
        if fetch == "raw":
            return rows
        if fetch == "rows":
            return [dict(r) for r in rows]
        if fetch == "none":
            return len(rows)

        if fetch == "json":
            print(json.dumps([dict(r) for r in rows], indent=2, default=str))
            return None

        if fetch == "csv":
            if not rows:
                print("(no rows)")
                return None
            headers = rows[0].keys()
            print(",".join(headers))
            for row in rows:
                print(",".join(
                    '' if row[h] is None else str(row[h]) for h in headers))
            return None

        _render_table(rows, truncated, elapsed, limit)
        return None

    except sqlite3.Error as exc:
        # Re-raised for module callers; main() turns it into a clean exit.
        print(f"SQL error: {exc}", file=sys.stderr)
        print(f"Query: {sql.strip()}", file=sys.stderr)
        raise
    finally:
        conn.close()


def _objects(conn, kinds=('table', 'view')):
    placeholders = ','.join('?' for _ in kinds)
    return conn.execute(
        f"SELECT name, type, sql FROM sqlite_master WHERE type IN ({placeholders}) "
        "AND name NOT LIKE 'sqlite_%' ORDER BY type, name", kinds).fetchall()


def schema(db_path: str = DB_PATH):
    """
    Print the schema of every table and view.

    Views are included deliberately: episode_index, episode_slots,
    category_counts and friends are the objects most worth querying, and
    filtering to type='table' hides them.
    """
    conn = get_connection(db_path)
    try:
        for obj in _objects(conn):
            print(f"\n{'=' * 60}")
            print(f"{obj['type'].upper()}: {obj['name']}")
            print('=' * 60)
            print(obj['sql'])

            count = conn.execute(
                f"SELECT COUNT(*) FROM [{obj['name']}]").fetchone()[0]
            print(f"\n  Row count: {count}")

            indexes = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND tbl_name=? ORDER BY name", (obj['name'],)).fetchall()
            if indexes:
                print("  Indexes:")
                for index in indexes:
                    print(f"    {index['name']}")
            print()
    finally:
        conn.close()


def list_tables(db_path: str = DB_PATH):
    """Print every table and view with its row count."""
    conn = get_connection(db_path)
    try:
        objects = _objects(conn)
        print(f"{'Name':<30} {'Kind':<6} {'Rows':>8}")
        print("-" * 46)
        for obj in objects:
            count = conn.execute(
                f"SELECT COUNT(*) FROM [{obj['name']}]").fetchone()[0]
            print(f"{obj['name']:<30} {obj['type']:<6} {count:>8}")
        print(f"\nDatabase: {db_path}")
    finally:
        conn.close()


def resolve_table(db_path: str, name: str) -> str:
    """Check a --table argument names a real table or view."""
    conn = get_connection(db_path)
    try:
        known = [o['name'] for o in _objects(conn)]
    finally:
        conn.close()
    if name in known:
        return name
    matches = [k for k in known if k.lower() == name.lower()]
    if matches:
        return matches[0]
    raise ValueError(f"no table or view named {name!r}. Available: "
                     + ", ".join(known))


def main():
    parser = argparse.ArgumentParser(
        description="Query the TNG SQLite database (read-only by default).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python query_tng.py --tables
  python query_tng.py --schema
  python query_tng.py --table episodes --format json
  python query_tng.py "SELECT title FROM episodes WHERE season=2"

  # avoids shell quoting entirely -- preferred for anything with apostrophes
  python query_tng.py --stdin <<'SQL'
  SELECT season, episode_number FROM episodes
   WHERE title = 'Captain''s Holiday';
  SQL
        """
    )
    parser.add_argument("sql", nargs="?", help="SQL query to execute")
    parser.add_argument("--table", "-t", help="Dump all rows from a table or view")
    parser.add_argument("--sql-file", help="Read SQL from a file ('-' for stdin)")
    parser.add_argument("--stdin", action="store_true", help="Read SQL from stdin")
    parser.add_argument("--schema", action="store_true", help="Print database schema")
    parser.add_argument("--tables", action="store_true",
                        help="List all tables and views with row counts")
    parser.add_argument("--format", "-f", choices=["table", "json", "csv"],
                        default="table", help="Output format (default: table)")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"Max rows to show (default: {DEFAULT_LIMIT})")
    parser.add_argument("--all", action="store_true",
                        help="Show every row, ignoring --limit")
    parser.add_argument("--write", action="store_true",
                        help="Open the database writable (required to modify it)")
    parser.add_argument("--db", default=DB_PATH,
                        help="Database path (auto-detected by default)")
    args = parser.parse_args()

    try:
        if args.schema:
            schema(args.db)
            return 0
        if args.tables:
            list_tables(args.db)
            return 0

        if args.table:
            sql = f"SELECT * FROM [{resolve_table(args.db, args.table)}]"
        elif args.stdin or args.sql_file == '-':
            sql = sys.stdin.read()
        elif args.sql_file:
            sql = Path(args.sql_file).read_text(encoding='utf-8')
        elif args.sql:
            sql = args.sql
        else:
            parser.print_help()
            return 0

        fetch = {"json": "json", "csv": "csv"}.get(args.format, "print")
        query(sql, db_path=args.db, fetch=fetch, write=args.write,
              limit=None if args.all else args.limit)
        return 0

    except (sqlite3.Error, ValueError, FileNotFoundError, OSError) as exc:
        # Clean one-line failure rather than a traceback for the caller to parse.
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
