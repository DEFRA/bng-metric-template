"""Record the template version in the template's GeoPackage.

The BNG service reads the record to know which template, and which version
of it, a file comes from. The version is TEMPLATE_VERSION in
plugin/bng_template_convert/gpkg_common.py, which the plugin also writes.
Raise it there, then run this tool. "Template version" in MAINTAINERS.md says
when to raise it.

    python3 development/tools/set_template_version.py [--check] <gpkg>

Replaces any record that is there, so the file holds exactly one, and leaves
every table and all other metadata alone. Running it twice changes nothing.
With --check it writes nothing, says what it would change, and exits 1 if
anything would change.
"""
import argparse
import os
import sqlite3
import sys

PLUGIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", "..", "plugin", "bng_template_convert")
sys.path.insert(0, os.path.normpath(PLUGIN_DIR))

import gpkg_common                                             # noqa: E402


def recorded(conn):
    """The recorded version, or a sentence saying why there is none."""
    try:
        record = gpkg_common.read_template_version(conn)
    except ValueError as error:
        return None, str(error)
    if record is None:
        return None, "no template version recorded"
    if record["template"] != gpkg_common.TEMPLATE_NAME:
        return None, f"records template {record['template']!r}"
    return record["version"], None


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("gpkg", help="the template's GeoPackage")
    parser.add_argument("--check", action="store_true",
                        help="write nothing; exit 1 if a change is needed")
    args = parser.parse_args(argv)
    if not os.path.isfile(args.gpkg):
        raise SystemExit(f"no such file: {args.gpkg}")

    wanted = gpkg_common.TEMPLATE_VERSION
    conn = sqlite3.connect(args.gpkg)
    try:
        version, problem = recorded(conn)
        if version == wanted:
            print(f"no change needed: version {wanted} is recorded")
            return 0
        found = problem or f"version {version} is recorded"
        if args.check:
            print(f"{found}; would record version {wanted}")
            return 1
        gpkg_common.write_template_version(conn, wanted)
        conn.commit()
    finally:
        conn.close()
    print(f"{found}; recorded version {wanted} in {args.gpkg}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
