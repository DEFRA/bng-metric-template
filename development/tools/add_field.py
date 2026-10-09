"""Add a column to a layer of the template: GeoPackage table and project XML.

The inverse of drop_field.py. A column added to the GeoPackage alone shows
in QGIS with no alias, policies, default, constraints or attribute-table
width, and at the end of the table, after the hidden lineage columns. This
puts the column where it belongs and copies each per-field element of the
same field from another layer, such as the baseline twin of a
post-intervention layer, so the two cannot drift.

    python3 development/tools/add_field.py <project.qgz> <field> \\
        --layer <name> --like <layer> --after <field> \\
        [--gpkg <layers.gpkg>] [--type TEXT] [--layer ... --like ... --after ...]

Each --layer takes the --like and --after given after it, so one run can add
the field to several layers. With --gpkg, the column is also added to each
layer's table, in place after the --after column. The table must be empty:
SQLite cannot insert a column in the middle of a table, so the table is
dropped and created again, with its triggers. The template ships empty.

The project XML is edited in place and every other byte is left alone, for
the same reasons as qgz_actions.py. Running it twice changes nothing.
"""
import argparse
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from drop_field import (ELEMENTS, LAYER_NAME, MAPLAYER,     # noqa: E402
                        element_pattern, section_spans)
from qgz_actions import read_project, write_project             # noqa: E402

ALIAS_INDEX = re.compile(r'(<alias\b(?:\s+[\w:-]+="[^"]*")*?\s+index=")(\d+)(")')


def find_element(section_text, tag, attribute, field):
    """The element naming the field in a section, with its leading indent."""
    pattern = re.compile(rf"[ \t]*{element_pattern(tag, attribute, field)}",
                         re.S)
    return pattern.search(section_text)


def section_text(block, section):
    spans = list(section_spans(block, section))
    return spans[0] if len(spans) == 1 else None


def insert_into_section(block, section, tag, attribute, field, after, source):
    """Put `source` after the element naming `after`, or at the section end.

    Returns (block, inserted). Nothing is inserted where the section already
    names the field, where the layer has no such section, or where the
    source layer has no element to copy.
    """
    span = section_text(block, section)
    if span is None or source is None:
        return block, False
    start, end = span
    text = block[start:end]
    if find_element(text, tag, attribute, field):
        return block, False
    anchor = find_element(text, tag, attribute, after)
    if anchor is not None:
        at = start + anchor.end()
        new = block[:at] + "\n" + source.rstrip() + block[at:]
    else:
        # No anchor: last in the section, indented like its closing tag.
        at = end
        closing_indent = re.search(r"[ \t]*$", block[:end]).group(0)
        new = (block[:at - len(closing_indent)] + source.strip("\n").rstrip()
               + "\n" + closing_indent + block[at:])
    return new, True


def renumber_aliases(block):
    """Number the aliases 0, 1, 2... in the order they are listed."""
    span = section_text(block, "aliases")
    if span is None:
        return block
    start, end = span
    counter = iter(range(10_000))
    text = ALIAS_INDEX.sub(
        lambda m: f"{m.group(1)}{next(counter)}{m.group(3)}", block[start:end])
    return block[:start] + text + block[end:]


def source_elements(block, field):
    """Section -> the element configuring the field, with its indent."""
    found = {}
    for section, tag, attribute in ELEMENTS:
        span = section_text(block, section)
        if span is None:
            continue
        match = find_element(block[span[0]:span[1]], tag, attribute, field)
        if match:
            found[section] = match.group(0)
    return found


def add_to_layer(block, field, after, sources):
    added = 0
    for section, tag, attribute in ELEMENTS:
        block, inserted = insert_into_section(
            block, section, tag, attribute, field, after, sources.get(section))
        added += inserted
    if added:
        block = renumber_aliases(block)
    return block, added


def add_column(gpkg, table, field, after, sql_type):
    """Insert the column after `after`, by creating the empty table again."""
    conn = sqlite3.connect(gpkg)
    try:
        names = [row[1] for row in conn.execute(
            f'PRAGMA table_info("{table}")')]
        if field in names:
            return False
        if after not in names:
            raise SystemExit(f"{table}: no column {after!r}")
        if conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]:
            raise SystemExit(f"{table} holds rows: add the column to an "
                             "empty table only")
        (create,) = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,)).fetchone()
        anchor = f'"{after}" '
        at = create.index(anchor)
        at = create.index(",", at) if "," in create[at:] else create.rindex(")")
        create = (create[:at] + f', "{field}" {sql_type}' + create[at:])
        triggers = [sql for (sql,) in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
            (table,))]
        with conn:
            conn.execute(f'DROP TABLE "{table}"')
            conn.execute(create)
            for sql in triggers:
                conn.execute(sql)
        conn.execute("VACUUM")
        return True
    finally:
        conn.close()


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Add a column to layers of the template.")
    parser.add_argument("project")
    parser.add_argument("field")
    parser.add_argument("--gpkg", help="the template's GeoPackage")
    parser.add_argument("--type", default="TEXT",
                        help="SQLite type of the new column (default TEXT)")
    parser.add_argument("--layer", action="append", default=[])
    parser.add_argument("--like", action="append", default=[])
    parser.add_argument("--after", action="append", default=[])
    args = parser.parse_args(argv)
    if not args.layer or not (len(args.layer) == len(args.like)
                              == len(args.after)):
        parser.error("give --like and --after once for each --layer")
    return args


def main(argv):
    args = parse_args(argv)
    targets = dict(zip(args.layer, zip(args.like, args.after)))

    if args.gpkg:
        for layer, (_like, after) in targets.items():
            if add_column(args.gpkg, layer, args.field, after, args.type):
                print(f"{layer}: added column {args.field!r} after {after!r}")

    qgs, payload = read_project(args.project)
    xml = payload[qgs].decode("utf-8")
    blocks = {}
    for match in MAPLAYER.finditer(xml):
        name = LAYER_NAME.search(match.group(0))
        if name:
            blocks[name.group(1)] = match.group(0)
    missing = sorted({*targets, *args.like} - set(blocks))
    if missing:
        print(f"no such layer: {', '.join(missing)}", file=sys.stderr)
        return 1

    def replace(match):
        block = match.group(0)
        name = LAYER_NAME.search(block)
        name = name.group(1) if name else ""
        if name not in targets:
            return block
        like, after = targets[name]
        sources = source_elements(blocks[like], args.field)
        block, count = add_to_layer(block, args.field, after, sources)
        if count:
            print(f"{name}: added {count} element(s) for {args.field!r}, "
                  f"copied from {like}")
        return block

    new_xml = MAPLAYER.sub(replace, xml)
    if new_xml == xml:
        print(f"no change needed: {args.project}")
        return 0
    backup = write_project(args.project, qgs, payload, new_xml)
    print(f"wrote {args.project} (backup: {backup})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
