"""Build the UKHab symbology copy of the BNG Service template.

`templates/bng-service-ukhab/` is `templates/bng-service/` with the map
styles of the Natural England template (`templates/legacy-ne/`): its
extended UKHab colours and patterns, without its labels. It is a separate folder so that the
BNG Service template stays as it is until the styles are cleared for
public use.

The copy is built, not edited. This tool copies the BNG Service template and
changes only its map styles, so the two templates always have the same
GeoPackage, reference lists, forms, buttons and rules. Build it again after
every change to `templates/bng-service/`:

    python3 development/tools/build_ukhab_template.py [--check]

With `--check` it writes nothing. It builds the copy in a temporary folder,
says which files differ from the committed copy, and exits with 1 if any do.

What it changes in the project:

- The renderer of each data layer is replaced by the renderer of its
  Natural England layer, and so is its opacity, but not its labels. The tree style
  then gets the `Enhanced` rules of `style_enhanced_trees.py`, as Natural
  England has none. The vertical
  area habitat layers keep their own renderer, because Natural England has
  no such layers.
- Each layer group gets a group of view-only layers, as in the Natural
  England template: Condition, Distinctiveness and Retention. Each one reads
  the same GeoPackage table as a data layer, and is read-only.

Natural England stores a list label with its list number, such as
`4. Fairly Poor`. The BNG Service template stores the words only, so each
value is changed to the words. `Lost` is not a value in the BNG Service
template, which records a loss by leaving the feature out, so the styles for
it are dropped, with one exception: the Natural England area habitat list
pairs `Lost` with `To be created`, so its style is used for `Created`.
`templates/README.md` lists each difference from the Natural England styles.

The tool changes the project file as text, as the other tools do, so every
byte that is not a map style stays as it is in the BNG Service template.
"""
import hashlib
import io
import re
import sys
import xml.etree.ElementTree as ET

import template_copy
from style_enhanced_trees import add_enhanced_rules

TEMPLATES = template_copy.TEMPLATES
TARGET_DIR = TEMPLATES / "bng-service-ukhab"
LEGACY_DIR = TEMPLATES / "legacy-ne"
TARGET_PROJECT = "BNG Service Habitat Mapping - UKHab symbology.qgz"
LEGACY_PROJECT = LEGACY_DIR / "Net Gain Habitat Mapping.qgz"
PROJECT_TITLE = "BNG Service Habitat Mapping - UKHab symbology"

# Data layer of the BNG Service template -> its Natural England layer.
MAIN_LAYERS = {
    "Red Line Boundary": "Red Line Boundary",
    "Area Habitats Baseline": "Habitats Baseline EDIT ME",
    "Area Habitats Post-Intervention": "Habitats Proposed EDIT ME",
    "Hedgerows Baseline": "Hedgerow Baseline EDIT ME",
    "Hedgerows Post-Intervention": "Hedgerows Proposed EDIT ME",
    "Watercourses Baseline": "Watercourse Baseline EDIT ME",
    "Watercourses Post-Intervention": "Watercourse Proposed EDIT ME",
    "Individual Trees Baseline": "Individual tree Baseline (EDIT ME) copy",
    "Individual Trees Post-Intervention":
        "Individual tree Proposed (EDIT ME) copy",
}

# Layer group of the BNG Service template -> (name of the new view-only
# group, [(Natural England view-only layer, BNG Service table it reads)]).
# The layers keep their Natural England names, and their order, except where
# a name is taken: `VIEW_NAMES` gives the name the layer gets instead.
VIEW_GROUPS = {
    "Area Habitats": ("Habitat Graphics (VIEW ONLY)", [
        ("Baseline Habitat Condition", "Area Habitats Baseline"),
        ("Baseline Habitat Distinctiveness", "Area Habitats Baseline"),
        ("Habitats Retention", "Area Habitats Post-Intervention"),
        ("Proposed Habitats Condition", "Area Habitats Post-Intervention"),
        ("Proposed Habitats Distinctiveness",
         "Area Habitats Post-Intervention"),
    ]),
    "Hedgerows": ("Hedgerow Graphics (VIEW ONLY)", [
        ("Baseline Hedgerow Condition", "Hedgerows Baseline"),
        ("Baseline Hedgerow Distinctiveness", "Hedgerows Baseline"),
        ("Hedgerow Retention", "Hedgerows Post-Intervention"),
        ("Proposed Hedgerow Condition", "Hedgerows Post-Intervention"),
        ("Proposed Hedgerow Distinctiveness", "Hedgerows Post-Intervention"),
    ]),
    "Watercourses": ("Watercourse Graphics (VIEW ONLY)", [
        ("Baseline Watercourse Condition", "Watercourses Baseline"),
        ("Baseline Watercourse Distinctiveness", "Watercourses Baseline"),
        ("Watercourse Retention", "Watercourses Post-Intervention"),
        ("Proposed Watercourse Condition", "Watercourses Post-Intervention"),
        ("Proposed Watercourse Distinctiveness",
         "Watercourses Post-Intervention"),
    ]),
    "Individual Trees": ("Individual tree Graphics (VIEW ONLY)", [
        ("Individual tree Retention", "Individual Trees Post-Intervention"),
        ("Baseline Individual tree Condition", "Individual Trees Baseline"),
        ("Proposed Individual tree Condition",
         "Individual Trees Post-Intervention"),
    ]),
}

# The BNG Service project already has a reference list layer named
# `Individual tree Retention`. So has the Natural England one, which is why
# it holds that name twice. Two layers must not share a name: a drop-down
# finds its list layer by name when its id does not match.
VIEW_NAMES = {"Individual tree Retention": "Individual tree Retention (VIEW ONLY)"}

# The Natural England area habitat list pairs `Lost` with `To be created`:
# the baseline habitat is lost and a new one created. A BNG Service row that
# records that is `Created`.
AREA_RETENTION_LAYER = "Habitats Retention"
LIST_NUMBER_RE = re.compile(r"^\d+\. ")
LOST_RE = re.compile(r"""(^|[\s(])"Retention Category"\s*=\s*'Lost'""")
# Baseline trees have no Category column: every baseline tree is existing.
TREE_CATEGORY_RE = re.compile(r"""\s*"Category"\s*=\s*'Existing'\s*(AND\s*)?""")


def fail(message):
    template_copy.fail("build_ukhab_template.py", message)


def layer_span(xml, name):
    return template_copy.layer_span(xml, name, "build_ukhab_template.py")


# --- Reading the projects ---------------------------------------------------

def legacy_layers(root):
    """Natural England layers by name. A name used twice keeps the layer that
    has a renderer: the hidden data group repeats some names without one."""
    found = {}
    for layer in root.iter("maplayer"):
        name = layer.findtext("layername")
        if layer.find("renderer-v2") is not None or name not in found:
            found[name] = layer
    return found


# --- Turning a Natural England style into a BNG Service one -----------------

def words(value):
    """`4. Fairly Poor` -> `Fairly Poor`. Other values are unchanged."""
    return LIST_NUMBER_RE.sub("", value) if value else value


def rewrite_filter(expression):
    """Remove the list numbers from the quoted values of a rule filter."""
    return re.sub(r"'(\d+)\. ", "'", expression)


def convert_renderer(renderer, legacy_name):
    """Rewrite a Natural England renderer for BNG Service values, in place."""
    if renderer.get("type") == "categorizedSymbol":
        convert_categories(renderer, legacy_name)
    elif renderer.get("type") == "RuleRenderer":
        convert_rules(renderer)
    drop_unused_symbols(renderer)


def convert_categories(renderer, legacy_name):
    categories = renderer.find("categories")
    for category in list(categories):
        value = words(category.get("value"))
        if value == "Lost":
            if legacy_name != AREA_RETENTION_LAYER:
                categories.remove(category)
                continue
            value = "Created"
            category.set("label", "Created")
        category.set("value", value)
        category.set("label", words(category.get("label")))


def convert_rules(renderer):
    for parent in renderer.iter():
        for rule in list(parent.findall("rule")):
            expression = rule.get("filter")
            if expression is not None:
                if LOST_RE.search(expression):
                    parent.remove(rule)
                    continue
                # A rule left with no condition was the catch-all for an
                # existing tree whose details are not complete.
                expression = TREE_CATEGORY_RE.sub(" ", expression).strip()
                rule.set("filter", rewrite_filter(expression) or "ELSE")
            if rule.get("label"):
                rule.set("label", words(rule.get("label")))


def drop_unused_symbols(renderer):
    """Drop the symbols no category or rule names. A single symbol renderer
    names none: its one symbol is the symbol."""
    if renderer.get("type") not in ("categorizedSymbol", "RuleRenderer"):
        return
    used = {c.get("symbol") for c in renderer.iter("category")}
    used |= {r.get("symbol") for r in renderer.iter("rule")}
    symbols = renderer.find("symbols")
    for symbol in list(symbols):
        if symbol.get("name") not in used:
            symbols.remove(symbol)


def fragment(element, indent):
    """Serialise a Natural England element at the indent of the project."""
    ET.indent(element, space="  ", level=indent // 2)
    text = ET.tostring(element, encoding="unicode", short_empty_elements=True)
    return " " * indent + text.rstrip()


# --- Changing the BNG Service project ---------------------------------------

def replace_element(block, tag, new_text):
    """Replace the one <tag ...>...</tag> (or <tag .../>) in a layer block."""
    pattern = re.compile(
        rf"( *)<{tag}(?:\s[^>]*)?(?:/>|>.*?</{tag}>)", re.DOTALL)
    matches = list(pattern.finditer(block))
    if len(matches) != 1:
        fail(f"expected one <{tag}> in a layer, found {len(matches)}")
    match = matches[0]
    return block[:match.start()] + new_text + block[match.end():]




def restyle_layer(block, legacy):
    """Give a BNG Service layer block the style of a Natural England layer."""
    renderer = legacy.find("renderer-v2")
    convert_renderer(renderer, legacy.findtext("layername"))
    block = replace_element(block, "renderer-v2", fragment(renderer, 6))
    opacity = legacy.findtext("layerOpacity") or "1"
    block = replace_element(block, "layerOpacity",
                            f"      <layerOpacity>{opacity}</layerOpacity>")
    # Labels are not taken: the layer keeps its own, which is none.
    return block


def view_layer_id(name):
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]
    return re.sub(r"\W+", "_", name).strip("_") + "_ukhab_" + digest


def view_layer_block(xml, table, name, legacy):
    """A read-only layer on a BNG Service table, with a Natural England style.

    It takes the data source part of the data layer it reads, up to its
    elevation settings, and none of its form, buttons or rules: it is for
    viewing only.
    """
    start, end = layer_span(xml, table)
    source = xml[start:end]
    if "</elevation>" not in source:
        fail(f"no <elevation> in layer {table!r}")
    head = source[:source.index("</elevation>") + len("</elevation>")]
    layer_id = re.search(r"<id>([^<]*)</id>", head).group(1)
    head = head.replace(f"<id>{layer_id}</id>", f"<id>{view_layer_id(name)}</id>", 1)
    head = head.replace(f"<layername>{table}</layername>",
                        f"<layername>{name}</layername>", 1)
    head = template_copy.set_layer_attribute(head, "readOnly", "1")
    block = head + (
        "\n      <renderer-v2/>"
        "\n      <customproperties>\n        <Option/>\n      </customproperties>"
        "\n      <blendMode>0</blendMode>"
        "\n      <featureBlendMode>0</featureBlendMode>"
        "\n      <layerOpacity>1</layerOpacity>"
        '\n      <legend type="default-vector" showLabelLegend="0"/>'
        "\n    </maplayer>")
    return restyle_layer(block, legacy)


def tree_layer_entry(xml, table, name):
    """The <layer-tree-layer> of a view-only layer, made from its table's."""
    entry_re = re.compile(
        rf'( *)<layer-tree-layer [^>]*name="{re.escape(table)}"[^>]*>.*?'
        r"</layer-tree-layer>", re.DOTALL)
    match = entry_re.search(xml)
    if match is None:
        fail(f"no layer tree entry for {table!r}")
    entry = match.group(0).strip()
    layer_id = re.search(r' id="([^"]*)"', entry).group(1)
    entry = entry.replace(f' id="{layer_id}"', f' id="{view_layer_id(name)}"')
    entry = entry.replace(f' name="{table}"', f' name="{name}"')
    return re.sub(r"\n {6}", "\n" + " " * 8, "        " + entry)


def add_view_groups(xml, legacy):
    new_layers, new_ids = [], []
    for group, (view_group, layers) in VIEW_GROUPS.items():
        entries = []
        for legacy_name, table in layers:
            if legacy_name not in legacy:
                fail(f"no Natural England layer named {legacy_name!r}")
            name = VIEW_NAMES.get(legacy_name, legacy_name)
            if f"<layername>{name}</layername>" in xml:
                fail(f"the project already has a layer named {name!r}")
            new_layers.append(
                view_layer_block(xml, table, name, legacy[legacy_name]))
            entries.append(tree_layer_entry(xml, table, name))
            new_ids.append(view_layer_id(name))
        group_xml = (
            f'      <layer-tree-group expanded="0" name="{view_group}" '
            'groupLayer="" checked="Qt::Unchecked">\n'
            "        <customproperties>\n          <Option/>\n"
            "        </customproperties>\n"
            + "\n".join(entries) + "\n      </layer-tree-group>\n")
        opening = re.search(
            rf'    <layer-tree-group [^>]*name="{re.escape(group)}"[^>]*>', xml)
        if opening is None:
            fail(f"no layer group named {group!r}")
        # The group's own closer starts its line; a subgroup's is deeper.
        close = xml.index("\n    </layer-tree-group>", opening.end()) + 1
        xml = xml[:close] + group_xml + xml[close:]
    # The layers, in the project's layer list and its drawing order list.
    close = xml.index("  </projectlayers>")
    xml = xml[:close] + "".join("    " + b.strip() + "\n" for b in new_layers) + xml[close:]
    close = xml.index("    </custom-order>")
    xml = xml[:close] + "".join(f"      <item>{i}</item>\n" for i in new_ids) + xml[close:]
    # No snapping to a view-only copy of a layer that is already snapped to.
    close = xml.index("    </individual-layer-settings>")
    xml = xml[:close] + "".join(
        f'      <layer-setting tolerance="12" maxScale="0" enabled="0" id="{i}" '
        'type="1" minScale="0" units="1"/>\n' for i in new_ids) + xml[close:]
    return xml


def change_project(source_xml):
    legacy_qgs, _, payload = template_copy.read_qgz(LEGACY_PROJECT)
    legacy_root = ET.parse(io.BytesIO(payload[legacy_qgs])).getroot()
    legacy = legacy_layers(legacy_root)
    xml = source_xml
    for name, legacy_name in MAIN_LAYERS.items():
        start, end = layer_span(xml, name)
        xml = xml[:start] + restyle_layer(xml[start:end], legacy[legacy_name]) + xml[end:]
    xml = add_view_groups(xml, legacy)
    # The Natural England tree style has no Enhanced rules: add them, as the
    # BNG Service template has them.
    xml, _ = add_enhanced_rules(xml)
    xml = template_copy.set_title(xml, PROJECT_TITLE)
    return xml


def main(argv=None):
    return template_copy.main(argv, __doc__, "build_ukhab_template.py",
                              TARGET_DIR, TARGET_PROJECT, change_project)


if __name__ == "__main__":
    sys.exit(main())
