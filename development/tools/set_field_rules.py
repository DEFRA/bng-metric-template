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

Each of those drop-downs offers blank, `0` to `30` and `30+`, which is what
the Statutory Metric takes. A stored value the list does not offer, such as
`N/A` or `Habitat already in target condition` from an earlier template, is
cleared when the row is saved. It does not count as above 0, so it does not
blank or grey out the other column.

A blank years created in advance becomes `30+` on an area, vertical area or
hedgerow row that records a habitat whose condition gets worse: `Created`,
with a baseline type, the same type proposed, and a Proposed Condition
ranked below the Baseline Condition, as the Metric User Guide asks (section
5, "Habitat retention"). The surveyor can pick another value. On any other
row of those layers `30+` is kept, but a soft constraint shows a warning in
the form: a `30+` left behind when a row changes, for example to
`Enhanced`, would credit the habitat at once with gains it has not made.

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
import require_shape                                            # noqa: E402
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
CREATED = "Created"

# Area, vertical area, hedgerow and watercourse rows share these columns.
ADVANCE_YEARS = "Habitat created in advance/years"
DELAY_YEARS = "Delay in starting habitat creation/years"
# Trees name both differently.
TREE_ADVANCE_YEARS = "Habitat Created/Enhanced in advance/years"
TREE_DELAY_YEARS = "Delay in starting habitat creation/enhancement in years"

# Kind -> (years created in advance, years of delay). The metric allows one.
TIMING = {
    AREA: (ADVANCE_YEARS, DELAY_YEARS),
    VERTICAL: (ADVANCE_YEARS, DELAY_YEARS),
    HEDGE: (ADVANCE_YEARS, DELAY_YEARS),
    WATER: (ADVANCE_YEARS, DELAY_YEARS),
    TREE: (TREE_ADVANCE_YEARS, TREE_DELAY_YEARS),
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


# The years the Statutory Metric takes, as the drop-down stores them. Blank
# is the Value Map's own NULL entry, added by value_map().
YEAR_VALUES = tuple(str(year) for year in range(31)) + ("30+",)
YEARS_OFFERED = ", ".join(f"'{year}'" for year in YEAR_VALUES)
YEARS_ABOVE_ZERO = ", ".join(f"'{year}'" for year in YEAR_VALUES if year != "0")


def other_above_zero(other):
    """The other timing value is a year above 0.

    A text value the drop-down no longer offers, such as `N/A`, is not a
    year, so it does not count.
    """
    return f'coalesce("{other}", \'0\') IN ({YEARS_ABOVE_ZERO})'


def kept_year(field):
    """The field when it is blank or a year the list offers, else NULL.

    A blank is NULL. coalesce of NULL is `0`, which the list offers, so a
    blank stays blank. Anything else the list does not offer is cleared.
    """
    return (f'if(coalesce("{field}", \'0\') IN ({YEARS_OFFERED}), '
            f'"{field}", NULL)')


def only_one_timing(field, other):
    """Blank this timing value while the other one is a year above 0.

    Also blank a value the drop-down does not offer. A backstop for a table
    cell, where timing_editable does not apply: QGIS evaluates the pair in
    its own order, so either one may be blanked.
    """
    return f'if({other_above_zero(other)}, NULL, {kept_year(field)})'


# A row that records a habitat whose condition gets worse: Created, with a
# baseline part, the same habitat type as its baseline, and a worse
# condition. The Metric team asks for it to be created 30 or more years in
# advance (User Guide, section 5, "Habitat retention": "the same area and
# habitat type as created in a lower condition"). The rule is for the area
# and hedgerow modules; watercourses follow the Metric's own creation rules,
# which the surveyor applies.
DEGRADED_KINDS = (AREA, VERTICAL, HEDGE)
DEGRADED_ADVANCE = "'30+'"
# QgsFieldConstraints.ConstraintStrengthSoft: the form warns, and saves.
SOFT = "2"

# The conditions, best first. Hedgerows use Good, Moderate and Poor, in the
# same order. A condition not in the list, such as `N/A - Other` or
# `Condition Assessment N/A`, has no rank, so it is never worse.
CONDITION_RANK = ("Good", "Fairly Good", "Moderate", "Fairly Poor", "Poor")
CONDITION = ("Baseline Condition", "Proposed Condition")


def worse_condition():
    """The Proposed Condition is ranked below a ranked Baseline Condition.

    The same or a better condition is not a habitat that gets worse: a
    same-type Created row in the same condition, such as grassland stripped
    for temporary works and reseeded, is a new creation, and keeps its
    temporal risk.
    """
    ranks = ", ".join(f"'{c}'" for c in CONDITION_RANK)
    base, proposed = CONDITION
    return (f"with_variable('rank', array({ranks}), "
            f'coalesce(array_find(@rank, "{proposed}") > '
            f'array_find(@rank, "{base}") '
            f'AND array_find(@rank, "{base}") >= 0, false))')


def degraded(kind):
    base, proposed = TYPE_COLUMNS[kind]
    blanks = ", ".join(f"'{v}'" for v in NO_BASELINE)
    return (f'"{RETENTION}" = \'{CREATED}\' AND "{base}" IS NOT NULL '
            f'AND "{base}" NOT IN ({blanks}) AND "{proposed}" = "{base}" '
            f'AND {worse_condition()}')


def advance_default(kind, advance, delay):
    """The years created in advance: blank while the delay is a year above 0,
    as only_one_timing gives. On a row that records a habitat whose condition
    gets worse, a blank one becomes `30+`.

    Only a blank value is filled, so the surveyor can pick another year,
    including `0`, and it is kept. Picking blank fills `30+` again. A `30+`
    on any other row is kept too: the Metric allows creation in advance in
    general, so the template does not decide it. advance_warning() flags it.

    A value the drop-down does not offer is cleared, including on a row whose
    condition gets worse. That clear does not become `30+` on the same save:
    the `30+` fill applies only to a value that was already blank.
    """
    if kind not in DEGRADED_KINDS:
        return only_one_timing(advance, delay)
    keep = (f'if("{advance}" IS NULL AND {degraded(kind)}, '
            f'{DEGRADED_ADVANCE}, {kept_year(advance)})')
    return f'if({other_above_zero(delay)}, NULL, {keep})'


def advance_warning(kind, advance):
    """A soft constraint: `30+` years in advance outside a habitat whose
    condition gets worse.

    The default fills `30+` only on such a row, but cannot clear it when the
    row changes, for example to Enhanced, without also refusing a `30+` the
    surveyor chose. A `30+` left behind credits the habitat at once with
    gains it has not made, so the form shows a warning beside it. The row
    can still be saved.
    """
    return (f'coalesce("{advance}", \'\') <> {DEGRADED_ADVANCE} '
            f'OR ({degraded(kind)})')


ADVANCE_WARNING = ("30+ years created in advance is for a habitat whose "
                   "condition gets worse: Created, the same habitat type as "
                   "the baseline, and a worse condition. Check this row: a "
                   "30+ left from an earlier choice overstates its units.")


def timing_editable(other):
    """A timing drop-down can be used only while the other is not a year above 0.

    Blank, `0` and a text value the list no longer offers all leave this
    drop-down usable. The attribute table's form view saves the row the
    moment a value is picked, before the form re-evaluates the other value,
    and the save cannot tell which value was picked last. Greying out the
    other drop-down stops both values reaching above 0 in any form, so the
    surveyor sets one back to 0 or blank before picking the other.
    only_one_timing still blanks one of them if a table cell sets both.
    """
    return f'coalesce("{other}", \'0\') NOT IN ({YEARS_ABOVE_ZERO})'


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
        years = ("map", YEAR_VALUES)
        rules.append((advance, years, False,
                      advance_default(kind, advance, delay), "1"))
        rules.append((delay, years, False,
                      only_one_timing(delay, advance), "1"))
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


def element_span(block, name):
    """Start, end, indent and text of the first `<name>` element.

    The closing tag is found with a direct search. A `.*?` match backtracks
    over the whole layer when the closing tag is missing, which is
    super-linear.
    """
    open_tag = f"<{name}>"
    close_tag = f"</{name}>"
    open_at = block.find(open_tag)
    if open_at < 0:
        return None
    close_at = block.find(close_tag, open_at + len(open_tag))
    if close_at < 0:
        return None
    start = open_at
    while start > 0 and block[start - 1] in " \t":
        start -= 1
    end = close_at + len(close_tag)
    return start, end, block[start:open_at], block[start:end]


def set_editable(block, field, locked):
    """Set the field's entry in the layer's <editable> list, adding it if
    the list has none."""
    value = "0" if locked else "1"
    wanted = f'<field name="{escape(field)}" editable="{value}"/>'
    empty = re.search(r"^(?P<pad>[ \t]*)<editable/>", block, re.M)
    if empty is not None:
        pad = empty.group("pad")
        return (block[:empty.start()] + f"{pad}<editable>\n{pad}  {wanted}\n"
                f"{pad}</editable>" + block[empty.end():])
    found = element_span(block, "editable")
    if found is None:
        raise SystemExit("a data layer has no <editable> list")
    start, end, pad, text = found
    entry = re.compile(r'<field name="' + re.escape(escape(field))
                       + r'" editable="[01]"/>')
    if entry.search(text):
        text = entry.sub(wanted, text)
    else:
        text = text.replace("<editable>", f"<editable>\n{pad}  {wanted}", 1)
    return block[:start] + text + block[end:]


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


def empty_properties(block):
    """Start, end and indent of a self-closing data-defined properties tag.

    The tag is read from the start of its line. An unanchored `[ \t]*` before
    the tag retries across a run of spaces when the tag is missing, which is
    super-linear.
    """
    tag = "<dataDefinedFieldProperties/>"
    line = 0
    while line < len(block):
        indent = line
        while indent < len(block) and block[indent] in " \t":
            indent += 1
        if block.startswith(tag, indent):
            return line, indent + len(tag), block[line:indent]
        newline = block.find("\n", line)
        if newline < 0:
            return None
        line = newline + 1
    return None


def without_field(text, field):
    """Drop this field's `<field>` block, including the indent on its line.

    The end tag is found with a direct search. A `.*?` match backtracks over
    the section when the end tag is missing, which is super-linear.
    """
    open_tag = f'<field name="{escape(field)}">'
    close_tag = "</field>\n"
    at = 0
    while True:
        found = text.find(open_tag, at)
        if found < 0:
            return text
        start = found
        while start > 0 and text[start - 1] in " \t":
            start -= 1
        close_at = text.find(close_tag, found + len(open_tag))
        if close_at < 0:
            return text
        text = text[:start] + text[close_at + len(close_tag):]
        at = start


def set_editable_when(block, field, expression):
    """Make the field editable in the form only while the expression holds."""
    found = empty_properties(block)
    entry = DD_FIELD.format(p="{p}", name=escape(field),
                            expression=escape(expression))
    if found is not None:
        start, end, pad = found
        return (block[:start] + f"{pad}<dataDefinedFieldProperties>\n"
                + entry.format(p=pad) + f"{pad}</dataDefinedFieldProperties>"
                + block[end:])
    section = element_span(block, "dataDefinedFieldProperties")
    if section is None:
        raise SystemExit("a data layer has no <dataDefinedFieldProperties>")
    start, end, pad, text = section
    text = without_field(text, field)
    text = text.replace(f"{pad}</dataDefinedFieldProperties>",
                        entry.format(p=pad)
                        + f"{pad}</dataDefinedFieldProperties>", 1)
    return block[:start] + text + block[end:]


def set_soft_constraint(block, field, expression, description, errors,
                        layer):
    """Give the field an expression constraint that warns, and does not
    refuse the row."""
    start, end, tag = require_shape.element("constraints", field, block)
    flags = int(re.search(r'\bconstraints="(\d+)"', tag).group(1))
    new_tag = require_shape.set_attribute(
        tag, "constraints", flags | require_shape.EXPRESSION_FLAG)
    new_tag = require_shape.set_attribute(new_tag, "exp_strength", SOFT)
    block = block[:start] + new_tag + block[end:]
    start, end, tag = require_shape.element("constraintExpressions", field,
                                            block)
    current = html.unescape(re.search(r'\bexp="([^"]*)"', tag).group(1))
    if current and current != expression and DEGRADED_ADVANCE not in current:
        errors.append(f"{layer}: {field!r} already has a constraint no tool "
                      f"wrote: {current}")
        return block
    new_tag = require_shape.set_attribute(tag, "exp", escape(expression))
    new_tag = require_shape.set_attribute(new_tag, "desc", escape(description))
    return block[:start] + new_tag + block[end:]


def set_post_rules(block, kind, layer, errors):
    """Grey out significance and the timing pair, and warn on a stale 30+."""
    block = set_editable_when(block, PROPOSED_SIGNIFICANCE,
                              SIGNIFICANCE_EDITABLE)
    advance, delay = TIMING[kind]
    block = set_editable_when(block, advance, timing_editable(delay))
    block = set_editable_when(block, delay, timing_editable(advance))
    if kind in DEGRADED_KINDS:
        block = set_soft_constraint(block, advance,
                                    advance_warning(kind, advance),
                                    ADVANCE_WARNING, errors, layer)
    return block


def rewrite_layer(block, ids, errors, changed):
    """Return the layer block with its filled and locked columns set."""
    name = paste_lineage.LAYER_NAME.search(block)
    if name is None or name.group(1) not in LAYERS:
        return block
    layer = name.group(1)
    kind, stage = LAYERS[layer]
    before = block
    for field, widget, locked, expression, on_update in rules_for(
            kind, stage, ids):
        if widget is not None:
            block = set_widget(block, field, widget, ids, errors, layer)
        block = set_editable(block, field, locked)
        block = set_default(block, field, expression, on_update, errors,
                            layer)
    if stage == POST:
        block = set_post_rules(block, kind, layer, errors)
    if block != before:
        changed.append(layer)
    return block


def rewrite(xml):
    known = paste_lineage.layers(xml)
    ids = {name: layer_id for name, (layer_id, _) in known.items()}
    errors, changed = [], []

    def layer(match):
        return rewrite_layer(match.group(0), ids, errors, changed)

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
