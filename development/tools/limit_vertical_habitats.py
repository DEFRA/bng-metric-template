"""Keep the vertical area habitats on their own layers, and off the area ones.

The Statutory Metric counts five habitat types by their vertical area, and
leaves them out of the site area: the two green walls (Urban) and the three
intertidal hard structures. The vertical layers' reference lists in
`CSV References/Vertical Area Habitats/` hold only these five. This limits
the two broad habitat drop-downs that are not read from those lists:

- Baseline Broad Habitat Type, a Value Map on both vertical layers, keeps
  only the blank choice and the broad habitats in VERTICAL_BROAD_HABITATS;
- Proposed Broad Habitat Type, on the post-intervention layer, reads the
  list it shares with the area habitat layers, so its filter also asks for
  one of VERTICAL_BROAD_HABITATS.

The area habitat layers must not offer them: they are not part of the site
area, which the area habitats must cover exactly. The intertidal hard
structures are not in the area habitat reference lists, and the green walls
never were. So the area layers drop the broad habitats in
VERTICAL_ONLY_BROAD_HABITATS, whose every habitat is a vertical one:

- Baseline Broad Habitat Type, a Value Map on both area layers, loses them;
- Proposed Broad Habitat Type, on the area post-intervention layer, gets a
  filter that leaves them out.

Urban stays on the area layers, for its other habitats.

Run reset_stale_dropdowns.py after it, because the reset of the proposed
drop-downs is made from their filter.

    python3 development/tools/limit_vertical_habitats.py [--check] <project.qgz>

Edits the widget settings in place and leaves every other byte alone, for the
same reasons as qgz_actions.py. Running it twice changes nothing. With
--check it writes nothing, lists what it would change, and exits 1 if
anything would change.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qgz_actions import escape, read_project, write_project     # noqa: E402

CHECK = "--check"
VERTICAL_LAYERS = ("Vertical Area Habitats Baseline",
                   "Vertical Area Habitats Post-Intervention")
VERTICAL_BROAD_HABITATS = ("Intertidal hard structures", "Urban")
AREA_LAYERS = ("Area Habitats Baseline", "Area Habitats Post-Intervention")
# The broad habitats whose every habitat is counted by vertical area.
VERTICAL_ONLY_BROAD_HABITATS = ("Intertidal hard structures",)
BASELINE_BROAD = "Baseline Broad Habitat Type"
PROPOSED_BROAD = "Proposed Broad Habitat Type"
# QGIS stores NULL in a Value Map under this key (QgsValueMapFieldFormatter).
NULL_VALUE = "{2839923C-8B7D-419E-B84B-CA2FE9B80EC7}"

BROAD_FILTER = ("\"ID\"=concat(current_value('Baseline Broad Habitat Type'),"
                "current_value('Retention Category'))")
VERTICAL_FILTER = (BROAD_FILTER + ' AND "New" IN ('
                   + ",".join(f"'{name}'" for name in VERTICAL_BROAD_HABITATS)
                   + ")")
AREA_FILTER = (BROAD_FILTER + ' AND NOT ("New" IN ('
               + ",".join(f"'{name}'" for name in VERTICAL_ONLY_BROAD_HABITATS)
               + "))")

MAPLAYER = re.compile(r"<maplayer\b.*?</maplayer>", re.S)
LAYER_NAME = re.compile(r"<layername>([^<]*)</layername>")
MAP_ENTRY = re.compile(r'[ \t]*<Option type="Map">\s*<Option name="[^"]*" '
                       r'type="QString" value="(?P<value>[^"]*)"/>\s*'
                       r"</Option>\n")
FILTER_OPTION = re.compile(r'(<Option name="FilterExpression" type="QString" '
                           r'value=")([^"]*)("/>)')


def field_block(layer, field):
    """The span of one field's widget settings in a layer, or None."""
    return re.search(r'<field name="' + re.escape(escape(field))
                     + r'"[^>]*>.*?</field>', layer, re.S)


def limit_value_map(widget):
    """Drop every entry but the blank choice and the vertical broad habitats."""
    keep = {NULL_VALUE} | {escape(name) for name in VERTICAL_BROAD_HABITATS}
    return MAP_ENTRY.sub(
        lambda found: found.group(0) if found.group("value") in keep else "",
        widget)


def drop_vertical_only(widget):
    """Drop the broad habitats whose every habitat is a vertical one."""
    drop = {escape(name) for name in VERTICAL_ONLY_BROAD_HABITATS}
    return MAP_ENTRY.sub(
        lambda found: "" if found.group("value") in drop else found.group(0),
        widget)


def set_filter(wanted):
    """A change that gives the proposed broad drop-down this filter."""
    def change(widget):
        found = FILTER_OPTION.search(widget)
        if found is None:
            raise SystemExit(f"{PROPOSED_BROAD} has no filter")
        if found.group(2) not in (escape(BROAD_FILTER), escape(wanted)):
            raise SystemExit(f"{PROPOSED_BROAD} has an unexpected filter: "
                             f"{found.group(2)}")
        return (widget[:found.start(2)] + escape(wanted)
                + widget[found.end(2):])
    return change


def rewrite_field(layer, field, change, changed, name):
    found = field_block(layer, field)
    if found is None:
        raise SystemExit(f"{name} has no field {field!r}")
    new = change(found.group(0))
    if new != found.group(0):
        changed.append((name, field))
    return layer[:found.start()] + new + layer[found.end():]


def rewrite(xml):
    """Return (xml, [(layer, field)]) with the broad drop-downs limited."""
    changed, seen = [], set()

    def layer(match):
        block = match.group(0)
        name = LAYER_NAME.search(block)
        if name is None or name.group(1) not in VERTICAL_LAYERS + AREA_LAYERS:
            return block
        name = name.group(1)
        seen.add(name)
        vertical = name in VERTICAL_LAYERS
        block = rewrite_field(
            block, BASELINE_BROAD,
            limit_value_map if vertical else drop_vertical_only,
            changed, name)
        if name.endswith("Post-Intervention"):
            block = rewrite_field(
                block, PROPOSED_BROAD,
                set_filter(VERTICAL_FILTER if vertical else AREA_FILTER),
                changed, name)
        return block

    xml = MAPLAYER.sub(layer, xml)
    missing = sorted(set(VERTICAL_LAYERS + AREA_LAYERS) - seen)
    if missing:
        raise SystemExit(f"the project has no layer {', '.join(missing)}")
    return xml, changed


def main(argv):
    check = CHECK in argv
    paths = [a for a in argv if a != CHECK]
    if len(paths) != 1:
        raise SystemExit(__doc__)
    path = paths[0]
    qgs, payload = read_project(path)
    xml = payload[qgs].decode("utf-8")
    new_xml, changed = rewrite(xml)
    if not changed:
        print(f"no change needed: {path}")
        return 0
    for name, field in changed:
        print(f"{'would limit' if check else 'limited'} {name} / {field}")
    if check:
        return 1
    backup = write_project(path, qgs, payload, new_xml)
    print(f"wrote {path} (backup: {backup})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
