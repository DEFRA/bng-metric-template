"""Build the labelled copy of the BNG Service template.

`templates/bng-service-labels/` is `templates/bng-service/` with a label on
every habitat feature: its `Habitat Ref` on the baseline layers, and its
`Habitat Ref` with its Retention Category on the post-intervention layers,
such as `AH-004-2 (Enhanced)`. It is for testing with users whether labels
help, so it is a separate folder and `bng-service/` is unchanged.

The copy is built, not edited, as `build_ukhab_template.py` builds its copy.
Build it again after every change to `templates/bng-service/`:

    python3 development/tools/build_labels_template.py [--check]

Baseline labels are grey and italic, post-intervention labels black and
bold. QGIS leaves out a label that would hide another, so each label may
move: anywhere inside its area, around its tree, or to either side of its
line. Where the two stages still compete for room, the post-intervention
label wins, as it also says what happens to the feature. Some labels show
only when zoomed in.

A surveyor turns a layer's labels off and on in the Layers panel: right-click
the layer and select Show Labels.
"""
import re
import sys

import template_copy

TOOL = "build_labels_template.py"
TARGET_DIR = template_copy.TEMPLATES / "bng-service-labels"
TARGET_PROJECT = "BNG Service Habitat Mapping - Labels.qgz"
PROJECT_TITLE = "BNG Service Habitat Mapping - Labels"

KINDS = ("Area Habitats", "Vertical Area Habitats", "Hedgerows",
         "Watercourses", "Individual Trees")
BASELINE, POST = "Baseline", "Post-Intervention"
POLYGON, LINE, POINT = "polygon", "line", "point"
GEOMETRY = {"Area Habitats": POLYGON, "Vertical Area Habitats": LINE,
            "Hedgerows": LINE, "Watercourses": LINE, "Individual Trees": POINT}

BASELINE_LABEL = '"Habitat Ref"'
POST_LABEL = ('if("Retention Category" IS NULL, "Habitat Ref", '
              "concat(\"Habitat Ref\", ' (', \"Retention Category\", ')'))")

# Qgis::LabelPlacement: AroundPoint 0, Line 2, Horizontal 4.
# An area's label may go anywhere inside it (polygonPlacementFlags 2), and a
# tree's anywhere around it, so QGIS can move a label clear of another
# instead of leaving it out. A line's label runs above it on the baseline
# (flags 2 above the line, 8 map orientation) and below it on the
# post-intervention (4 below the line), with the other side to fall back on.
PLACEMENT = {
    (POLYGON, BASELINE): 'placement="4" polygonPlacementFlags="2"',
    (POLYGON, POST): 'placement="4" polygonPlacementFlags="2"',
    (LINE, BASELINE): 'placement="2" placementFlags="11" dist="0.5"',
    (LINE, POST): 'placement="2" placementFlags="13" dist="0.5"',
    (POINT, BASELINE): 'placement="0" dist="1"',
    (POINT, POST): 'placement="0" dist="1"',
}
# Where the two stages' labels compete for room, the post-intervention label
# wins: it names the feature and what happens to it. 0 to 10, QGIS default 5.
PRIORITY = {BASELINE: "3", POST: "8"}
STYLE = {
    BASELINE: 'textColor="90,90,90,255" fontItalic="1" fontWeight="50"',
    POST: 'textColor="0,0,0,255" fontItalic="0" fontWeight="75"',
}


def escape(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace('"', "&quot;"))


def labeling(kind, stage):
    """The <labeling> element of a layer, at the indent of the project."""
    expression = BASELINE_LABEL if stage == BASELINE else POST_LABEL
    placement = PLACEMENT[(GEOMETRY[kind], stage)]
    return (
        '      <labeling type="simple">\n'
        '        <settings calloutType="simple">\n'
        f'          <text-style fieldName="{escape(expression)}" '
        f'isExpression="1" fontSize="8" fontSizeUnit="Point" {STYLE[stage]} '
        'textOpacity="1" multilineHeight="1">\n'
        '            <text-buffer bufferDraw="1" bufferSize="0.8" '
        'bufferSizeUnits="MM" bufferColor="255,255,255,255" '
        'bufferOpacity="1" bufferNoFill="1" bufferJoinStyle="128"/>\n'
        '          </text-style>\n'
        '          <text-format multilineAlign="3" wrapChar=""/>\n'
        f'          <placement {placement} distUnits="MM" '
        f'overlapHandling="PreventOverlap" priority="{PRIORITY[stage]}"/>\n'
        '          <rendering drawLabels="1" obstacle="1" obstacleFactor="1" '
        'obstacleType="1" labelPerPart="0" mergeLines="0" '
        'upsidedownLabels="0" scaleVisibility="0"/>\n'
        '        </settings>\n'
        '      </labeling>\n')


def label_layer(xml, kind, stage):
    start, end = template_copy.layer_span(xml, f"{kind} {stage}", TOOL)
    block = xml[start:end]
    if "<labeling" in block:
        template_copy.fail(TOOL, f"layer {kind} {stage} already has labels")
    block = template_copy.set_layer_attribute(block, "labelsEnabled", "1")
    # QGIS writes a layer's labels before its custom properties.
    at = re.search(r"\n      <customproperties>", block)
    if at is None:
        template_copy.fail(TOOL, f"no custom properties in {kind} {stage}")
    block = (block[:at.start() + 1] + labeling(kind, stage)
             + block[at.start() + 1:])
    return xml[:start] + block + xml[end:]


def change_project(xml):
    for kind in KINDS:
        for stage in (BASELINE, POST):
            xml = label_layer(xml, kind, stage)
    return template_copy.set_title(xml, PROJECT_TITLE)


def main(argv=None):
    return template_copy.main(argv, __doc__, TOOL, TARGET_DIR,
                              TARGET_PROJECT, change_project)


if __name__ == "__main__":
    sys.exit(main())
