"""The rules that give a pasted post-intervention feature its lineage.

A surveyor can fill a post-intervention layer with the Copy button, or by
copying baseline features and pasting them into it. The button writes the
lineage itself. A paste goes through QGIS, which fills each column from its
default value expression. The expressions built here make a paste write what
the button writes.

A pasted feature takes its lineage from the one baseline feature whose
geometry is exactly the same as its own. When no baseline feature is the
same, or more than one is, the feature gets no lineage.

Two tools write these expressions, and both import this module:

- `set_paste_defaults.py` writes the lineage columns, which have no other
  default.
- `reset_stale_dropdowns.py` puts the pre-fill for Retention Category and the
  Proposed values into the reset rules that it already owns on those fields.
"""
import re
import xml.etree.ElementTree as ET

# Post-intervention layer -> (its baseline layer, the baseline's ref column).
# The names are the ones the buttons use.
PARENTS = {
    "Area Habitats Post-Intervention":
        ("Area Habitats Baseline", "Habitat Ref"),
    "Hedgerows Post-Intervention":
        ("Hedgerows Baseline", "Habitat Ref"),
    "Individual Trees Post-Intervention":
        ("Individual Trees Baseline", "Habitat Ref"),
    "Vertical Area Habitats Post-Intervention":
        ("Vertical Area Habitats Baseline", "Habitat Ref"),
    "Watercourses Post-Intervention":
        ("Watercourses Baseline", "Habitat Ref"),
}

# The Copy button writes parent_geom with asWkt(3). geom_to_wkt(g, 3) is the
# same call, so a pasted row and a copied row hold the same text.
WKT_DECIMALS = 3

UUID = '"feature_uuid"'

RETENTION = "Retention Category"
RETAINED = "'Retained'"
PROPOSED = "Proposed "
BASELINE = "Baseline "

# A row with no shape has no baseline twin. Every lookup tests this first, so
# a paste of rows with no shape reads nothing from the baseline. That paste is
# what Paste Features makes of the text Copy Layer leaves on the clipboard:
# one row per line of the layer's XML, often thousands.
SHAPED = "$geometry IS NOT NULL"

# Every default written by these tools reads the baseline through this call.
# A tool may therefore replace a default that contains it: it wrote it.
MARKER = "overlay_equals(layer:="

MAPLAYER = re.compile(r"<maplayer\b.*?</maplayer>", re.S)
LAYER_ID = re.compile(r"<id>([^<]+)</id>")
LAYER_NAME = re.compile(r"<layername>([^<]*)</layername>")


def matches(baseline_id, expression):
    """An array of the expression's value on each baseline feature that has
    exactly the same geometry as the feature being created.

    overlay_equals compares vertex by vertex, in order. It finds the
    candidates through the baseline's spatial index. The cache stays off: on
    this template it reads the whole baseline once per paste, which costs more
    than it saves for anything but a very large paste.
    """
    return (f"overlay_equals(layer:='{baseline_id}', "
            f"expression:={expression}, cache:=false)")


def lookup(baseline_id, expression):
    """The expression's value on the one matching baseline feature, or NULL."""
    return (f"if({SHAPED}, with_variable('m', "
            f"{matches(baseline_id, expression)}, "
            f"if(array_length(@m) = 1, @m[0], NULL)), NULL)")


def gate(baseline_id):
    """True while a feature that equals one baseline feature is created.

    QGIS fills the columns of a new feature in column order, and a default
    sees NULL in its own column and in every later one. parent_uuid is near
    the end of each post-intervention table, so it is NULL while the feature
    is created. After that it holds the parent's id, so the gate is false on
    every later edit of the row, and a value the surveyor cleared stays
    cleared.

    "Being created" is not only a paste from the baseline. QGIS builds a
    feature column by column in the same way for Split Features, Duplicate
    Feature and a paste of a post-intervention row, from the same layer or
    from another file. parent_uuid is NULL during each of them, so the gate
    is true whenever the new shape equals one baseline feature. A default
    applied on update then replaces the value the row brought with it. See
    prefill_gate for the part of that which a column before can prevent.

    QGIS stops at the first false term of an AND, so a row with no shape
    never reaches the baseline lookup.
    """
    return (f'{SHAPED} AND "parent_uuid" IS NULL AND '
            f"array_length({matches(baseline_id, UUID)}) = 1")


def prefill_gate(baseline_id, field):
    """The gate of the pre-fill of one column.

    A Proposed value is pre-filled only on a row that is Retained, because
    Copy writes the Baseline twin only beside Retained. Retention Category
    comes before every Proposed column, so its value is already set when a
    Proposed default runs. On area and vertical area habitats that value is
    the one the row brought with it, since its default is applied only when
    the value is blank. A split, duplicated or re-pasted Enhanced or Created
    row therefore keeps its Proposed values there. On hedgerows, trees and
    watercourses Retention Category is itself a pre-fill applied on update,
    so no column before it tells a paste from the baseline apart from the
    other cases.
    """
    when = gate(baseline_id)
    if field.startswith(PROPOSED):
        return f'{when} AND "{RETENTION}" = {RETAINED}'
    return when


def copy_value(field, names, baseline_names):
    """What the Copy button writes into a filtered drop-down, or None.

    It writes Retained into Retention Category, and the Baseline twin into
    each Proposed value whose twin both layers have.
    """
    if field == RETENTION:
        return RETAINED
    if field.startswith(PROPOSED):
        twin = BASELINE + field[len(PROPOSED):]
        if twin in names and twin in baseline_names:
            return f'"{twin}"'
    return None


def layers(xml):
    """Map layer name -> (layer id, [field names]) for every layer."""
    found = {}
    for block in MAPLAYER.findall(xml):
        name = LAYER_NAME.search(block)
        layer_id = LAYER_ID.search(block)
        if name is None or layer_id is None:
            continue
        found[name.group(1)] = (layer_id.group(1), field_names(block))
    return found


def field_names(block):
    config = re.search(r"<fieldConfiguration>.*?</fieldConfiguration>",
                       block, re.S)
    if config is None:
        return []
    return [f.get("name")
            for f in ET.fromstring(config.group(0)).findall("field")]


def parent_of(name, known):
    """(baseline id, baseline field names, ref column) for a post-intervention
    layer, or None for any other layer."""
    if name not in PARENTS:
        return None
    baseline, ref = PARENTS[name]
    if baseline not in known:
        raise SystemExit(f"{name}: its baseline layer {baseline!r} is missing")
    baseline_id, baseline_names = known[baseline]
    return baseline_id, baseline_names, ref
