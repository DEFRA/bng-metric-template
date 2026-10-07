"""The template's field rules, as QGIS itself applies them.

These run with PyQGIS, inside the official qgis/qgis Docker image (see
tests_qgis/README.md). Each test works on a fresh copy of
templates/bng-service, so the template itself is never written.
"""
import os
import shutil
import sys
import tempfile
import unittest

from qgis.core import (QgsApplication, QgsFeature, QgsGeometry, QgsProject,
                       QgsVectorLayerUtils)
from qgis.gui import (QgsAttributeEditorContext, QgsAttributeForm, QgsGui,
                      QgsEditorWidgetWrapper)
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtWidgets import QComboBox
import qgis.utils

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(REPO, "templates", "bng-service")
PROJECT_NAME = "BNG Service Habitat Mapping.qgz"
TOOLS_DIR = os.path.join(REPO, "development", "tools")

sys.path.insert(0, TOOLS_DIR)
from run_actions_headless import FakeIface, FakeProgress, load_action  # noqa: E402

AREA_BASE = "Area Habitats Baseline"
AREA_PI = "Area Habitats Post-Intervention"
HEDGE_BASE = "Hedgerows Baseline"
HEDGE_PI = "Hedgerows Post-Intervention"
TREE_PI = "Individual Trees Post-Intervention"

REF = "Habitat Ref"
RETENTION = "Retention Category"
PROPOSED_SIG = "Proposed Strategic Significance"
BASELINE_SIG = "Baseline Strategic Significance"
SPATIAL_RISK = "Spatial risk category"
ADVANCE = "Habitat created in advance/years"
DELAY = "Delay in starting habitat creation/years"
TREE_ADVANCE = "Habitat Created/Enhanced in advance/years"
TREE_DELAY = "Delay in starting habitat creation/enhancement in years"

SQUARE = "POLYGON((0 0,100 0,100 100,0 100,0 0))"
OTHER_SQUARE = "POLYGON((200 0,300 0,300 100,200 100,200 0))"
HEDGE_LINE = "LINESTRING(0 0,50 0,100 10)"
TREE_POINT = "POINT(10 10)"

APP = QgsApplication([], True)
APP.initQgis()
QgsGui.editorWidgetRegistry().initEditors()


def is_null(value):
    return value is None or (hasattr(value, "isNull") and value.isNull())


class TemplateCase(unittest.TestCase):
    """Opens a fresh copy of the template for each test."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bng-template-")
        self.dir = os.path.join(self.tmp, "bng-service")
        shutil.copytree(TEMPLATE_DIR, self.dir)
        self.project = QgsProject.instance()
        self.assertTrue(self.project.read(os.path.join(self.dir, PROJECT_NAME)),
                        "the template project should open")

    def tearDown(self):
        for layer in self.project.mapLayers().values():
            if hasattr(layer, "isEditable") and layer.isEditable():
                layer.rollBack()
        self.project.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def layer(self, name):
        found = self.project.mapLayersByName(name)
        self.assertEqual(len(found), 1, f"one layer named {name!r}")
        return found[0]

    def add(self, layer, wkt, **values):
        """Add a feature as a drawn one would be, with the layer defaults."""
        if not layer.isEditable():
            layer.startEditing()
        index = layer.fields().indexOf
        attributes = {index(name): value for name, value in values.items()}
        geometry = QgsGeometry.fromWkt(wkt) if wkt else QgsGeometry()
        feature = QgsVectorLayerUtils.createFeature(
            layer, geometry, attributes, layer.createExpressionContext())
        self.assertTrue(layer.addFeature(feature))
        return feature.id()

    def set(self, layer, fid, name, value):
        """Change one value, as a cell of the attribute table does."""
        layer.changeAttributeValue(fid, layer.fields().indexOf(name), value)
        return layer.getFeature(fid)

    def get(self, layer, fid):
        return layer.getFeature(fid)


class TheProject(TemplateCase):

    def test_every_layer_is_valid(self):
        invalid = [layer.name() for layer in self.project.mapLayers().values()
                   if not layer.isValid()]
        self.assertEqual(invalid, [])

    def test_the_data_layers_are_empty(self):
        for name in (AREA_BASE, AREA_PI, HEDGE_BASE, HEDGE_PI, TREE_PI):
            self.assertEqual(self.layer(name).featureCount(), 0, name)


class FilledColumns(TemplateCase):

    def test_a_new_post_intervention_row_is_low_and_n_a(self):
        layer = self.layer(AREA_PI)
        row = self.get(layer, self.add(layer, SQUARE, **{REF: "PI-1",
                                                         RETENTION: "Created"}))
        self.assertEqual(row[PROPOSED_SIG], "Low")
        self.assertEqual(row[SPATIAL_RISK], "N/A")

    def test_baseline_significance_is_always_low(self):
        layer = self.layer(AREA_BASE)
        row = self.get(layer, self.add(layer, SQUARE, **{REF: "PR-1"}))
        self.assertEqual(row[BASELINE_SIG], "Low")

    def test_distinctiveness_follows_the_habitat_type(self):
        layer = self.layer(AREA_BASE)
        fid = self.add(layer, SQUARE, **{
            REF: "PR-1", "Baseline Broad Habitat Type": "Grassland",
            "Baseline Habitat Type": "Modified grassland"})
        self.assertEqual(self.get(layer, fid)["Baseline Distinctiveness"], "Low")
        fid = self.add(layer, OTHER_SQUARE, **{
            REF: "PR-2", "Baseline Broad Habitat Type": "Wetland",
            "Baseline Habitat Type": "Blanket bog"})
        self.assertEqual(self.get(layer, fid)["Baseline Distinctiveness"],
                         "V.High")

    def test_a_single_allowed_condition_fills_itself_in(self):
        layer = self.layer(AREA_BASE)
        fid = self.add(layer, SQUARE, **{
            REF: "PR-1", "Baseline Broad Habitat Type": "Urban",
            "Baseline Habitat Type": "Developed land; sealed surface"})
        self.assertEqual(self.get(layer, fid)["Baseline Condition"],
                         "N/A - Other")

    def test_a_choice_of_conditions_is_left_to_the_surveyor(self):
        layer = self.layer(AREA_BASE)
        fid = self.add(layer, SQUARE, **{
            REF: "PR-1", "Baseline Broad Habitat Type": "Grassland",
            "Baseline Habitat Type": "Modified grassland"})
        self.assertTrue(is_null(self.get(layer, fid)["Baseline Condition"]))

    def test_irreplaceable_habitat_fills_itself_in(self):
        layer = self.layer(AREA_BASE)
        bog = self.add(layer, SQUARE, **{
            REF: "PR-1", "Baseline Broad Habitat Type": "Wetland",
            "Baseline Habitat Type": "Blanket bog"})
        grass = self.add(layer, OTHER_SQUARE, **{
            REF: "PR-2", "Baseline Broad Habitat Type": "Grassland",
            "Baseline Habitat Type": "Modified grassland"})
        self.assertEqual(self.get(layer, bog)["Irreplaceable Habitat"], "Yes")
        self.assertEqual(self.get(layer, grass)["Irreplaceable Habitat"], "No")


class RetainedSignificance(TemplateCase):

    def test_a_retained_row_cannot_be_high(self):
        layer = self.layer(AREA_PI)
        fid = self.add(layer, SQUARE, **{REF: "PI-1", RETENTION: "Retained"})
        self.assertEqual(self.set(layer, fid, PROPOSED_SIG, "High")[PROPOSED_SIG],
                         "Low")

    def test_a_retained_row_cannot_be_blank(self):
        layer = self.layer(AREA_PI)
        fid = self.add(layer, SQUARE, **{REF: "PI-1", RETENTION: "Retained"})
        self.assertEqual(self.set(layer, fid, PROPOSED_SIG, None)[PROPOSED_SIG],
                         "Low")

    def test_a_created_row_can_be_high(self):
        layer = self.layer(AREA_PI)
        fid = self.add(layer, SQUARE, **{REF: "PI-1", RETENTION: "Created"})
        self.assertEqual(self.set(layer, fid, PROPOSED_SIG, "High")[PROPOSED_SIG],
                         "High")


class AdvanceOrDelay(TemplateCase):

    def assert_not_both(self, layer, fid, advance, delay):
        row = self.get(layer, fid)
        above = [name for name in (advance, delay)
                 if not is_null(row[name]) and row[name] != "0"]
        self.assertLessEqual(len(above), 1,
                             f"advance={row[advance]} delay={row[delay]}")

    def test_a_table_cell_cannot_set_both(self):
        for name, wkt, advance, delay in (
                (AREA_PI, SQUARE, ADVANCE, DELAY),
                (HEDGE_PI, HEDGE_LINE, ADVANCE, DELAY),
                (TREE_PI, TREE_POINT, TREE_ADVANCE, TREE_DELAY)):
            with self.subTest(layer=name):
                layer = self.layer(name)
                fid = self.add(layer, wkt, **{REF: "PI-1"})
                self.set(layer, fid, delay, "5")
                self.set(layer, fid, advance, "4")
                self.assert_not_both(layer, fid, advance, delay)

    def test_a_value_beside_a_zero_is_kept(self):
        # Once advance is above 0, the delay is stored blank: a 0 there
        # becomes NULL, which the Metric reads the same way.
        layer = self.layer(AREA_PI)
        fid = self.add(layer, SQUARE, **{REF: "PI-1"})
        self.set(layer, fid, DELAY, "0")
        row = self.set(layer, fid, ADVANCE, "3")
        self.assertEqual(row[ADVANCE], "3")
        self.assertTrue(is_null(row[DELAY]) or row[DELAY] == "0")


class TheForm(TemplateCase):
    """The attribute form greys out what the surveyor cannot change."""

    def open_form(self, layer, fid):
        form = QgsAttributeForm(layer, layer.getFeature(fid),
                                QgsAttributeEditorContext())
        form.setMode(QgsAttributeEditorContext.SingleEditMode)
        self.addCleanup(form.deleteLater)
        return {w.field().name(): w
                for w in form.findChildren(QgsEditorWidgetWrapper)}

    def pick(self, widgets, name, value):
        widget = widgets[name].widget()
        combo = widget if isinstance(widget, QComboBox) else \
            widget.findChild(QComboBox)
        combo.setCurrentIndex(combo.findData(value))
        APP.processEvents()

    def enabled(self, widgets, name):
        """Whether the surveyor can change the value. QGIS locks a text box
        by making it read-only, and a drop-down by greying it out."""
        widget = widgets[name].widget()
        read_only = getattr(widget, "isReadOnly", lambda: False)()
        return widget.isEnabled() and not read_only

    def test_picking_one_timing_value_greys_out_the_other(self):
        layer = self.layer(AREA_PI)
        widgets = self.open_form(layer, self.add(layer, SQUARE, **{
            REF: "PI-1", RETENTION: "Created"}))
        self.assertTrue(self.enabled(widgets, DELAY))
        self.pick(widgets, ADVANCE, "3")
        self.assertFalse(self.enabled(widgets, DELAY))
        self.pick(widgets, ADVANCE, "0")
        self.assertTrue(self.enabled(widgets, DELAY))

    def test_retained_greys_out_proposed_significance(self):
        layer = self.layer(AREA_PI)
        widgets = self.open_form(layer, self.add(layer, SQUARE, **{
            REF: "PI-1", RETENTION: "Created"}))
        self.assertTrue(self.enabled(widgets, PROPOSED_SIG))
        self.pick(widgets, RETENTION, "Retained")
        self.assertFalse(self.enabled(widgets, PROPOSED_SIG))

    def test_distinctiveness_is_locked(self):
        layer = self.layer(AREA_BASE)
        widgets = self.open_form(layer, self.add(layer, SQUARE, **{REF: "PR-1"}))
        self.assertFalse(self.enabled(widgets, "Baseline Distinctiveness"))
        self.assertFalse(self.enabled(widgets, BASELINE_SIG))


class EveryRowNeedsAShape(TemplateCase):

    def test_a_row_without_a_shape_breaks_a_hard_constraint(self):
        layer = self.layer(AREA_BASE)
        feature = QgsFeature(layer.fields())
        feature[REF] = "PR-1"
        valid, errors = QgsVectorLayerUtils.validateAttribute(
            layer, feature, layer.fields().indexOf(REF))
        self.assertFalse(valid, "a shapeless row should be refused")
        self.assertTrue(any("shape" in error for error in errors), errors)

    def test_a_row_with_a_shape_passes(self):
        layer = self.layer(AREA_BASE)
        feature = QgsFeature(layer.fields())
        feature[REF] = "PR-1"
        feature.setGeometry(QgsGeometry.fromWkt(SQUARE))
        valid, _ = QgsVectorLayerUtils.validateAttribute(
            layer, feature, layer.fields().indexOf(REF))
        self.assertTrue(valid)


class PasteLineage(TemplateCase):
    """A pasted copy of a baseline feature is linked to it."""

    def test_a_pasted_baseline_shape_gets_its_parent(self):
        base = self.layer(AREA_BASE)
        self.add(base, SQUARE, **{
            REF: "PR-1", "Baseline Broad Habitat Type": "Grassland",
            "Baseline Habitat Type": "Modified grassland"})
        self.assertTrue(base.commitChanges())
        parent = next(base.getFeatures())

        pi = self.layer(AREA_PI)
        row = self.get(pi, self.add(pi, SQUARE))
        self.assertEqual(row["Parent Ref"], "PR-1")
        # The baseline values themselves arrive with the pasted columns; the
        # template's rules supply only the link.
        self.assertEqual(row["parent_uuid"], parent["feature_uuid"])

    def test_a_new_shape_gets_no_parent(self):
        base = self.layer(AREA_BASE)
        self.add(base, SQUARE, **{REF: "PR-1"})
        self.assertTrue(base.commitChanges())
        pi = self.layer(AREA_PI)
        row = self.get(pi, self.add(pi, OTHER_SQUARE, **{REF: "PI-POND"}))
        self.assertTrue(is_null(row["Parent Ref"]))
        self.assertTrue(is_null(row["parent_uuid"]))


class CopyBaselineButton(TemplateCase):
    """The Copy baseline to post-intervention button, run headless."""

    def run_button(self, prefix, layer_name):
        project_path = os.path.join(self.dir, PROJECT_NAME)
        body = load_action(project_path, prefix, layer_name)

        class NoQuestions:
            Yes, No = 1, 0

            @staticmethod
            def question(*_args, **_kwargs):
                return NoQuestions.No

        originals = (QtWidgets.QProgressDialog, QtWidgets.QMessageBox,
                     getattr(qgis.utils, "iface", None))
        QtWidgets.QProgressDialog = FakeProgress
        QtWidgets.QMessageBox = NoQuestions
        qgis.utils.iface = FakeIface()
        try:
            exec(compile(body, "<action>", "exec"), {"__name__": "__action__"})
        finally:
            (QtWidgets.QProgressDialog, QtWidgets.QMessageBox,
             qgis.utils.iface) = originals

    def test_copy_links_every_baseline_hedge(self):
        base = self.layer(HEDGE_BASE)
        self.add(base, HEDGE_LINE, **{REF: "HR-1",
                                      "Baseline Hedge Type": "Line of trees"})
        self.add(base, "LINESTRING(0 50,100 50)", **{
            REF: "HR-2", "Baseline Hedge Type": "Line of trees"})
        self.assertTrue(base.commitChanges())

        self.run_button("Copy baseline", HEDGE_PI)

        pi = self.layer(HEDGE_PI)
        rows = sorted(pi.getFeatures(), key=lambda f: f[REF])
        self.assertEqual([r["Parent Ref"] for r in rows], ["HR-1", "HR-2"])
        self.assertEqual({r[RETENTION] for r in rows}, {"Retained"})
        uuids = {f["feature_uuid"] for f in base.getFeatures()}
        self.assertEqual({r["parent_uuid"] for r in rows}, uuids)


if __name__ == "__main__":
    unittest.main()
