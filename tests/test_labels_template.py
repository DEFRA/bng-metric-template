"""The labelled copy of the template, `templates/bng-service-labels/`.

It is built from `templates/bng-service/` by
`development/tools/build_labels_template.py`, with a label on every habitat
layer. These tests check that the committed copy is the one the tool builds,
that it differs from the BNG Service template only in its labels, and what
each label shows.
"""

import io
import shutil
import sys
import unittest
import xml.etree.ElementTree as ET
import zipfile

from tests import support
from tests.test_project_xml import CHECK_TOOLS, NO_CHANGE

if str(support.TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(support.TOOLS_DIR))

import template_copy  # noqa: E402

LABELS_DIR = support.TEMPLATES_DIR / "bng-service-labels"
LABELS_PROJECT = LABELS_DIR / "BNG Service Habitat Mapping - Labels.qgz"
BUILD_TOOL = support.TOOLS_DIR / "build_labels_template.py"
KINDS = ("Area Habitats", "Vertical Area Habitats", "Hedgerows",
         "Watercourses", "Individual Trees")


def layers_by_name(path):
    with zipfile.ZipFile(path) as archive:
        qgs = next(n for n in archive.namelist() if n.endswith(".qgs"))
        root = ET.parse(io.BytesIO(archive.read(qgs))).getroot()
    return {layer.findtext("layername"): layer
            for layer in root.find("projectlayers")}


def without_labels(layer):
    copy = ET.fromstring(ET.tostring(layer))
    for child in copy.findall("labeling"):
        copy.remove(child)
    copy.attrib.pop("labelsEnabled", None)
    return ET.tostring(copy)


class LabelsTemplateTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.service = layers_by_name(support.SERVICE_PROJECT)
        cls.labels = layers_by_name(LABELS_PROJECT)

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
                                 (LABELS_DIR / relative).read_bytes())

    def test_each_layer_differs_only_in_its_labels(self):
        self.assertEqual(set(self.service), set(self.labels))
        for name, layer in self.service.items():
            with self.subTest(layer=name):
                self.assertEqual(without_labels(layer),
                                 without_labels(self.labels[name]))

    def test_every_habitat_layer_is_labelled(self):
        for kind in KINDS:
            for stage in ("Baseline", "Post-Intervention"):
                layer = self.labels[f"{kind} {stage}"]
                style = layer.find("labeling/settings/text-style")
                with self.subTest(layer=layer.findtext("layername")):
                    self.assertEqual("1", layer.get("labelsEnabled"))
                    self.assertEqual("1", style.get("isExpression"))
                    self.assertIn('"Habitat Ref"', style.get("fieldName"))
                    self.assertEqual(stage == "Post-Intervention",
                                     '"Retention Category"'
                                     in style.get("fieldName"))

    def test_the_red_line_is_not_labelled(self):
        self.assertNotEqual("1",
                            self.labels["Red Line Boundary"].get("labelsEnabled"))


class MaintenanceToolCheckTest(support.TempDirTestCase):

    def test_each_generated_setting_is_in_step(self):
        template = self.tmp / LABELS_DIR.name
        shutil.copytree(LABELS_DIR, template)
        project = template / LABELS_PROJECT.name
        for tool in CHECK_TOOLS:
            with self.subTest(tool=tool):
                result = support.run_python(support.TOOLS_DIR / tool,
                                            "--check", project)
                self.assertEqual(0, result.returncode, support.describe(result))
                self.assertIn(NO_CHANGE, result.stdout)


if __name__ == "__main__":
    unittest.main()
