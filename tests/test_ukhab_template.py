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
import sys
import unittest
import xml.etree.ElementTree as ET
import zipfile

from tests import support
from tests.test_project_xml import CHECK_TOOLS, NO_CHANGE

if str(support.TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(support.TOOLS_DIR))

import style_enhanced_trees  # noqa: E402
import template_copy  # noqa: E402

UKHAB_DIR = support.TEMPLATES_DIR / "bng-service-ukhab"
UKHAB_PROJECT = UKHAB_DIR / "BNG Service Habitat Mapping - UKHab symbology.qgz"
BUILD_TOOL = support.TOOLS_DIR / "build_ukhab_template.py"
LISTS = UKHAB_DIR / support.CSV_REFERENCES

# The parts of a layer that are its map style.
STYLE_TAGS = {"renderer-v2", "labeling", "layerOpacity"}
STYLE_ATTRIBUTES = {"labelsEnabled"}

# The yellow of a Retained tree and its outline, and the purple of Enhanced.
ENHANCED_COLOURS = {"251,243,83": "92,1,115", "178,172,58": "61,1,77"}
COLOUR_RE = re.compile(r"^(\d+,\d+,\d+),(\d+)")

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


def mapped_values(path, key, column, keys):
    """The values in `column` of the rows whose `key` is one of `keys`."""
    with open(LISTS / path, encoding="utf-8-sig", newline="") as handle:
        return {row[column] for row in csv.DictReader(handle)
                if row[key] in keys and row[column]}


def symbol_settings(symbol):
    """Each setting of a symbol's layers as (key, value), colours without
    their fractions part, so two symbols compare by shape, size and colour."""
    settings = []
    for element in symbol.iter():
        key = element.get("k") if element.tag == "prop" else element.get("name")
        value = element.get("v") if element.tag == "prop" else element.get("value")
        if element.tag not in ("prop", "Option") or value is None:
            continue
        match = COLOUR_RE.match(value)
        settings.append((key, match.group(0) if match else value))
    return settings


def as_enhanced(value):
    """A Retained colour as its Enhanced colour; any other value as it is."""
    match = COLOUR_RE.match(value)
    if match is None or match.group(1) not in ENHANCED_COLOURS:
        return value
    return f"{ENHANCED_COLOURS[match.group(1)]},{match.group(2)}"


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
                    or template_copy.SKIP_RE.search(source.name)):
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
        area_post_types = list_values(
            "Habitats/Habitat Options- post.csv", "UKHAB")
        area_conditions = list_values("Habitats/Habitat Condition.csv", "Label")
        hedge_types = list_values(
            "Hedgerows/Hedgerow Retention Options.csv", "Value") - {"To be created"}
        hedge_post_types = list_values(
            "Hedgerows/Hedgerow Habitat Options - post.csv", "Description")
        water_types = list_values(
            "Watercourses/Watercourse Retention Options.csv", "Value") - {"To be created"}
        expected = {
            "Area Habitats Baseline": area_types,
            "Area Habitats Post-Intervention": area_post_types,
            "Hedgerows Baseline": hedge_types,
            "Hedgerows Post-Intervention": hedge_post_types,
            "Watercourses Baseline": water_types,
            "Baseline Habitat Distinctiveness": mapped_values(
                "Habitats/Habitat Distinctiveness- pre.csv", "Habitat",
                "Baseline Distinctivness", area_types),
            "Proposed Habitats Distinctiveness": mapped_values(
                "Habitats/Habitat Distinctiveness- post.csv", "Habitat",
                "Proposed Distinctivness", area_post_types),
            "Baseline Hedgerow Distinctiveness": mapped_values(
                "Hedgerows/Hedgerow Distinctiveness- pre.csv", "Value",
                "Distinctiveness", hedge_types),
            "Proposed Hedgerow Distinctiveness": mapped_values(
                "Hedgerows/Hedgerow Distinctiveness - post.csv", "Value",
                "Distinctiveness", hedge_post_types),
            "Baseline Watercourse Distinctiveness": mapped_values(
                "Watercourses/Watercourse Distinctiveness- pre.csv", "Value",
                "Distinctiveness", water_types),
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

    def test_every_offered_value_has_a_rule(self):
        """The rule renderers: a value with no rule is not drawn."""
        water_post_types = list_values(
            "Watercourses/Watercourse Habitat Options - post.csv", "Description")
        sizes = list_values(
            "Individual trees/Individual tree Size - pre.csv", "Retention") - {"N/A"}
        settings = list_values(
            "Individual trees/Individual tree Rural or Urban - pre.csv",
            "Retention") - {"N/A"}
        expected = {
            "Watercourses Post-Intervention": {
                f"\"Proposed River Type\" = '{t}'" for t in water_post_types},
            "Proposed Watercourse Condition": {
                f"\"Proposed Condition\" = '{c}'" for c in mapped_values(
                    "Watercourses/Watercourse Condition.csv", "Habitat",
                    "Label", water_post_types)},
            "Proposed Watercourse Distinctiveness": {
                f"\"Proposed Distinctiveness\" = '{d}'" for d in mapped_values(
                    "Watercourses/Watercourse Distinctiveness- post.csv",
                    "Value", "Distinctiveness", water_post_types)},
            "Individual Trees Baseline": {
                f"\"Baseline Tree Size\" = '{size}' AND "
                f"\"Baseline Rural or Urban Tree\" = '{setting}'"
                for size in sizes for setting in settings},
        }
        for name, conditions in expected.items():
            filters = " ".join(rule_filters(self.ukhab[name]))
            for condition in sorted(conditions):
                with self.subTest(layer=name, condition=condition):
                    self.assertIn(condition, filters)

    def test_tree_conditions_have_a_rule_each(self):
        conditions = list_values(
            "Individual trees/Individual tree Condition - options.csv", "Label")
        for name, field in (
                ("Baseline Individual tree Condition", "Baseline Condition"),
                ("Proposed Individual tree Condition", "Proposed Condition")):
            filters = " ".join(rule_filters(self.ukhab[name]))
            for condition in conditions:
                with self.subTest(layer=name, condition=condition):
                    self.assertIn(f"\"{field}\" = '{condition}'", filters)

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


    def test_each_retained_tree_rule_has_an_enhanced_one(self):
        """For every size and setting: the same shape and size as Retained,
        with the Retained yellow made purple."""
        for name, layers in (("bng-service", self.service),
                             ("bng-service-ukhab", self.ukhab)):
            renderer = layers["Individual Trees Post-Intervention"].find(
                "renderer-v2")
            symbols = {s.get("name"): s
                       for s in renderer.findall("symbols/symbol")}
            rules = {" ".join(r.get("filter").split()): r
                     for r in renderer.iter("rule")
                     if r.get("filter") is not None}
            for condition, rule in rules.items():
                if "'Retained'" not in condition:
                    continue
                enhanced = condition.replace("'Retained'", "'Enhanced'")
                with self.subTest(template=name, rule=enhanced):
                    self.assertIn(enhanced, rules)
                    want = [(k, as_enhanced(v)) for k, v in symbol_settings(
                        symbols[rule.get("symbol")])]
                    got = symbol_settings(
                        symbols[rules[enhanced].get("symbol")])
                    self.assertEqual(want, got)


class EnhancedTreeRulesTest(unittest.TestCase):

    def test_a_missing_enhanced_rule_is_added_again(self):
        qgs, payload = style_enhanced_trees.qgz_actions.read_project(
            support.SERVICE_PROJECT)
        xml = payload[qgs].decode("utf-8")
        start, end = style_enhanced_trees.renderer_span(xml)
        renderer = xml[start:end]
        enhanced = [m for m in style_enhanced_trees.RULE_RE.finditer(renderer)
                    if "'Enhanced'" in m.group(0)]
        self.assertTrue(enhanced)
        gone = enhanced[0]
        partial = (xml[:start] + renderer[:gone.start()]
                   + renderer[gone.end():] + xml[end:])
        rebuilt, changed = style_enhanced_trees.add_enhanced_rules(partial)
        self.assertTrue(changed)
        self.assertIn(style_enhanced_trees.rule_filter(gone.group(0)),
                      [style_enhanced_trees.rule_filter(m.group(0))
                       for m in style_enhanced_trees.RULE_RE.finditer(rebuilt)])
        self.assertFalse(style_enhanced_trees.add_enhanced_rules(rebuilt)[1])


class EnhancedTreeToolTest(support.TempDirTestCase):
    """style_enhanced_trees.py on a project with one Enhanced rule gone."""

    def test_check_finds_it_and_a_run_puts_it_back(self):
        tool = support.TOOLS_DIR / "style_enhanced_trees.py"
        project = self.tmp / support.SERVICE_PROJECT.name
        qgs, payload = style_enhanced_trees.qgz_actions.read_project(
            support.SERVICE_PROJECT)
        xml = payload[qgs].decode("utf-8")
        start, end = style_enhanced_trees.renderer_span(xml)
        gone = next(m for m in style_enhanced_trees.RULE_RE.finditer(
            xml, start, end) if "'Enhanced'" in m.group(0))
        with zipfile.ZipFile(project, "w", zipfile.ZIP_DEFLATED) as out:
            for name, data in payload.items():
                out.writestr(name, data if name != qgs else
                             (xml[:gone.start()] + xml[gone.end():])
                             .encode("utf-8"))
        before = project.read_bytes()

        result = support.run_python(tool, "--check", project)
        self.assertEqual(1, result.returncode, support.describe(result))
        self.assertEqual(before, project.read_bytes())

        result = support.run_python(tool, project)
        self.assertEqual(0, result.returncode, support.describe(result))
        self.assertNotEqual(before, project.read_bytes())
        backups = list(self.tmp.glob(f"{project.name}.backup-*"))
        self.assertEqual(1, len(backups))
        self.assertEqual(before, backups[0].read_bytes())

        result = support.run_python(tool, "--check", project)
        self.assertEqual(0, result.returncode, support.describe(result))
        self.assertIn(NO_CHANGE, result.stdout)


class DifferencesTest(support.TempDirTestCase):
    """template_copy.differences, which --check reports."""

    def test_finds_a_changed_a_missing_and_an_extra_file(self):
        built, committed = self.tmp / "built", self.tmp / "committed"
        for folder in (built, committed):
            (folder / "Layers").mkdir(parents=True)
            (folder / "same.csv").write_text("a\n")
            (folder / "Layers" / "changed.gpkg").write_text(folder.name)
        (built / "missing.csv").write_text("b\n")
        (committed / "extra.csv").write_text("c\n")
        (committed / "Layers" / "changed.gpkg-wal").write_text("side file")
        self.assertEqual(
            ([str(support.Path("Layers") / "changed.gpkg")],
             ["missing.csv"], ["extra.csv"]),
            template_copy.differences(built, committed))


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
