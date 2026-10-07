"""Blank a drop-down value when an earlier choice makes it invalid.

Most of the template's drop-downs are filtered by an earlier choice: the
condition list shows only the conditions the Metric allows for the chosen
habitat. QGIS applies that filter to the list and not to the value already
chosen. Change the habitat after picking a condition and the old condition
stays, shown in brackets, as `(Good)`, and saves like any other value.

This gives every filtered drop-down a default value expression, applied on
update, that keeps the value while it is still in the filtered list and
blanks it otherwise. The expression is generated from the drop-down's own
reference list, key column and filter, so it can never disagree with the list
the user is shown. A valid value is never touched.

A condition or Irreplaceable Habitat drop-down whose filtered list allows one
value only takes that value by itself, and keeps it while the list allows it.

A drop-down whose filter reads a column the layer does not have is skipped and
reported: QGIS ignores such a filter and offers the whole list, so there is no
narrower list to hold a value to.

On a post-intervention layer the same expression also pre-fills a pasted
feature, as the Copy button fills a copied row: Retention Category becomes
Retained and each Proposed value takes its Baseline twin. The pre-fill is
part of the reset because QGIS keeps one default per column. It applies only
while a feature that equals one baseline feature is created, and only to a
blank value. A Proposed value is pre-filled only on a Retained row (see
paste_lineage.py).

    python3 development/tools/reset_stale_dropdowns.py [--check] <project.qgz> [...]

Edits the `<default>` elements in place and leaves every other byte alone,
for the same reasons as qgz_actions.py. Running it twice changes nothing.
With --check it writes nothing, lists what it would change, and exits 1 if
anything would change.
"""
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import paste_lineage                                            # noqa: E402
from qgz_actions import escape, read_project, write_project     # noqa: E402

CURRENT_VALUE = re.compile(r"current_value\(\s*'([^']+)'\s*\)")
CHECK = "--check"
MAPLAYER = re.compile(r"<maplayer\b.*?</maplayer>", re.S)
LAYER_ID = re.compile(r"<id>([^<]+)</id>")


def default_element(field):
    # Attribute by attribute rather than [^>]*, because QGIS leaves `>`
    # unescaped inside an attribute and the reset expression contains one.
    return re.compile(
        r'<default\b(?=(?:\s+[\w-]+="[^"]*")*?\s+field="'
        + re.escape(escape(field)) + r'")(?:\s+[\w-]+="[^"]*")*\s*/>')


def options(widget):
    return {o.get("name"): o.get("value")
            for o in widget.iter("Option") if o.get("name")}


def parent_filter(filter_expr):
    """The drop-down's filter, as an aggregate over its list sees it."""
    return CURRENT_VALUE.sub(
        lambda m: f"attribute(@parent, '{m.group(1)}')", filter_expr.strip())


def in_list(field, rule):
    """True while the field's value is in its filtered list."""
    layer_id, key, filter_expr = rule
    return (f"coalesce(aggregate(layer:='{layer_id}', aggregate:='count', "
            f'expression:="{key}", filter:=({parent_filter(filter_expr)}) '
            f"AND \"{key}\" = attribute(@parent, '{field}')), 0) > 0")


def ancestors(field, rules, seen=()):
    """The filtered drop-downs this one's list depends on, nearest first."""
    found = []
    for name in CURRENT_VALUE.findall(rules[field][2]):
        if name in rules and name not in seen and name != field:
            found.append(name)
            found += ancestors(name, rules, seen + (field, name))
    return list(dict.fromkeys(found))


def reset_expression(field, rules, prefill=None):
    """Keep the value while it and every choice above it are still valid.

    The choices above are checked as well as the field's own list so that the
    expression names them. The attribute form re-evaluates a default only
    when a field it names changes, so without them a change of broad habitat
    type would blank the habitat type on screen and leave the condition below
    it showing until the form is saved. A blank choice above is accepted: a
    newly planted tree has no baseline size, and its proposed size is valid.

    A blank value stays blank, unless a pre-fill is given. The pre-fill is an
    expression that gives NULL whenever it does not apply.
    """
    checks = [in_list(field, rules[field])]
    checks += [f'("{a}" IS NULL OR {in_list(a, rules[a])})'
               for a in ancestors(field, rules)]
    blank = prefill or "NULL"
    return (f'if("{field}" IS NULL, {blank}, '
            f'if({" AND ".join(checks)}, "{field}", NULL))')


def fills_single(field):
    """True for a drop-down that takes its only choice by itself.

    A condition list can allow one condition only, such as `N/A - Other` for
    Developed land; sealed surface. The irreplaceable list can allow `No`
    only, or `Yes` only. The surveyor can still change the value.
    """
    return field.endswith(" Condition") or field == "Irreplaceable Habitat"


def single_fill(rule, otherwise):
    """The only value the filtered list allows, else `otherwise`."""
    layer_id, key, filter_expr = rule
    return (f"with_variable('only', array_distinct(aggregate("
            f"layer:='{layer_id}', aggregate:='array_agg', "
            f'expression:="{key}", filter:=({parent_filter(filter_expr)}))), '
            f"if(array_length(@only) = 1, @only[0], {otherwise}))")


def rule_expression(field, rules, prefill=None):
    """The reset, with the only choice filled in where the list has one."""
    reset = reset_expression(field, rules, prefill)
    if fills_single(field):
        return single_fill(rules[field], reset)
    return reset


def prefills(layer_name, names, fields, known):
    """Field -> the pre-fill of a pasted feature, on a post-intervention layer.

    The value is the one the Copy button writes, and it is written only while
    a feature that equals one baseline feature is created.
    """
    parent = paste_lineage.parent_of(layer_name, known)
    if parent is None:
        return {}
    baseline_id, baseline_names, _ref = parent
    found = {}
    for field in fields:
        value = paste_lineage.copy_value(field, names, baseline_names)
        if value is not None:
            gate = paste_lineage.prefill_gate(baseline_id, field)
            found[field] = f"if({gate}, {value}, NULL)"
    return found


def filter_rule(field, locked, names):
    """Return (rule, missing) for one field.

    rule is (layer id, key, filter) for a drop-down this tool manages, and
    None for any other field. missing lists the columns that a drop-down's
    filter reads and the layer does not have; such a drop-down is skipped.
    """
    widget = field.find("editWidget")
    if widget is None or widget.get("type") != "ValueRelation":
        return None, []
    opts = options(widget)
    filter_expr = opts.get("FilterExpression") or ""
    if not filter_expr.strip() or field.get("name") in locked:
        return None, []
    needs = set(CURRENT_VALUE.findall(filter_expr))
    # With no current_value() the filter is fixed, such as on-site spatial
    # risk: no other choice can change the list, so no value can go stale.
    missing = sorted(needs - names)
    if not needs or missing:
        return None, missing
    return (opts["Layer"], opts["Key"], filter_expr), []


def plan(xml):
    """Map layer id -> [(field, expression)], and list what was skipped."""
    wanted, skipped = {}, []
    known = paste_lineage.layers(xml)
    for layer in ET.fromstring(xml).iter("maplayer"):
        config = layer.find("fieldConfiguration")
        if config is None:
            continue
        layer_name = layer.findtext("layername")
        names = {f.get("name") for f in config.findall("field")}
        # A locked column is written only by the Actions, from a baseline
        # that already had to pass its own resets. Refresh writes those
        # columns one at a time, so a reset there would see a new broad type
        # beside the old habitat, blank the habitat's children, and Refresh
        # would never write them back, because their values did not change.
        locked = {f.get("name") for f in layer.iter("editable")
                  for f in f.findall("field") if f.get("editable") == "0"}
        rules = {}
        for field in config.findall("field"):
            rule, missing = filter_rule(field, locked, names)
            if missing:
                skipped.append((layer_name, field.get("name"), missing))
            if rule is not None:
                rules[field.get("name")] = rule
        if rules:
            fills = prefills(layer_name, names, rules, known)
            wanted[layer.findtext("id")] = [
                (name, rule_expression(name, rules, fills.get(name)))
                for name in rules]
    return wanted, skipped


def rewrite_layer(block, fields):
    changed = 0
    for field, expression in fields:
        element = (f'<default field="{escape(field)}" '
                   f'expression="{escape(expression)}" applyOnUpdate="1"/>')
        found = default_element(field).search(block)
        if found is None:
            raise SystemExit(f"no <default> element for field {field!r}")
        if found.group(0) == element:
            continue
        current = re.search(r'\bexpression="([^"]*)"', found.group(0)).group(1)
        if current and "attribute(@parent" not in current:
            raise SystemExit(f"{field!r} already has its own default: {current}")
        block = block[:found.start()] + element + block[found.end():]
        changed += 1
    return block, changed


def main(argv):
    check = CHECK in argv
    paths = [a for a in argv if a != CHECK]
    pending = 0
    for path in paths:
        qgs, payload = read_project(path)
        xml = payload[qgs].decode("utf-8")
        wanted, skipped = plan(xml)
        total = 0

        def replace(match):
            nonlocal total
            block = match.group(0)
            layer_id = LAYER_ID.search(block).group(1)
            if layer_id not in wanted:
                return block
            block, count = rewrite_layer(block, wanted[layer_id])
            total += count
            return block

        new_xml = MAPLAYER.sub(replace, xml)
        for layer, field, missing in skipped:
            print(f"skipped {layer} / {field}: filter reads {missing}, "
                  "which the layer does not have")
        if new_xml == xml:
            print(f"no change needed: {path}")
            continue
        if check:
            pending += total
            print(f"{total} drop-down reset(s) out of date in {path}")
            continue
        write_project(path, qgs, payload, new_xml)
        print(f"wrote {total} drop-down reset(s) to {path}")
    return 1 if pending else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
