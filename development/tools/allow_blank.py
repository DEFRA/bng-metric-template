"""Let every drop-down be left blank.

A column whose drop-down has no blank choice cannot be cleared once a value is
picked. It also shows a value outside its list in brackets: an empty string
reads `()`. This gives every drop-down a blank choice, stored as NULL:

- a Value Map drop-down gets QGIS's own NULL entry, first in the list, shown
  as `<NULL>`, as the widget's "Add NULL value" button makes it;
- a Value Relation drop-down gets "Allow NULL value" switched on.

A blank choice makes no value valid that was invalid before. A column that
must hold a value still says so through its constraint, and the backend still
checks it.

    python3 development/tools/allow_blank.py [--check] <project.qgz>

Edits the widget settings in place and leaves every other byte alone, for the
same reasons as qgz_actions.py. Running it twice changes nothing. With --check
it writes nothing, lists what it would change, and exits 1 if anything would
change.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qgz_actions import read_project, write_project             # noqa: E402

CHECK = "--check"
# QGIS stores NULL in a Value Map under this key (QgsValueMapFieldFormatter).
NULL_VALUE = "{2839923C-8B7D-419E-B84B-CA2FE9B80EC7}"
NULL_LABEL = "&lt;NULL&gt;"

MAPLAYER = re.compile(r"<maplayer\b.*?</maplayer>", re.S)
LAYER_NAME = re.compile(r"<layername>([^<]*)</layername>")
FIELD = re.compile(r'<field name="(?P<name>[^"]+)"[^>]*>\s*'
                   r'<editWidget type="(?P<type>\w+)">.*?</editWidget>', re.S)
MAP_LIST = re.compile(r'(?P<indent>[ \t]*)<Option name="map" type="List">\n')
ALLOW_NULL_OFF = '<Option name="AllowNull" type="bool" value="false"/>'
ALLOW_NULL_ON = '<Option name="AllowNull" type="bool" value="true"/>'


def null_entry(indent):
    """QGIS's NULL entry, indented as the entries after it."""
    inner = indent + "  "
    return (f'{inner}<Option type="Map">\n'
            f'{inner}  <Option name="{NULL_LABEL}" type="QString" '
            f'value="{NULL_VALUE}"/>\n'
            f'{inner}</Option>\n')


def allow_blank(widget, kind):
    """Return the widget with a blank choice, or the same text if it has one."""
    if kind == "ValueMap":
        if NULL_VALUE in widget:
            return widget
        found = MAP_LIST.search(widget)
        if found is None:
            raise SystemExit("a Value Map drop-down has no map list")
        return (widget[:found.end()] + null_entry(found.group("indent"))
                + widget[found.end():])
    if kind == "ValueRelation":
        return widget.replace(ALLOW_NULL_OFF, ALLOW_NULL_ON)
    return widget


def rewrite(xml):
    """Return (xml, [(layer, field)]) with every drop-down able to be blank."""
    changed = []

    def layer(match):
        block = match.group(0)
        name = LAYER_NAME.search(block)
        config = re.search(r"<fieldConfiguration>.*?</fieldConfiguration>",
                           block, re.S)
        if name is None or config is None:
            return block

        def field(found):
            widget = allow_blank(found.group(0), found.group("type"))
            if widget != found.group(0):
                changed.append((name.group(1), found.group("name")))
            return widget

        section = FIELD.sub(field, config.group(0))
        return block[:config.start()] + section + block[config.end():]

    return MAPLAYER.sub(layer, xml), changed


def main(argv):
    check = CHECK in argv
    paths = [a for a in argv if a != CHECK]
    if len(paths) != 1:
        print("usage: allow_blank.py [--check] <project.qgz>", file=sys.stderr)
        return 2
    project = paths[0]
    qgs, payload = read_project(project)
    xml = payload[qgs].decode("utf-8")
    new_xml, changed = rewrite(xml)
    for layer, field in changed:
        print(f"{layer} / {field}: blank choice added")
    if new_xml == xml:
        print(f"no change needed: {project}")
        return 0
    if check:
        print(f"{len(changed)} drop-down(s) without a blank choice in {project}")
        return 1
    backup = write_project(project, qgs, payload, new_xml)
    print(f"gave {len(changed)} drop-down(s) a blank choice in {project} "
          f"(backup: {backup})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
