"""Declare the width of each text column in the template's GeoPackage.

Each text column of a feature table is declared TEXT(n), where n is the most
characters it holds: 99 for references, drop-downs and Location, 999 for
Comment and the other site details. Spatial risk category is the one
drop-down at 255: two intertidal values of its Habitats list are 101 and 115
characters long. GDAL, and so QGIS, reads n as the field width. The lineage keys and the parent shape stay TEXT, with no limit. The
limits are TEXT_LIMITS in plugin/bng_template_convert/gpkg_common.py, the one
list of them, which the plugin also reads.

    python3 development/tools/set_text_widths.py [--check] <gpkg>

SQLite keeps a table's definition as text in sqlite_master, and does not
enforce a declared width. TEXT(n) has the same type affinity as TEXT, so only
the text of the definitions changes: no table is created again, and no row,
index, trigger, metadata record or other table is touched. The edit is made
on a copy of the file, which must pass "PRAGMA integrity_check" and declare
every width before it replaces the file. A failure leaves the file as it was.

A text column that is not in TEXT_LIMITS stops the run before anything is
written: add it to the list first. Running it twice changes nothing. With
--check it writes nothing, lists what it would change, and exits 1 if
anything would change.
"""
import argparse
import os
import re
import shutil
import sqlite3
import sys
import tempfile

PLUGIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", "..", "plugin", "bng_template_convert")
sys.path.insert(0, os.path.normpath(PLUGIN_DIR))

import gpkg_common                                             # noqa: E402

# A declared text type: TEXT, or TEXT(n). Any case, as SQLite reads it.
TEXT_DECLARATION = re.compile(r"TEXT(?:\s*\(\s*\d+\s*\))?\Z", re.I)


def feature_tables(conn):
    return [name for (name,) in conn.execute(
        "SELECT table_name FROM gpkg_contents WHERE data_type = 'features' "
        "ORDER BY table_name")]


def text_columns(conn, table):
    """(column, declared type) for each text column of the table."""
    return [(row[1], row[2]) for row in conn.execute(
        f"PRAGMA table_info({gpkg_common.quote_ident(table)})")
        if TEXT_DECLARATION.match(row[2] or "")]


def definition_pattern(column):
    """The column's name and declared text type in a CREATE TABLE text."""
    return re.compile(
        re.escape(gpkg_common.quote_ident(column))
        + r"(\s+)TEXT(?:\s*\(\s*\d+\s*\))?(?=\s*[,)])", re.I)


def plan(conn):
    """Return ({table: new CREATE TABLE text}, changes, errors).

    Use the plan only if there are no errors.
    """
    new_sql, changes, errors = {}, [], []
    for table in feature_tables(conn):
        (sql,) = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,)).fetchone()
        updated = sql
        for column, declared in text_columns(conn, table):
            if column not in gpkg_common.TEXT_LIMITS:
                errors.append(f"{table}: {column!r} is not in TEXT_LIMITS "
                              "of gpkg_common.py")
                continue
            wanted = gpkg_common.text_type(column)
            if declared == wanted:
                continue
            pattern = definition_pattern(column)
            if len(pattern.findall(updated)) != 1:
                errors.append(f"{table}: cannot find the definition of "
                              f"{column!r} exactly once")
                continue
            updated = pattern.sub(
                lambda match, wanted=wanted: (
                    f"{gpkg_common.quote_ident(column)}{match.group(1)}"
                    f"{wanted}"),
                updated)
            changes.append(f"{table}: {column!r} {declared} -> {wanted}")
        if updated != sql:
            new_sql[table] = updated
    return new_sql, changes, errors


def rewrite_definitions(path, new_sql):
    """Put the new CREATE TABLE texts into sqlite_master of the file.

    The schema version goes up by one, so that every connection reads the
    definitions again.
    """
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        # Some builds of Python open SQLite in defensive mode, which refuses
        # any write to sqlite_master. Turn it off for this connection only.
        if hasattr(conn, "setconfig"):
            conn.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, False)
        (version,) = conn.execute("PRAGMA schema_version").fetchone()
        conn.execute("BEGIN")
        try:
            conn.execute("PRAGMA writable_schema = ON")
            for table, sql in new_sql.items():
                conn.execute(
                    "UPDATE sqlite_master SET sql = ? "
                    "WHERE type = 'table' AND name = ?", (sql, table))
            conn.execute(f"PRAGMA schema_version = {version + 1}")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.execute("PRAGMA writable_schema = OFF")
    finally:
        conn.close()


def verify(path):
    """Errors in the rewritten file: integrity, or a width not declared."""
    conn = sqlite3.connect(path)
    try:
        result = [row[0] for row in conn.execute("PRAGMA integrity_check")]
        errors = [] if result == ["ok"] else [f"integrity check: {line}"
                                               for line in result]
        _new_sql, changes, plan_errors = plan(conn)
        return errors + plan_errors + [f"not written: {line}"
                                       for line in changes]
    finally:
        conn.close()


def write(path, new_sql):
    """Rewrite a copy beside the file, check it, then put it in its place."""
    folder = os.path.dirname(os.path.abspath(path))
    handle, copy = tempfile.mkstemp(prefix=".set_text_widths-",
                                    suffix=".gpkg", dir=folder)
    os.close(handle)
    try:
        shutil.copy2(path, copy)
        rewrite_definitions(copy, new_sql)
        errors = verify(copy)
        if errors:
            return errors
        os.replace(copy, path)
        return []
    finally:
        if os.path.exists(copy):
            os.remove(copy)


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("gpkg", help="the template's GeoPackage")
    parser.add_argument("--check", action="store_true",
                        help="write nothing; exit 1 if a change is needed")
    args = parser.parse_args(argv)
    if not os.path.isfile(args.gpkg):
        raise SystemExit(f"no such file: {args.gpkg}")

    conn = sqlite3.connect(gpkg_common.read_only_uri(args.gpkg), uri=True)
    try:
        new_sql, changes, errors = plan(conn)
    finally:
        conn.close()
    if errors:
        print("\n".join(errors), file=sys.stderr)
        print("nothing written", file=sys.stderr)
        return 1
    for line in changes:
        print(line)
    if not changes:
        print(f"no change needed: every text column declares its width in "
              f"{args.gpkg}")
        return 0
    if args.check:
        print(f"{len(changes)} text column(s) to declare in {args.gpkg}")
        return 1
    errors = write(args.gpkg, new_sql)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        print("nothing written", file=sys.stderr)
        return 1
    print(f"declared {len(changes)} text column width(s) in "
          f"{len(new_sql)} table(s) of {args.gpkg}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
