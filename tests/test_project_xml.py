"""The field settings in the template's QGIS project, and the tools that
keep them in step.

The project XML is read straight out of the .qgz, in memory. The maintenance
tools are run with --check against a copy of the template folder, so a tool
that misbehaved could not write to templates/.
"""

import shutil
import unittest
import xml.etree.ElementTree as ET
import zipfile

from tests import support

# QGIS stores a Value Map's NULL entry under this key
# (QgsValueMapFieldFormatter::NULL_VALUE).
NULL_VALUE = "{2839923C-8B7D-419E-B84B-CA2FE9B80EC7}"
VALUE_MAP = "ValueMap"
VALUE_RELATION = "ValueRelation"
APPLY_ON_UPDATE = "1"
LOCKED = "0"
EDITABLE = "1"
# QgsFieldConstraints: ConstraintExpression = 4, ConstraintStrengthHard = 1.
EXPRESSION_CONSTRAINT = 4
HARD = "1"
SHAPE_EXPRESSION = "$geometry IS NOT NULL"

RED_LINE = "Red Line Boundary"
AREA, VERTICAL, HEDGE, WATER, TREE = (
    "Area Habitats", "Vertical Area Habitats", "Hedgerows", "Watercourses",
    "Individual Trees")
KINDS = (AREA, VERTICAL, HEDGE, WATER, TREE)
BASELINE, POST = "Baseline", "Post-Intervention"
WITH_DISTINCTIVENESS = (AREA, VERTICAL, HEDGE, WATER)
WITH_VALUE_MAP_SIGNIFICANCE = (AREA, VERTICAL)

BASELINE_SIGNIFICANCE = "Baseline Strategic Significance"
PROPOSED_SIGNIFICANCE = "Proposed Strategic Significance"
SPATIAL_RISK = "Spatial risk category"
IRREPLACEABLE = "Irreplaceable Habitat"
COMMENT = "Comment"
BASELINE_TYPE = {
    AREA: "Baseline Habitat Type",
    VERTICAL: "Baseline Habitat Type",
    HEDGE: "Baseline Hedge Type",
    WATER: "Baseline River Type",
    TREE: "Baseline Tree Type",
}
TIMING = {kind: ("Habitat created in advance/years",
                 "Delay in starting habitat creation/years")
          for kind in (AREA, VERTICAL, HEDGE, WATER)}
TIMING[TREE] = ("Habitat Created/Enhanced in advance/years",
                "Delay in starting habitat creation/enhancement in years")

PROPOSED_SIGNIFICANCE_DEFAULT = (
    'if("Retention Category" = \'Retained\', \'Low\', '
    'coalesce("Proposed Strategic Significance", \'Low\'))')
PROPOSED_SIGNIFICANCE_EDITABLE = (
    'coalesce("Retention Category", \'\') <> \'Retained\'')
IRREPLACEABLE_LIST_LAYER = "Habitat Irreplaceable"

# The six generated settings, in the order MAINTAINERS.md runs them.
CHECK_TOOLS = ("set_field_rules.py", "reset_stale_dropdowns.py",
               "set_paste_defaults.py", "order_dropdowns.py",
               "allow_blank.py", "require_shape.py")
NO_CHANGE = "no change needed"


def data_layers():
    names = [RED_LINE]
    for kind in KINDS:
        names += [f"{kind} {BASELINE}", f"{kind} {POST}"]
    return names


def read_project_xml(path):
    with zipfile.ZipFile(path) as archive:
        qgs = [name for name in archive.namelist() if name.endswith(".qgs")]
        return archive.read(qgs[0]).decode("utf-8")


class Layer:
    """The settings of one map layer, keyed by field name."""

    def __init__(self, element):
        self.element = element
        self.id = element.findtext("id")
        self.widgets = {
            field.get("name"): field.find("editWidget")
            for field in element.iterfind("fieldConfiguration/field")}
        self.defaults = {d.get("field"): d
                         for d in element.iterfind("defaults/default")}
        self.editable = {f.get("name"): f.get("editable")
                         for f in element.iterfind("editable/field")}
        self.constraints = {
            c.get("field"): c
            for c in element.iterfind("constraints/constraint")}
        self.constraint_expressions = {
            c.get("field"): c.get("exp")
            for c in element.iterfind("constraintExpressions/constraint")}
        self.columns = {
            c.get("name"): c
            for c in element.iterfind("attributetableconfig/columns/column")
            if c.get("name")}
        self.alias_indexes = [int(a.get("index"))
                              for a in element.iterfind("aliases/alias")]
        self.data_defined_editable = {}
        for field in element.iterfind("dataDefinedFieldProperties/field"):
            for option in field.iter("Option"):
                if option.get("name") == "dataDefinedEditable":
                    expression = [o.get("value") for o in option
                                  if o.get("name") == "expression"]
                    self.data_defined_editable[field.get("name")] = (
                        expression[0] if expression else None)

    def default(self, field):
        element = self.defaults[field]
        return element.get("expression"), element.get("applyOnUpdate")

    def widget_type(self, field):
        return self.widgets[field].get("type")


def value_map_values(widget):
    return [option.get("value")
            for option in widget.iterfind(
                "config/Option/Option[@name='map']/Option/Option")]


def widget_options(widget):
    return {option.get("name"): option.get("value")
            for option in widget.iter("Option") if option.get("name")}


class ProjectXmlTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.xml = read_project_xml(support.SERVICE_PROJECT)
        root = ET.fromstring(cls.xml)
        cls.layers = {element.findtext("layername"): Layer(element)
                      for element in root.iter("maplayer")}

    def layer(self, kind, stage):
        return self.layers[f"{kind} {stage}"]

    def each_stage(self, stages=(BASELINE, POST), kinds=KINDS):
        for kind in kinds:
            for stage in stages:
                yield kind, stage, self.layer(kind, stage)

    def test_project_has_every_data_layer(self):
        for name in data_layers():
            with self.subTest(layer=name):
                self.assertIn(name, self.layers)

    def test_parent_checksum_is_gone_from_the_project(self):
        self.assertNotIn("parent_checksum", self.xml)

    def test_every_value_map_offers_a_blank(self):
        for name in data_layers():
            layer = self.layers[name]
            for field, widget in layer.widgets.items():
                if widget.get("type") != VALUE_MAP:
                    continue
                with self.subTest(layer=name, field=field):
                    self.assertIn(NULL_VALUE, value_map_values(widget))

    def test_every_value_relation_allows_a_blank(self):
        for name in data_layers():
            layer = self.layers[name]
            for field, widget in layer.widgets.items():
                if widget.get("type") != VALUE_RELATION:
                    continue
                with self.subTest(layer=name, field=field):
                    self.assertEqual("true",
                                     widget_options(widget).get("AllowNull"))

    def test_every_habitat_layer_has_an_editable_comment(self):
        """A free-text field, shown in the table, with nothing filled in."""
        for kind, stage, layer in self.each_stage():
            with self.subTest(layer=f"{kind} {stage}"):
                self.assertIn(COMMENT, layer.widgets)
                self.assertIn(layer.widget_type(COMMENT), ("", "TextEdit"))
                self.assertNotEqual(LOCKED, layer.editable.get(COMMENT))
                self.assertEqual(("", "0"), layer.default(COMMENT))
                self.assertEqual("0", layer.columns[COMMENT].get("hidden"))
                self.assertEqual(sorted(layer.alias_indexes),
                                 layer.alias_indexes)

    def test_distinctiveness_is_locked_and_looked_up(self):
        for kind, stage, layer in self.each_stage(kinds=WITH_DISTINCTIVENESS):
            prefixes = ("Baseline",) if stage == BASELINE else (
                "Baseline", "Proposed")
            for prefix in prefixes:
                field = f"{prefix} Distinctiveness"
                with self.subTest(layer=f"{kind} {stage}", field=field):
                    self.assertEqual(LOCKED, layer.editable[field])
                    expression, on_update = layer.default(field)
                    self.assertIn("aggregate(layer:=", expression)
                    self.assertEqual(APPLY_ON_UPDATE, on_update)

    def test_trees_have_no_distinctiveness(self):
        for _kind, _stage, layer in self.each_stage(kinds=(TREE,)):
            self.assertNotIn("Baseline Distinctiveness", layer.widgets)

    def test_baseline_significance_is_locked_at_low(self):
        for kind, _stage, layer in self.each_stage(stages=(BASELINE,)):
            with self.subTest(layer=kind):
                self.assertEqual(LOCKED, layer.editable[BASELINE_SIGNIFICANCE])
                self.assertEqual(("'Low'", APPLY_ON_UPDATE),
                                 layer.default(BASELINE_SIGNIFICANCE))

    def test_post_baseline_significance_is_low_only_with_a_baseline_part(self):
        for kind, _stage, layer in self.each_stage(stages=(POST,)):
            column = BASELINE_TYPE[kind]
            expected = (f'if("{column}" IS NULL OR "{column}" IN '
                        "('To be created', 'N/A'), NULL, 'Low')")
            with self.subTest(layer=kind):
                self.assertEqual(LOCKED, layer.editable[BASELINE_SIGNIFICANCE])
                self.assertEqual((expected, APPLY_ON_UPDATE),
                                 layer.default(BASELINE_SIGNIFICANCE))

    def test_spatial_risk_is_locked_at_not_applicable(self):
        for kind, _stage, layer in self.each_stage(stages=(POST,)):
            with self.subTest(layer=kind):
                self.assertEqual(LOCKED, layer.editable[SPATIAL_RISK])
                self.assertEqual(("'N/A'", APPLY_ON_UPDATE),
                                 layer.default(SPATIAL_RISK))

    def test_proposed_significance_defaults_low_and_low_when_retained(self):
        for kind, _stage, layer in self.each_stage(stages=(POST,)):
            with self.subTest(layer=kind):
                self.assertEqual(EDITABLE,
                                 layer.editable[PROPOSED_SIGNIFICANCE])
                self.assertEqual(
                    (PROPOSED_SIGNIFICANCE_DEFAULT, APPLY_ON_UPDATE),
                    layer.default(PROPOSED_SIGNIFICANCE))

    def test_proposed_significance_is_greyed_out_when_retained(self):
        for kind, _stage, layer in self.each_stage(stages=(POST,)):
            with self.subTest(layer=kind):
                self.assertEqual(
                    PROPOSED_SIGNIFICANCE_EDITABLE,
                    layer.data_defined_editable.get(PROPOSED_SIGNIFICANCE))

    def test_proposed_significance_offers_only_low_and_high(self):
        for kind, _stage, layer in self.each_stage(
                stages=(POST,), kinds=WITH_VALUE_MAP_SIGNIFICANCE):
            with self.subTest(layer=kind):
                widget = layer.widgets[PROPOSED_SIGNIFICANCE]
                self.assertEqual(VALUE_MAP, widget.get("type"))
                self.assertEqual([NULL_VALUE, "Low", "High"],
                                 value_map_values(widget))
        for kind in (HEDGE, WATER, TREE):
            layer = self.layer(kind, POST)
            with self.subTest(layer=kind):
                options = widget_options(layer.widgets[PROPOSED_SIGNIFICANCE])
                self.assertEqual(VALUE_RELATION,
                                 layer.widget_type(PROPOSED_SIGNIFICANCE))
                self.assertEqual("", options["FilterExpression"])
                self.assertIn("Strategic Significance", options["LayerName"])

    def test_timing_fields_allow_only_one_of_advance_and_delay(self):
        for kind, _stage, layer in self.each_stage(stages=(POST,)):
            advance, delay = TIMING[kind]
            for field, other in ((advance, delay), (delay, advance)):
                with self.subTest(layer=kind, field=field):
                    expected = (f'if(coalesce("{other}", \'0\') <> \'0\', '
                                f'NULL, "{field}")')
                    self.assertEqual((expected, APPLY_ON_UPDATE),
                                     layer.default(field))
                    self.assertEqual(
                        f'coalesce("{other}", \'0\') = \'0\'',
                        layer.data_defined_editable.get(field))

    def test_data_layers_refuse_a_row_with_no_shape(self):
        for name in data_layers():
            field = "Site Name" if name == RED_LINE else "Habitat Ref"
            layer = self.layers[name]
            with self.subTest(layer=name):
                constraint = layer.constraints[field]
                flags = int(constraint.get("constraints"))
                self.assertTrue(flags & EXPRESSION_CONSTRAINT)
                self.assertEqual(HARD, constraint.get("exp_strength"))
                self.assertEqual(SHAPE_EXPRESSION,
                                 layer.constraint_expressions[field])

    def test_irreplaceable_habitat_fills_itself_from_its_list(self):
        list_id = self.layers[IRREPLACEABLE_LIST_LAYER].id
        for stage in (BASELINE, POST):
            layer = self.layer(AREA, stage)
            with self.subTest(stage=stage):
                expression, on_update = layer.default(IRREPLACEABLE)
                self.assertIn(list_id, expression)
                self.assertIn("array_length", expression)
                self.assertEqual(APPLY_ON_UPDATE, on_update)


class MaintenanceToolCheckTest(support.TempDirTestCase):
    """Each tool reports "no change needed" on a template that is in step."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = cls.tmp / "bng-service"
        shutil.copytree(support.SERVICE_TEMPLATE_DIR, cls.template)
        cls.project = cls.template / support.SERVICE_PROJECT.name

    def test_each_generated_setting_is_in_step(self):
        for tool in CHECK_TOOLS:
            with self.subTest(tool=tool):
                result = support.run_python(support.TOOLS_DIR / tool,
                                            "--check", self.project)
                self.assertEqual(0, result.returncode,
                                 support.describe(result))
                self.assertIn(NO_CHANGE, result.stdout)

    def test_check_writes_nothing(self):
        before = self.project.read_bytes()
        support.run_python(support.TOOLS_DIR / CHECK_TOOLS[0], "--check",
                           self.project)
        self.assertEqual(before, self.project.read_bytes())
        backups = list(self.template.glob("*.backup-*"))
        self.assertEqual([], backups)


if __name__ == "__main__":
    unittest.main()
