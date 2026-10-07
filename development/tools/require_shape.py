"""Refuse a row with no shape on every data layer.

Copy Layer, in the Layers panel, copies the layer's definition, not its
features. It leaves the layer's XML on the clipboard as text, and Paste
Features then makes one row from each line of it: thousands of rows with no
shape and every column blank. A habitat row with no shape has no area or
length, so it is never valid.

This gives the ref column of each data layer a hard constraint that the row
has a shape. QGIS checks it when features are pasted. A paste of rows with no
shape opens the Fix Pasted Features dialog, where Discard All drops them,
instead of adding them. A drawn, copied or pasted feature always has a shape, so the
constraint never stops real work.

    python3 development/tools/require_shape.py [--check] <project.qgz>

Edits the constraint elements in place and leaves every other byte alone, for
the same reasons as qgz_actions.py. Running it twice changes nothing. It
refuses to replace an expression constraint it did not write, and then writes
nothing. With --check it writes nothing, lists what it would change, and exits
1 if anything would change.
"""
import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qgz_actions import escape, read_project, write_project     # noqa: E402

CHECK = "--check"
# Layer -> the column that carries the constraint: the first one a surveyor
# sees, so the message shows beside the row's ref.
LAYERS = {
    "Area Habitats Baseline": "Habitat Ref",
    "Area Habitats Post-Intervention": "Habitat Ref",
    "Hedgerows Baseline": "Habitat Ref",
    "Hedgerows Post-Intervention": "Habitat Ref",
    "Individual Trees Baseline": "Habitat Ref",
    "Individual Trees Post-Intervention": "Habitat Ref",
    "Vertical Area Habitats Baseline": "Habitat Ref",
    "Vertical Area Habitats Post-Intervention": "Habitat Ref",
    "Watercourses Baseline": "Habitat Ref",
    "Watercourses Post-Intervention": "Habitat Ref",
    "Red Line Boundary": "Site Name",
}
EXPRESSION = "$geometry IS NOT NULL"
DESCRIPTION = ("Every row needs a shape. To copy features, select them and "
               "use Copy Features on the Edit menu. Copy Layer copies the "
               "layer, not its features.")
# QgsFieldConstraints: ConstraintExpression = 4, ConstraintStrengthHard = 1.
EXPRESSION_FLAG = 4
HARD = "1"

MAPLAYER = re.compile(r"<maplayer\b.*?</maplayer>", re.S)
LAYER_NAME = re.compile(r"<layername>([^<]*)</layername>")


def element(section, field, block):
    """The one element in <section> of this layer block for this field."""
    body = re.search(rf"<{section}>.*?</{section}>", block, re.S)
    if body is None:
        raise SystemExit(f"no <{section}> in the layer")
    # QGIS leaves > unescaped in an attribute, so step over quoted values.
    attrs = r'(?:[^>"]|"[^"]*")*'
    pattern = re.compile(rf'<constraint\b{attrs}\bfield="{re.escape(escape(field))}"'
                         rf"{attrs}/>")
    found = [m for m in pattern.finditer(body.group(0))]
    if len(found) != 1:
        raise SystemExit(f"{len(found)} <{section}> entries for {field!r}")
    start = body.start() + found[0].start()
    return start, start + len(found[0].group(0)), found[0].group(0)


def set_attribute(tag, name, value):
    return re.sub(rf'\b{name}="[^"]*"', f'{name}="{value}"', tag, count=1)


def require(block, layer, field, errors):
    """Return the block with the constraint set on this field."""
    start, end, tag = element("constraints", field, block)
    flags = int(re.search(r'\bconstraints="(\d+)"', tag).group(1))
    new_tag = set_attribute(tag, "constraints", flags | EXPRESSION_FLAG)
    new_tag = set_attribute(new_tag, "exp_strength", HARD)
    block = block[:start] + new_tag + block[end:]

    start, end, tag = element("constraintExpressions", field, block)
    current = html.unescape(re.search(r'\bexp="([^"]*)"', tag).group(1))
    if current and current != EXPRESSION:
        errors.append(f"{layer} / {field}: already has the constraint "
                      f"{current}")
        return block
    new_expr = set_attribute(tag, "exp", escape(EXPRESSION))
    new_expr = set_attribute(new_expr, "desc", escape(DESCRIPTION))
    return block[:start] + new_expr + block[end:]


def rewrite(xml):
    """Return (xml, changed layers, errors). Use the xml only if no errors."""
    changed, errors, seen = [], [], set()

    def layer(match):
        block = match.group(0)
        name = LAYER_NAME.search(block)
        if name is None or name.group(1) not in LAYERS:
            return block
        seen.add(name.group(1))
        new_block = require(block, name.group(1), LAYERS[name.group(1)],
                               errors)
        if new_block != block:
            changed.append(name.group(1))
        return new_block

    new_xml = MAPLAYER.sub(layer, xml)
    errors += [f"no layer named {n!r}" for n in sorted(set(LAYERS) - seen)]
    return new_xml, changed, errors


def main(argv):
    check = CHECK in argv
    paths = [a for a in argv if a != CHECK]
    if len(paths) != 1:
        print("usage: require_shape.py [--check] <project.qgz>",
              file=sys.stderr)
        return 2
    project = paths[0]
    qgs, payload = read_project(project)
    xml = payload[qgs].decode("utf-8")
    new_xml, changed, errors = rewrite(xml)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        print("nothing written", file=sys.stderr)
        return 1
    for name in changed:
        print(f"{name}: a row must have a shape")
    if new_xml == xml:
        print(f"no change needed: {project}")
        return 0
    if check:
        print(f"{len(changed)} layer(s) accept rows with no shape in {project}")
        return 1
    backup = write_project(project, qgs, payload, new_xml)
    print(f"required a shape on {len(changed)} layer(s) in {project} "
          f"(backup: {backup})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
