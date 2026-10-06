"""Show each drop-down in the order that its reference list sets.

QGIS sorts the items of a value-relation drop-down by their key, unless the
widget names a column to sort by. The template's condition, retention and
encroachment lists were once numbered, as "1. Good", "2. Fairly Good", and the
numbers put the items in order. Without the numbers the keys sort
alphabetically, and "Fairly Good" comes before "Good".

A reference list that has an Order column sets the order of its items. This
points every drop-down that reads such a list at that column. A drop-down
whose list has no Order column is left alone.

    python3 development/tools/order_dropdowns.py [--check] <project.qgz>

The reference lists are read from the paths that the project gives, relative
to the project file. Edits the drop-down settings in place and leaves every
other byte alone, for the same reasons as qgz_actions.py. Running it twice
changes nothing. With --check it writes nothing, lists what it would change,
and exits 1 if anything would change.
"""
import csv
import html
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qgz_actions import read_project, write_project     # noqa: E402

CHECK = "--check"
ORDER_COLUMN = "Order"
# The settings that sort a drop-down by a column. QGIS reads them by name.
WANTED = (("OrderByField", "bool", "true"),
          ("OrderByFieldName", "QString", ORDER_COLUMN))
# The new settings go before this one, which every drop-down in the template
# has, so that the map stays in the alphabetical order QGIS writes it in.
ANCHOR = "OrderByValue"

MAPLAYER = re.compile(r"<maplayer\b.*?</maplayer>", re.S)
LAYER_ID = re.compile(r"<id>([^<]+)</id>")
LAYER_NAME = re.compile(r"<layername>([^<]*)</layername>")
DATASOURCE = re.compile(r"<datasource>([^<]*)</datasource>")
PROVIDER = re.compile(r"<provider\b[^>]*>([^<]*)</provider>")
WIDGET = re.compile(r'<editWidget type="ValueRelation">.*?</editWidget>', re.S)
# Attribute by attribute, because QGIS leaves `>` unescaped in a value.
OPTION_LINE = re.compile(
    r'^([ \t]*)<Option\b((?:\s+[\w:-]+="[^"]*")*)\s*/>[ \t]*\r?\n', re.M)
ATTRIBUTE = re.compile(r'([\w:-]+)="([^"]*)"')


def list_path(project_dir, datasource):
    """The file behind a delimited-text datasource, such as
    file:./CSV%20References/Habitats/Habitat%20Condition.csv?type=csv&..."""
    source = html.unescape(datasource).split("?", 1)[0]
    source = urllib.parse.unquote(source.removeprefix("file:"))
    if source.startswith("//"):
        source = source[2:]
    return os.path.normpath(os.path.join(project_dir, source))


def ordered_lists(xml, project_dir):
    """The ids of the reference-list layers whose file has an Order column."""
    found = set()
    for block in MAPLAYER.findall(xml):
        provider = PROVIDER.search(block)
        if provider is None or provider.group(1) != "delimitedtext":
            continue
        path = list_path(project_dir, DATASOURCE.search(block).group(1))
        if not os.path.exists(path):
            raise SystemExit(f"reference list not found: {path}")
        with open(path, newline="", encoding="utf-8-sig") as handle:
            header = next(csv.reader(handle), [])
        if ORDER_COLUMN in header:
            found.add(LAYER_ID.search(block).group(1))
    return found


def options(widget):
    """Map option name -> (value, line match) for each one-line option."""
    found = {}
    for line in OPTION_LINE.finditer(widget):
        attributes = dict(ATTRIBUTE.findall(line.group(2)))
        if "name" in attributes:
            found[attributes["name"]] = (attributes.get("value"), line)
    return found


def order_widget(widget):
    """Return the widget with the Order settings in place, and whether it changed."""
    current = options(widget)
    if all(current.get(name, (None,))[0] == value
           for name, _type, value in WANTED):
        return widget, False
    if ANCHOR not in current:
        raise SystemExit(f"a drop-down has no {ANCHOR} setting to anchor on")
    anchor = current[ANCHOR][1]
    indent = anchor.group(1)
    newline = "\r\n" if anchor.group(0).endswith("\r\n") else "\n"
    lines = "".join(f'{indent}<Option name="{name}" type="{kind}" '
                    f'value="{value}"/>{newline}' for name, kind, value in WANTED)
    drop = sorted((current[name][1].span() for name, _t, _v in WANTED
                   if name in current), reverse=True)
    start = anchor.start()
    widget = widget[:start] + lines + widget[start:]
    for begin, end in drop:
        shift = len(lines) if begin >= start else 0
        widget = widget[:begin + shift] + widget[end + shift:]
    return widget, True


def main(argv):
    check = CHECK in argv
    paths = [a for a in argv if a != CHECK]
    if len(paths) != 1:
        print("usage: order_dropdowns.py [--check] <project.qgz>", file=sys.stderr)
        return 2
    project = paths[0]
    qgs, payload = read_project(project)
    xml = payload[qgs].decode("utf-8")
    ordered = ordered_lists(xml, os.path.dirname(os.path.abspath(project)))
    changed = {}

    def per_widget(match, layer_name):
        widget = match.group(0)
        layer = re.search(r'<Option name="Layer" type="QString" value="([^"]*)"/>',
                          widget)
        if layer is None or layer.group(1) not in ordered:
            return widget
        widget, edited = order_widget(widget)
        changed[layer_name] = changed.get(layer_name, 0) + edited
        return widget

    def per_layer(match):
        block = match.group(0)
        name = LAYER_NAME.search(block)
        name = name.group(1) if name else ""
        return WIDGET.sub(lambda m: per_widget(m, name), block)

    new_xml = MAPLAYER.sub(per_layer, xml)
    for name, count in changed.items():
        print(f"{name}: {count} drop-down(s) to sort by {ORDER_COLUMN}")
    if new_xml == xml:
        print(f"no change needed: {project}")
        return 0
    if check:
        print(f"drop-down order out of date in {project}")
        return 1
    backup = write_project(project, qgs, payload, new_xml)
    print(f"sorted the drop-downs by {ORDER_COLUMN} in {project} (backup: {backup})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
