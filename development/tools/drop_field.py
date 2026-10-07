"""Remove a field's configuration from the layers of a .qgz, by raw XML edit.

A column dropped from the GeoPackage leaves its configuration behind in the
project: the widget, the alias, the split and duplicate policies, the default,
the constraints, the attribute-table column and the form settings. QGIS reads
configuration for a column that no longer exists without complaint, so the
leftovers are never noticed and never cleaned up.

This removes every per-field element that names the field, layer by layer,
and leaves every other byte alone, for the same reasons as qgz_actions.py.
Button code is not touched: a button that reads the field must be edited on
its own. Anything else that still names the field afterwards is reported, not
removed.

    python3 development/tools/drop_field.py <project.qgz> <field> [--layer <name>]...

With no --layer, the field is removed from every layer that configures it.
Running it twice changes nothing.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qgz_actions import escape, read_project, write_project     # noqa: E402

MAPLAYER = re.compile(r"<maplayer\b.*?</maplayer>", re.S)
LAYER_NAME = re.compile(r"<layername>([^<]*)</layername>")

# Attribute by attribute rather than [^>]*, because QGIS leaves `>`
# unescaped inside an attribute value.
ATTRIBUTES = r'(?:\s+[\w:-]+="[^"]*")*'

# (section, element, attribute that holds the field name). Each search is
# confined to its section, so that a field called, say, "Key" cannot match an
# <Option name="Key"> inside a drop-down's configuration.
ELEMENTS = (
    ("fieldConfiguration", "field", "name"),
    ("aliases", "alias", "field"),
    ("splitPolicies", "policy", "field"),
    ("duplicatePolicies", "policy", "field"),
    ("mergePolicies", "policy", "field"),
    ("defaults", "default", "field"),
    ("constraints", "constraint", "field"),
    ("constraintExpressions", "constraint", "field"),
    ("expressionfields", "field", "name"),
    ("attributetableconfig", "column", "name"),
    ("editable", "field", "name"),
    ("labelOnTop", "field", "name"),
    ("reuseLastValue", "field", "name"),
)


def element_pattern(tag, attribute, field):
    """One element naming the field: self-closing, or with children.

    A child element never has the same tag as its parent here, so the body
    ends at the first closing tag and cannot run on into the next element.
    """
    named = (rf'(?=(?:\s+[\w:-]+="[^"]*")*?\s+{attribute}="'
             + re.escape(escape(field)) + '")')
    body = rf"(?:/>|>(?:(?!<{tag}\b).)*?</{tag}>)"
    return rf"<{tag}\b{named}{ATTRIBUTES}\s*{body}"


def remove_elements(text, tag, attribute, field):
    """Remove each matching element, with its line when it is alone on one."""
    element = element_pattern(tag, attribute, field)
    whole_line = re.compile(rf"^[ \t]*{element}[ \t]*\r?\n", re.S | re.M)
    text, lines = whole_line.subn("", text)
    text, inline = re.compile(element, re.S).subn("", text)
    return text, lines + inline


def section_spans(block, section):
    """Yield (start, end) of the content of each <section> in the block."""
    opening = re.compile(rf"<{section}{ATTRIBUTES}\s*>")
    for match in opening.finditer(block):
        close = block.find(f"</{section}>", match.end())
        if close >= 0:
            yield match.end(), close


def drop_from_layer(block, field):
    """Return the layer block without the field's configuration, and a count."""
    removed = 0
    for section, tag, attribute in ELEMENTS:
        pieces, last = [], 0
        for start, end in section_spans(block, section):
            text, count = remove_elements(block[start:end], tag, attribute, field)
            pieces += [block[last:start], text]
            last = end
            removed += count
        block = "".join(pieces) + block[last:]
    return block, removed


def leftovers(block, field):
    """Elements that still name the field in an attribute of their own.

    A quote inside a button's code is written `&quot;`, so a raw quoted name
    can only be an attribute of a real element. <Option> is left out: its
    names are the keys of a widget's settings, and a field name in its value
    belongs to the layer that a drop-down reads, not to this one.
    """
    value = re.escape(escape(field))
    found = re.finditer(
        rf'<([\w:-]+)\b{ATTRIBUTES}?\s+[\w:-]+="{value}"', block)
    return sorted({match.group(1) for match in found} - {"Option"})


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Remove a field's configuration from a .qgz project.")
    parser.add_argument("project")
    parser.add_argument("field")
    parser.add_argument("--layer", action="append", default=[],
                        help="layer name; repeat for more than one "
                             "(default: every layer)")
    return parser.parse_args(argv)


def main(argv):
    args = parse_args(argv)
    qgs, payload = read_project(args.project)
    xml = payload[qgs].decode("utf-8")
    wanted = set(args.layer)
    seen = set()
    total = 0

    def replace(match):
        nonlocal total
        block = match.group(0)
        name = LAYER_NAME.search(block)
        name = name.group(1) if name else ""
        if wanted and name not in wanted:
            return block
        seen.add(name)
        block, count = drop_from_layer(block, args.field)
        if count:
            print(f"{name}: removed {count} element(s) for {args.field!r}")
        total += count
        for tag in leftovers(block, args.field):
            print(f"{name}: left in place, <{tag}> still names {args.field!r}")
        return block

    new_xml = MAPLAYER.sub(replace, xml)
    missing = sorted(wanted - seen)
    if missing:
        print(f"no such layer: {', '.join(missing)}", file=sys.stderr)
        return 1
    if new_xml == xml:
        print(f"no change needed: {args.project}")
        return 0
    backup = write_project(args.project, qgs, payload, new_xml)
    print(f"removed {total} element(s) from {args.project} (backup: {backup})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
