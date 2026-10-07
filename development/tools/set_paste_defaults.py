"""Give a pasted post-intervention feature the lineage the Copy button writes.

A feature pasted into a post-intervention layer is filled from the default
value expressions of its columns. This writes those expressions for the
lineage columns: the refs, the parent's hidden id and shape, and the values
that Copy sets on the row it makes. They take their values from the one
baseline feature whose geometry is exactly the same as the pasted feature's
(see paste_lineage.py).

The Retention Category and Proposed columns that are filtered drop-downs
already have a reset rule, owned by reset_stale_dropdowns.py. That tool
writes their pre-fill, so this one leaves them alone.

Each default here is applied only when a feature is created, never on a
later edit. A lineage value recomputed on an edit would be lost: a moved
vertex makes the shape differ from the baseline, and the lookup would then
give NULL.

    python3 development/tools/set_paste_defaults.py [--check] <project.qgz>

Edits the `<default>` elements in place and leaves every other byte alone,
for the same reasons as qgz_actions.py. Running it twice changes nothing. It
refuses to replace a default it did not write, and then writes nothing. With
--check it writes nothing, lists what it would change, and exits 1 if
anything would change.
"""
import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import paste_lineage                                            # noqa: E402
from paste_lineage import (RETAINED, UUID, WKT_DECIMALS,        # noqa: E402
                           lookup, prefill_gate)
from qgz_actions import escape, read_project, write_project     # noqa: E402
from reset_stale_dropdowns import default_element               # noqa: E402

CHECK = "--check"
NULL = "NULL"
# The Copy button rounds Baseline Length to the millimetre.
LENGTH_DECIMALS = 3
LENGTH = f"round(length($geometry), {LENGTH_DECIMALS})"
# The reset rules of reset_stale_dropdowns.py all contain this. A default
# that has it belongs to that tool.
RESET_MARKER = "attribute(@parent"
EXPRESSION = re.compile(r'\bexpression="([^"]*)"')
APPLY_ON_UPDATE = re.compile(r'\bapplyOnUpdate="([^"]*)"')

# Column -> the baseline expression whose value it takes. {ref} is the ref
# column of the baseline layer. The same on every post-intervention layer.
LOOKUPS = (
    ("Habitat Ref", '"{ref}"'),
    ("Parent Ref", '"{ref}"'),
    ("parent_uuid", UUID),
    ("parent_geom", f"geom_to_wkt($geometry, {WKT_DECIMALS})"),
)

# Layer -> (column, value when pasted from the baseline, value otherwise).
# Copy writes the same values, except where Copy has no "otherwise".
AREA = (("Retention Category", RETAINED, NULL),)
LINEAR = (("Baseline Length", LENGTH, NULL),)
GATED = {
    "Area Habitats Post-Intervention": AREA,
    "Vertical Area Habitats Post-Intervention": AREA,
    "Hedgerows Post-Intervention": LINEAR,
    "Watercourses Post-Intervention": LINEAR,
    "Individual Trees Post-Intervention":
        (("Category", "'Existing'", "'Newly Planted'"),),
}

# Defaults the template had before this tool, which it may replace.
REPLACES = {
    ("Individual Trees Post-Intervention", "Category"): "'Newly Planted'",
}


def wanted_defaults(layer, baseline_id, ref):
    """[(column, expression)] for one post-intervention layer."""
    found = [(field, lookup(baseline_id, expression.format(ref=ref)))
             for field, expression in LOOKUPS]
    found += [(field,
               f"if({prefill_gate(baseline_id, field)}, {value}, {otherwise})")
              for field, value, otherwise in GATED.get(layer, ())]
    return found


def may_replace(layer, field, current):
    """True if the current default is empty, from the template, or ours."""
    if not current or current == REPLACES.get((layer, field)):
        return True
    return paste_lineage.MARKER in current and RESET_MARKER not in current


def rewrite_layer(layer, block, fields, errors):
    """Return the layer block with its defaults set, and a count of changes."""
    changed = 0
    for field, expression in fields:
        found = default_element(field).search(block)
        if found is None:
            errors.append(f"{layer}: no <default> element for {field!r}")
            continue
        current = html.unescape(EXPRESSION.search(found.group(0)).group(1))
        update = APPLY_ON_UPDATE.search(found.group(0))
        if current == expression and update and update.group(1) == "0":
            continue
        if not may_replace(layer, field, current):
            errors.append(f"{layer}: {field!r} already has a default this "
                          f"tool did not write: {current}")
            continue
        element = (f'<default expression="{escape(expression)}" '
                   f'field="{escape(field)}" applyOnUpdate="0"/>')
        block = block[:found.start()] + element + block[found.end():]
        changed += 1
    return block, changed


def set_defaults(xml):
    """Return (xml, report lines, errors). The xml is usable only if no errors."""
    known = paste_lineage.layers(xml)
    report, errors = [], []

    def replace(match):
        block = match.group(0)
        name = paste_lineage.LAYER_NAME.search(block)
        parent = paste_lineage.parent_of(name.group(1), known) if name else None
        if parent is None:
            return block
        baseline_id, _names, ref = parent
        fields = wanted_defaults(name.group(1), baseline_id, ref)
        block, count = rewrite_layer(name.group(1), block, fields, errors)
        report.append(f"{name.group(1)}: {count} of {len(fields)} "
                      "default(s) to write")
        return block

    new_xml = paste_lineage.MAPLAYER.sub(replace, xml)
    missing = sorted(set(paste_lineage.PARENTS) - set(known))
    errors += [f"no layer named {name!r}" for name in missing]
    return new_xml, report, errors


def main(argv):
    check = CHECK in argv
    paths = [a for a in argv if a != CHECK]
    if len(paths) != 1:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print("usage: set_paste_defaults.py [--check] <project.qgz>",
              file=sys.stderr)
        return 2
    project = paths[0]
    qgs, payload = read_project(project)
    xml = payload[qgs].decode("utf-8")
    new_xml, report, errors = set_defaults(xml)
    print("\n".join(report))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        print("nothing written", file=sys.stderr)
        return 1
    if new_xml == xml:
        print(f"no change needed: {project}")
        return 0
    if check:
        print(f"paste defaults out of date in {project}")
        return 1
    backup = write_project(project, qgs, payload, new_xml)
    print(f"wrote the paste defaults to {project} (backup: {backup})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
