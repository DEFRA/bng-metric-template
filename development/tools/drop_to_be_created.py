"""Take "To be created" off the baseline hedgerow and watercourse type lists.

The Natural England template recorded a new hedgerow or watercourse as a
baseline row whose type was "To be created". The BNG Service template does
not: a new feature is drawn on the Post-Intervention layer as "Created", and
its baseline columns stay blank. The BNG service and bng-library read
"To be created" as no habitat type, so a baseline feature that holds it is
not a habitat at all. This removes the value from the Value Map of:

- Baseline Hedge Type, on both hedgerow layers;
- Baseline River Type, on both watercourse layers.

The reference lists in `CSV References/` keep "To be created". The Proposed
type and Retention Category drop-downs of a "Created" feature look up their
values under it when the baseline type is blank.

    python3 development/tools/drop_to_be_created.py [--check] <project.qgz>

Edits the widget settings in place and leaves every other byte alone, for the
same reasons as qgz_actions.py. Running it twice changes nothing. With
--check it writes nothing, lists what it would change, and exits 1 if
anything would change.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qgz_actions import read_project, write_project             # noqa: E402

CHECK = "--check"
TO_BE_CREATED = "To be created"
# Layer -> the column whose Value Map loses the value.
TARGETS = {
    "Hedgerows Baseline": "Baseline Hedge Type",
    "Hedgerows Post-Intervention": "Baseline Hedge Type",
    "Watercourses Baseline": "Baseline River Type",
    "Watercourses Post-Intervention": "Baseline River Type",
}

MAPLAYER = re.compile(r"<maplayer\b.*?</maplayer>", re.S)
LAYER_NAME = re.compile(r"<layername>([^<]*)</layername>")
FIELD = re.compile(r'<field name="(?P<name>[^"]+)"[^>]*>\s*'
                   r'<editWidget type="ValueMap">.*?</editWidget>', re.S)
ENTRY = re.compile(r'[ \t]*<Option type="Map">\s*<Option name="'
                   + re.escape(TO_BE_CREATED) + r'" type="QString" value="'
                   + re.escape(TO_BE_CREATED) + r'"/>\s*</Option>\n')


def drop_from_layer(layer_xml, column):
    """Return the layer without the entry, and how many entries went."""
    removed = 0

    def edit(match):
        nonlocal removed
        if match.group("name") != column:
            return match.group(0)
        widget, count = ENTRY.subn("", match.group(0))
        removed += count
        return widget

    return FIELD.sub(edit, layer_xml), removed


def drop(xml):
    """Return the project without the entries, and what was removed."""
    changes = []

    def edit(match):
        layer_xml = match.group(0)
        name = LAYER_NAME.search(layer_xml)
        column = TARGETS.get(name.group(1)) if name else None
        if column is None:
            return layer_xml
        layer_xml, removed = drop_from_layer(layer_xml, column)
        if removed:
            changes.append(f"{name.group(1)}: {column}")
        return layer_xml

    return MAPLAYER.sub(edit, xml), changes


def main(argv):
    check = CHECK in argv
    paths = [a for a in argv if a != CHECK]
    if len(paths) != 1:
        print(__doc__)
        return 2
    path = paths[0]
    qgs, payload = read_project(path)
    xml = payload[qgs].decode("utf-8")
    new_xml, changes = drop(xml)
    if not changes:
        print("no change needed")
        return 0
    for change in changes:
        print(f'{"would remove" if check else "removed"} "{TO_BE_CREATED}": {change}')
    if check:
        return 1
    backup = write_project(path, qgs, payload, new_xml)
    print(f"saved a copy of the original as {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
