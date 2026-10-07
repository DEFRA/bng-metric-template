"""Fill in and lock the columns a surveyor never chooses.

Some columns follow from other columns, or never vary, so the template fills
them in and locks them:

- Baseline and Proposed Distinctiveness: looked up from the habitat type in
  the Distinctiveness reference lists. NULL while there is no habitat type.
- Baseline Strategic Significance: `Low`. On a post-intervention row it is
  `Low` only when the row has a baseline part, that is when its baseline type
  is set, and NULL otherwise, as the other Baseline columns of a new habitat
  are blank.
- Spatial risk category: `N/A` on every post-intervention layer.

Proposed Strategic Significance is a drop-down of `Low` and `High`. It is
`Low` on a new row and never blank. On a Retained row it is `Low`, as the
baseline is, and the drop-down is greyed out.

The years created in advance and the years of delay cannot both be above 0.
While one is above 0, the other drop-down is greyed out in the form, and a
save blanks one if both are. Blank and `0` are both allowed.

Each filled column gets a default value expression applied on update, so it
follows every change of the column it depends on, and a text widget that the
surveyor cannot edit. A field has one default expression, so a filled column
has no stale-value rule: the lookup gives the right value, or NULL, every
time. reset_stale_dropdowns.py skips these columns, because they are no longer
filtered drop-downs.

    python3 development/tools/set_field_rules.py [--check] <project.qgz>

Edits the widget, editable and default settings in place and leaves every
other byte alone, for the same reasons as qgz_actions.py. Running it twice
changes nothing. It refuses to replace a default that none of the template
tools wrote, and then writes nothing. With --check it writes nothing, lists
what it would change, and exits 1 if anything would change.
"""
import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import paste_lineage                                            # noqa: E402
from qgz_actions import escape, read_project, write_project     # noqa: E402
from reset_stale_dropdowns import default_element               # noqa: E402

CHECK = "--check"
LOW = "'Low'"
NA = "'N/A'"
NULL_VALUE = "{2839923C-8B7D-419E-B84B-CA2FE9B80EC7}"

BASELINE, POST = "baseline", "post"
AREA, VERTICAL, HEDGE, WATER, TREE = ("area", "vertical", "hedge", "water",
                                      "tree")

LAYERS = {
    "Area Habitats Baseline": (AREA, BASELINE),
    "Area Habitats Post-Intervention": (AREA, POST),
    "Vertical Area Habitats Baseline": (VERTICAL, BASELINE),
    "Vertical Area Habitats Post-Intervention": (VERTICAL, POST),
    "Hedgerows Baseline": (HEDGE, BASELINE),
    "Hedgerows Post-Intervention": (HEDGE, POST),
    "Watercourses Baseline": (WATER, BASELINE),
    "Watercourses Post-Intervention": (WATER, POST),
    "Individual Trees Baseline": (TREE, BASELINE),
    "Individual Trees Post-Intervention": (TREE, POST),
}

# Kind -> the column that holds the type of the habitat, baseline and proposed.
TYPE_COLUMNS = {
    AREA: ("Baseline Habitat Type", "Proposed Habitat Type"),
    VERTICAL: ("Baseline Habitat Type", "Proposed Habitat Type"),
    HEDGE: ("Baseline Hedge Type", "Proposed Hedge Type"),
    WATER: ("Baseline River Type", "Proposed River Type"),
    TREE: ("Baseline Tree Type", "Proposed Tree Type"),
}

# Kind -> (list layer, its habitat column, its band column), baseline then
# proposed. Trees have no distinctiveness.
DISTINCTIVENESS = {
    AREA: (("Habitat Distinctiveness- pre", "Habitat", "Baseline Distinctivness"),
           ("Habitat Distinctiveness- post", "Habitat", "Proposed Distinctivness")),
    VERTICAL: (("Vertical Area Habitat Distinctiveness- pre", "Habitat",
                "Baseline Distinctivness"),
               ("Vertical Area Habitat Distinctiveness- post", "Habitat",
                "Proposed Distinctivness")),
    HEDGE: (("Hedgerow Distinctiveness- pre", "Value", "Distinctiveness"),
            ("Hedgerow Distinctiveness - post", "Value", "Distinctiveness")),
    WATER: (("Watercourse Distinctiveness- pre", "Value", "Distinctiveness"),
            ("Watercourse Distinctiveness- post", "Value", "Distinctiveness")),
}

# A baseline type that means the row has no baseline part.
NO_BASELINE = ("To be created", "N/A")

# Kind -> the Low/High list that its Proposed Strategic Significance reads.
# Area and vertical area habitats have no list layer and keep a Value Map.
SIGNIFICANCE_LISTS = {
    HEDGE: "Hedgerow Strategic Significance",
    WATER: "Watercourse Proposed Strategic Significance",
    TREE: "Individual tree Strategic Significance - post",
}
LOW_HIGH = ("Low", "High")

BASELINE_SIGNIFICANCE = "Baseline Strategic Significance"
PROPOSED_SIGNIFICANCE = "Proposed Strategic Significance"
SPATIAL_RISK = "Spatial risk category"
RETENTION = "Retention Category"
RETAINED = "Retained"

# Kind -> (years created in advance, years of delay). The metric allows one.
TIMING = {
    AREA: ("Habitat created in advance/years",
           "Delay in starting habitat creation/years"),
    VERTICAL: ("Habitat created in advance/years",
               "Delay in starting habitat creation/years"),
    HEDGE: ("Habitat created in advance/years",
            "Delay in starting habitat creation/years"),
    WATER: ("Habitat created in advance/years",
            "Delay in starting habitat creation/years"),
    TREE: ("Habitat Created/Enhanced in advance/years",
           "Delay in starting habitat creation/enhancement in years"),
}

# A default that any of the template tools wrote contains one of these, and
# may be replaced.
# Every default this tool writes contains one of these, or is a literal.
OWNED = ("attribute(@parent", paste_lineage.MARKER, "aggregate(layer:=",
         "coalesce(")
OWNED_LITERALS = (NA, LOW)

TEXT_WIDGET = ('<editWidget type="TextEdit">\n'
               '{i}  <config>\n'
               '{i}    <Option type="Map">\n'
               '{i}      <Option name="IsMultiline" type="bool" value="false"/>\n'
               '{i}      <Option name="UseHtml" type="bool" value="false"/>\n'
               '{i}    </Option>\n'
               '{i}  </config>\n'
               '{i}</editWidget>')


def value_map(indent, values):
    """A Value Map widget with QGIS's blank choice first."""
    i = indent
    entries = [("&lt;NULL&gt;", NULL_VALUE)] + [(v, v) for v in values]
    items = "".join(
        f'{i}        <Option type="Map">\n'
        f'{i}          <Option name="{name}" type="QString" value="{value}"/>\n'
        f'{i}        </Option>\n' for name, value in entries)
    return ('<editWidget type="ValueMap">\n'
            f'{i}  <config>\n'
            f'{i}    <Option type="Map">\n'
            f'{i}      <Option name="map" type="List">\n'
            + items +
            f'{i}      </Option>\n'
            f'{i}    </Option>\n'
            f'{i}  </config>\n'
            f'{i}</editWidget>')


def lookup(list_id, key, value, type_column):
    """The one band the list gives the habitat type, or NULL."""
    return (f'if("{type_column}" IS NULL, NULL, '
            f"with_variable('d', array_distinct(aggregate(layer:='{list_id}', "
            f"aggregate:='array_agg', expression:=\"{value}\", "
            f"filter:=\"{key}\" = attribute(@parent, '{type_column}'))), "
            "if(array_length(@d) = 1, @d[0], NULL)))")


def baseline_significance(kind, stage):
    if stage == BASELINE:
        return LOW
    column = TYPE_COLUMNS[kind][0]
    blanks = ", ".join(f"'{v}'" for v in NO_BASELINE)
    return (f'if("{column}" IS NULL OR "{column}" IN ({blanks}), NULL, '
            f"{LOW})")


def proposed_significance():
    """Low on a Retained row, which keeps its baseline value, else the
    surveyor's choice, starting at Low."""
    field = PROPOSED_SIGNIFICANCE
    return (f'if("{RETENTION}" = \'{RETAINED}\', {LOW}, '
            f'coalesce("{field}", {LOW}))')


def only_one_timing(field, other):
    """Blank this timing value while the other one is above 0.

    The values are the drop-down's text: blank, `0`, `1` and so on to `30+`.
    A backstop for a table cell, where timing_editable does not apply: QGIS
    evaluates the pair in its own order, so either one may be blanked.
    """
    return (f'if(coalesce("{other}", \'0\') <> \'0\', NULL, "{field}")')


def timing_editable(other):
    """A timing drop-down can be used only while the other is blank or 0.

    The attribute table's form view saves the row the moment a value is
    picked, before the form re-evaluates the other value, and the save cannot
    tell which value was picked last. Greying out the other drop-down stops
    both values reaching above 0 in any form, so the surveyor sets one back
    to 0 or blank before picking the other. only_one_timing still blanks one
    of them if a table cell sets both.
    """
    return f'coalesce("{other}", \'0\') = \'0\''


# The Proposed Strategic Significance drop-down is greyed out on a Retained
# row. The form evaluates this as the row changes.
SIGNIFICANCE_EDITABLE = f'coalesce("{RETENTION}", \'\') <> \'{RETAINED}\''


def rules_for(kind, stage, ids):
    """[(field, widget kind, locked, default, apply on update)]."""
    rules = []
    if kind in DISTINCTIVENESS:
        for (list_name, key, value), prefix, column in zip(
                DISTINCTIVENESS[kind], ("Baseline", "Proposed"),
                TYPE_COLUMNS[kind]):
            if stage == BASELINE and prefix == "Proposed":
                continue
            rules.append((f"{prefix} Distinctiveness", "text", True,
                          lookup(ids[list_name], key, value, column), "1"))
    rules.append((BASELINE_SIGNIFICANCE, "text", True,
                  baseline_significance(kind, stage), "1"))
    if stage == POST:
        widget = (("list", SIGNIFICANCE_LISTS[kind])
                  if kind in SIGNIFICANCE_LISTS else ("map", LOW_HIGH))
        rules.append((PROPOSED_SIGNIFICANCE, widget, False,
                      proposed_significance(), "1"))
        rules.append((SPATIAL_RISK, None, True, NA, "1"))
        advance, delay = TIMING[kind]
        rules.append((advance, None, False, only_one_timing(advance, delay),
                      "1"))
        rules.append((delay, None, False, only_one_timing(delay, advance),
                      "1"))
    return rules


def field_block(block, field):
    pattern = re.compile(
        r'(?P<indent>[ \t]*)<field name="' + re.escape(escape(field))
        + r'" configurationFlags="[^"]*">\s*(?P<widget><editWidget\b.*?</editWidget>)',
        re.S)
    return pattern.search(block)


def set_widget(block, field, widget, ids, errors, layer):
    found = field_block(block, field)
    if found is None:
        errors.append(f"{layer}: no widget for {field!r}")
        return block
    indent = found.group("indent") + "  "
    old = found.group("widget")
    if widget == "text":
        new = TEXT_WIDGET.format(i=indent)
    elif widget[0] == "map":
        new = value_map(indent, widget[1])
    else:
        new = relation_to_list(old, ids[widget[1]], widget[1], errors, layer)
    return block[:found.start("widget")] + new + block[found.end("widget"):]


def relation_to_list(widget, list_id, list_name, errors, layer):
    """Point a Value Relation at the Low/High list, with no filter."""
    if 'type="ValueRelation"' not in widget:
        errors.append(f"{layer}: {PROPOSED_SIGNIFICANCE} is not a Value "
                      "Relation")
        return widget
    wanted = {"FilterExpression": "", "Key": "Value", "Value": "Description",
              "Layer": list_id, "LayerName": list_name, "AllowNull": "true"}
    for name, value in wanted.items():
        widget = re.sub(rf'(<Option name="{name}" type="\w+" value=")[^"]*"',
                        lambda m, v=value: m.group(1) + escape(v) + '"',
                        widget)
    return widget


def set_editable(block, field, locked):
    """Set the field's entry in the layer's <editable> list, adding it if
    the list has none."""
    value = "0" if locked else "1"
    wanted = f'<field name="{escape(field)}" editable="{value}"/>'
    empty = re.search(r"(?P<pad>[ \t]*)<editable/>", block)
    if empty is not None:
        pad = empty.group("pad")
        return (block[:empty.start()] + f"{pad}<editable>\n{pad}  {wanted}\n"
                f"{pad}</editable>" + block[empty.end():])
    section = re.search(r"(?P<pad>[ \t]*)<editable>.*?</editable>", block,
                        re.S)
    if section is None:
        raise SystemExit("a data layer has no <editable> list")
    text = section.group(0)
    entry = re.compile(r'<field name="' + re.escape(escape(field))
                       + r'" editable="[01]"/>')
    if entry.search(text):
        text = entry.sub(wanted, text)
    else:
        pad = section.group("pad")
        text = text.replace("<editable>", f"<editable>\n{pad}  {wanted}", 1)
    return block[:section.start()] + text + block[section.end():]


def set_default(block, field, expression, on_update, errors, layer):
    found = default_element(field).search(block)
    if found is None:
        errors.append(f"{layer}: no <default> element for {field!r}")
        return block
    current = html.unescape(
        re.search(r'\bexpression="([^"]*)"', found.group(0)).group(1))
    if current and current != expression and current not in OWNED_LITERALS and not any(
            mark in current for mark in OWNED):
        errors.append(f"{layer}: {field!r} already has a default no tool "
                      f"wrote: {current}")
        return block
    element = (f'<default expression="{escape(expression)}" '
               f'field="{escape(field)}" applyOnUpdate="{on_update}"/>')
    if found.group(0) == element:
        return block
    return block[:found.start()] + element + block[found.end():]


DD_FIELD = ('{p}  <field name="{name}">\n'
            '{p}    <Option type="Map">\n'
            '{p}      <Option name="name" type="QString" value=""/>\n'
            '{p}      <Option name="properties" type="Map">\n'
            '{p}        <Option name="dataDefinedEditable" type="Map">\n'
            '{p}          <Option name="active" type="bool" value="true"/>\n'
            '{p}          <Option name="expression" type="QString" value="{expression}"/>\n'
            '{p}          <Option name="type" type="int" value="3"/>\n'
            '{p}        </Option>\n'
            '{p}      </Option>\n'
            '{p}      <Option name="type" type="QString" value="collection"/>\n'
            '{p}    </Option>\n'
            '{p}  </field>\n')


def set_editable_when(block, field, expression):
    """Make the field editable in the form only while the expression holds."""
    found = re.search(r"(?P<pad>[ \t]*)<dataDefinedFieldProperties/>", block)
    entry = DD_FIELD.format(p="{p}", name=escape(field),
                            expression=escape(expression))
    if found is not None:
        pad = found.group("pad")
        return (block[:found.start()] + f"{pad}<dataDefinedFieldProperties>\n"
                + entry.format(p=pad) + f"{pad}</dataDefinedFieldProperties>"
                + block[found.end():])
    section = re.search(r"(?P<pad>[ \t]*)<dataDefinedFieldProperties>.*?"
                        r"</dataDefinedFieldProperties>", block, re.S)
    if section is None:
        raise SystemExit("a data layer has no <dataDefinedFieldProperties>")
    pad = section.group("pad")
    mine = re.compile(r'[ \t]*<field name="' + re.escape(escape(field))
                      + r'">.*?</field>\n', re.S)
    text = mine.sub("", section.group(0))
    text = text.replace(f"{pad}</dataDefinedFieldProperties>",
                        entry.format(p=pad)
                        + f"{pad}</dataDefinedFieldProperties>", 1)
    return block[:section.start()] + text + block[section.end():]


def rewrite(xml):
    known = paste_lineage.layers(xml)
    ids = {name: layer_id for name, (layer_id, _) in known.items()}
    errors, changed = [], []

    def layer(match):
        block = match.group(0)
        name = paste_lineage.LAYER_NAME.search(block)
        if name is None or name.group(1) not in LAYERS:
            return block
        kind, stage = LAYERS[name.group(1)]
        before = block
        for field, widget, locked, expression, on_update in rules_for(
                kind, stage, ids):
            if widget is not None:
                block = set_widget(block, field, widget, ids, errors,
                                   name.group(1))
            block = set_editable(block, field, locked)
            block = set_default(block, field, expression, on_update, errors,
                                name.group(1))
        if stage == POST:
            block = set_editable_when(block, PROPOSED_SIGNIFICANCE,
                                      SIGNIFICANCE_EDITABLE)
            advance, delay = TIMING[kind]
            block = set_editable_when(block, advance, timing_editable(delay))
            block = set_editable_when(block, delay, timing_editable(advance))
        if block != before:
            changed.append(name.group(1))
        return block

    try:
        new_xml = paste_lineage.MAPLAYER.sub(layer, xml)
    except KeyError as missing:
        return xml, [], [f"no layer named {missing}"]
    missing = sorted(set(LAYERS) - set(known))
    errors += [f"no layer named {n!r}" for n in missing]
    return new_xml, changed, errors


def main(argv):
    check = CHECK in argv
    paths = [a for a in argv if a != CHECK]
    if len(paths) != 1:
        print("usage: set_field_rules.py [--check] <project.qgz>",
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
        print(f"{name}: filled and locked columns to update")
    if new_xml == xml:
        print(f"no change needed: {project}")
        return 0
    if check:
        print(f"{len(changed)} layer(s) out of date in {project}")
        return 1
    backup = write_project(project, qgs, payload, new_xml)
    print(f"set the filled and locked columns of {len(changed)} layer(s) in "
          f"{project} (backup: {backup})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
