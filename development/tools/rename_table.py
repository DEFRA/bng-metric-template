"""Point a project's layers at a GeoPackage table under its new name.

A layer finds its table through `|layername=<table>` at the end of its
datasource. This rewrites that part of every datasource that names the old
table. The layer's own name, its id and everything else stay as they are.

    python3 development/tools/rename_table.py <project.qgz> <old> <new>

Rename the table in the GeoPackage as well, with GDAL, which also renames its
spatial index and triggers. Edits the text in place and leaves every other
byte alone, for the same reasons as qgz_actions.py. Running it twice changes
nothing.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qgz_actions import escape, read_project, write_project     # noqa: E402


def rename(xml, old, new):
    """Return (xml, count). The table name ends at `<`, `|` or `"`."""
    pattern = re.compile(r"\|layername=" + re.escape(escape(old)) + r'(?=[<|"])')
    return pattern.subn("|layername=" + escape(new).replace("\\", r"\\"), xml)


def main(argv):
    if len(argv) != 3:
        print("usage: rename_table.py <project.qgz> <old> <new>",
              file=sys.stderr)
        return 2
    project, old, new = argv
    qgs, payload = read_project(project)
    xml = payload[qgs].decode("utf-8")
    new_xml, count = rename(xml, old, new)
    if new_xml == xml:
        print(f"no change needed: {project}")
        return 0
    backup = write_project(project, qgs, payload, new_xml)
    print(f"pointed {count} datasource(s) at {new!r} in {project} "
          f"(backup: {backup})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
