"""The UKHab symbology copy of the template, `templates/bng-service-ukhab/`.

It is built from `templates/bng-service/` by
`development/tools/build_ukhab_template.py`, with the map styles of the
Natural England template. These tests check that the committed copy is the
one the tool builds, that it differs from the BNG Service template only in
its map styles, and that the styles fit the values the template stores.
"""

import csv
import io
import re
import shutil
import unittest
import xml.etree.ElementTree as ET
import zipfile

from tests import support
from tests.test_project_xml import CHECK_TOOLS, NO_CHANGE

UKHAB_DIR = support.TEMPLATES_DIR / "bng-service-ukhab"
UKHAB_PROJECT = UKHAB_DIR / "BNG Service Habitat Mapping - UKHab symbology.qgz"
BUILD_TOOL = support.TOOLS_DIR / "build_ukhab_template.py"
LISTS = UKHAB_DIR / support.CSV_REFERENCES

# The parts of a layer that are its map style.
STYLE_TAGS = {"renderer-v2", "labeling", "layerOpacity"}
STYLE_ATTRIBUTES = {"labelsEnabled"}

# Each view-only layer, and the data layer whose table it reads.
VIEW_LAYERS = {
    "Baseline Habitat Condition": "Area Habitats Baseline",
    "Baseline Habitat Distinctiveness": "Area Habitats Baseline",
    "Habitats Retention": "Area Habitats Post-Intervention",
    "Proposed Habitats Condition": "Area Habitats Post-Intervention",
    "Proposed Habitats Distinctiveness": "Area Habitats Post-Intervention",
    "Baseline Hedgerow Condition": "Hedgerows Baseline",
    "Baseline Hedgerow Distinctiveness": "Hedgerows Baseline",
    "Hedgerow Retention": "Hedgerows Post-Intervention",
    "Proposed Hedgerow Condition": "Hedgerows Post-Intervention",
    "Proposed Hedgerow Distinctiveness": "Hedgerows Post-Intervention",
    "Baseline Watercourse Condition": "Watercourses Baseline",
    "Baseline Watercourse Distinctiveness": "Watercourses Baseline",
    "Watercourse Retention": "Watercourses Post-Intervention",
    "Proposed Watercourse Condition": "Watercourses Post-Intervention",
    "Proposed Watercourse Distinctiveness": "Watercourses Post-Intervention",
    "Individual tree Retention (VIEW ONLY)":
        "Individual Trees Post-Intervention",
    "Baseline Individual tree Condition": "Individual Trees Baseline",
    "Proposed Individual tree Condition": "Individual Trees Post-Intervention",
}


def project_root(path):
    with zipfile.ZipFile(path) as archive:
        qgs = next(n for n in archive.namelist() if n.endswith(".qgs"))
        return ET.parse(io.BytesIO(archive.read(qgs))).getroot()


def layers_by_name(root):
    return {layer.findtext("layername"): layer
            for layer in root.find("projectlayers")}


def without_style(layer):
    """A layer's XML with its map style taken out, for comparison."""
    copy = ET.fromstring(ET.tostring(layer))
    for tag in STYLE_TAGS:
        for child in copy.findall(tag):
            copy.remove(child)
    for name in STYLE_ATTRIBUTES:
        copy.attrib.pop(name, None)
    return ET.tostring(copy)


def list_values(path, column):
    with open(LISTS / path, encoding="utf-8-sig", newline="") as handle:
        return {row[column] for row in csv.DictReader(handle) if row[column]}


def category_values(layer):
    return {c.get("value") for c in layer.find("renderer-v2").iter("category")}


def rule_filters(layer):
    """Each rule's filter, with its runs of spaces made one space."""
    return [" ".join(r.get("filter").split())
            for r in layer.find("renderer-v2").iter("rule")
            if r.get("filter") is not None]


class CommittedCopyTest(unittest.TestCase):

    def test_the_committed_copy_is_the_one_the_tool_builds(self):
        result = support.run_python(BUILD_TOOL, "--check")
        self.assertEqual(0, result.returncode, support.describe(result))
        self.assertIn(NO_CHANGE, result.stdout)

    def test_the_data_and_lists_are_the_bng_service_templates(self):
        for source in support.SERVICE_TEMPLATE_DIR.rglob("*"):
            relative = source.relative_to(support.SERVICE_TEMPLATE_DIR)
            if (not source.is_file() or source.suffix == ".qgz"
                    or ".backup-" in source.name or source.name == ".DS_Store"):
                continue
            with self.subTest(file=str(relative)):
                self.assertEqual(source.read_bytes(),
                                 (UKHAB_DIR / relative).read_bytes())


class ProjectTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.service = layers_by_name(project_root(support.SERVICE_PROJECT))
        cls.ukhab = layers_by_name(project_root(UKHAB_PROJECT))

    def test_every_service_layer_differs_only_in_its_map_style(self):
        for name, layer in self.service.items():
            with self.subTest(layer=name):
                self.assertIn(name, self.ukhab)
                self.assertEqual(without_style(layer),
                                 without_style(self.ukhab[name]))

    def test_no_two_layers_share_a_name(self):
        root = project_root(UKHAB_PROJECT)
        names = [layer.findtext("layername")
                 for layer in root.find("projectlayers")]
        self.assertEqual(len(names), len(set(names)))

    def test_the_only_new_layers_are_the_view_only_ones(self):
        self.assertEqual(set(VIEW_LAYERS),
                         set(self.ukhab) - set(self.service))

    def test_each_view_only_layer_is_read_only_and_reads_its_table(self):
        for name, table in VIEW_LAYERS.items():
            layer = self.ukhab[name]
            with self.subTest(layer=name):
                self.assertEqual("1", layer.get("readOnly"))
                self.assertEqual(self.service[table].findtext("datasource"),
                                 layer.findtext("datasource"))
                self.assertIsNone(layer.find("fieldConfiguration"))
                self.assertIsNone(layer.find("attributeactions"))

    def test_vertical_area_habitats_keep_their_own_style(self):
        for stage in ("Baseline", "Post-Intervention"):
            name = f"Vertical Area Habitats {stage}"
            with self.subTest(layer=name):
                self.assertEqual(
                    ET.tostring(self.service[name].find("renderer-v2")),
                    ET.tostring(self.ukhab[name].find("renderer-v2")))

    def test_no_style_keeps_a_list_number_or_lost(self):
        for name, layer in self.ukhab.items():
            renderer = layer.find("renderer-v2")
            if renderer is None:
                continue
            values = category_values(layer)
            with self.subTest(layer=name):
                self.assertNotIn("Lost", values)
                self.assertFalse([v for v in values if re.match(r"\d+\. ", v)])
                for expression in rule_filters(layer):
                    self.assertNotRegex(expression, r"'\d+\. ")
                    self.assertNotRegex(expression, r"=\s*'Lost'")

    def test_every_offered_value_has_a_symbol(self):
        area_types = list_values("Habitats/Habitat Options- pre.csv", "UKHAB")
        area_conditions = list_values("Habitats/Habitat Condition.csv", "Label")
        expected = {
            "Area Habitats Baseline": area_types,
            "Area Habitats Post-Intervention": list_values(
                "Habitats/Habitat Options- post.csv", "UKHAB"),
            "Hedgerows Baseline": list_values(
                "Hedgerows/Hedgerow Retention Options.csv", "Value")
            - {"To be created"},
            "Watercourses Baseline": list_values(
                "Watercourses/Watercourse Retention Options.csv", "Value")
            - {"To be created"},
            "Baseline Habitat Condition": area_conditions,
            "Proposed Habitats Condition": area_conditions,
            "Habitats Retention": list_values(
                "Habitats/Habitat retention descriptor - post.csv",
                "Retention"),
            "Baseline Hedgerow Condition": list_values(
                "Hedgerows/Hedgerow Condition.csv", "Condition"),
            "Proposed Hedgerow Condition": list_values(
                "Hedgerows/Hedgerow Condition.csv", "Condition"),
            "Hedgerow Retention": list_values(
                "Hedgerows/Hedgerow Retention Options.csv", "Options"),
            "Baseline Watercourse Condition": list_values(
                "Watercourses/Watercourse Condition.csv", "Label"),
            "Watercourse Retention": list_values(
                "Watercourses/Watercourse Retention Options.csv", "Options"),
        }
        for name, offered in expected.items():
            with self.subTest(layer=name):
                self.assertEqual(set(), offered - category_values(self.ukhab[name]))

    def test_tree_conditions_have_a_rule_each(self):
        conditions = list_values(
            "Individual trees/Individual tree Condition - options.csv", "Label")
        for name in ("Baseline Individual tree Condition",
                     "Proposed Individual tree Condition"):
            filters = " ".join(rule_filters(self.ukhab[name]))
            for condition in conditions:
                with self.subTest(layer=name, condition=condition):
                    self.assertIn(f"Condition\" = '{condition}'", filters)

    def test_no_layer_is_labelled(self):
        for name, layer in self.ukhab.items():
            with self.subTest(layer=name):
                self.assertNotEqual("1", layer.get("labelsEnabled"))

    def test_every_renderer_has_its_symbols(self):
        """A single symbol renderer keeps its one symbol, and every symbol a
        category or rule names is there. Without its symbol, QGIS draws a
        layer in a random fill."""
        for name, layer in self.ukhab.items():
            renderer = layer.find("renderer-v2")
            if renderer is None:
                continue
            names = {s.get("name") for s in renderer.findall("symbols/symbol")}
            with self.subTest(layer=name):
                if renderer.get("type") == "singleSymbol":
                    self.assertEqual(1, len(names))
                named = {c.get("symbol") for c in renderer.iter("category")}
                named |= {r.get("symbol") for r in renderer.iter("rule")
                          if r.get("symbol") is not None}
                self.assertLessEqual(named, names)

    def test_the_red_line_is_an_outline(self):
        symbol = self.ukhab["Red Line Boundary"].find(
            "renderer-v2/symbols/symbol")
        self.assertEqual(["SimpleLine"],
                         [layer.get("class") for layer in symbol.iter("layer")])

    def test_every_retention_category_of_a_tree_is_drawn(self):
        """Natural England has no Enhanced rules: style_enhanced_trees.py
        adds them, in both templates."""
        retentions = list_values(
            "Individual trees/Individual tree Retention.csv", "Retention")
        for name, layers in (("bng-service", self.service),
                             ("bng-service-ukhab", self.ukhab)):
            filters = " ".join(rule_filters(
                layers["Individual Trees Post-Intervention"]))
            for retention in retentions:
                with self.subTest(template=name, retention=retention):
                    self.assertIn(f"\"Retention Category\" = '{retention}'",
                                  filters)


class MaintenanceToolCheckTest(support.TempDirTestCase):
    """The maintenance tools find the copy in step, as they find the source."""

    def test_each_generated_setting_is_in_step(self):
        template = self.tmp / UKHAB_DIR.name
        shutil.copytree(UKHAB_DIR, template)
        project = template / UKHAB_PROJECT.name
        for tool in CHECK_TOOLS:
            with self.subTest(tool=tool):
                result = support.run_python(support.TOOLS_DIR / tool,
                                            "--check", project)
                self.assertEqual(0, result.returncode, support.describe(result))
                self.assertIn(NO_CHANGE, result.stdout)


if __name__ == "__main__":
    unittest.main()
