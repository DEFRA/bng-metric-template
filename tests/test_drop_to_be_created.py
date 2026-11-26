"""development/tools/drop_to_be_created.py: the baseline type lists.

The tool removes one Value Map entry from one field of 4 layers. It must not
touch the same value in another field or on another layer, and must change
nothing when it runs again.
"""

import sys
import unittest

from tests import support

if str(support.TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(support.TOOLS_DIR))

import drop_to_be_created as tool  # noqa: E402

INDENT = "                  "


def field(name, *values):
    """A field with a Value Map widget, as QGIS writes it."""
    entries = "".join(
        f'{INDENT}<Option type="Map">\n'
        f'{INDENT}  <Option name="{value}" type="QString" value="{value}"/>\n'
        f'{INDENT}</Option>\n' for value in values)
    return (f'<field name="{name}" configurationFlags="NoFlag">\n'
            '  <editWidget type="ValueMap">\n'
            '    <config>\n'
            '      <Option type="Map">\n'
            '        <Option name="map" type="List">\n'
            f'{entries}'
            '        </Option>\n'
            '      </Option>\n'
            '    </config>\n'
            '  </editWidget>\n'
            '</field>\n')


def layer(name, *fields):
    return (f"<maplayer>\n<layername>{name}</layername>\n<fieldConfiguration>\n"
            + "".join(fields) + "</fieldConfiguration>\n</maplayer>\n")


def offered(xml, layer_name, field_name):
    for match in tool.MAPLAYER.finditer(xml):
        if f"<layername>{layer_name}</layername>" not in match.group(0):
            continue
        for widget in tool.FIELD.finditer(match.group(0)):
            if widget.group("name") == field_name:
                return [v for v in ("Native hedgerow", "Ditches", "Other",
                                    tool.TO_BE_CREATED)
                        if f'value="{v}"' in widget.group(0)]
    raise AssertionError(f"{layer_name} / {field_name} not found")


HEDGE = "Baseline Hedge Type"
RIVER = "Baseline River Type"
PROJECT = (
    layer("Hedgerows Baseline",
          field(HEDGE, "Native hedgerow", tool.TO_BE_CREATED),
          field("Other column", "Other", tool.TO_BE_CREATED))
    + layer("Hedgerows Post-Intervention",
            field(HEDGE, "Native hedgerow", tool.TO_BE_CREATED))
    + layer("Watercourses Baseline",
            field(RIVER, "Ditches", tool.TO_BE_CREATED))
    + layer("Watercourses Post-Intervention",
            field(RIVER, "Ditches", tool.TO_BE_CREATED))
    + layer("Hedgerow Retention Options",
            field(HEDGE, "Native hedgerow", tool.TO_BE_CREATED)))


class DropToBeCreatedTest(unittest.TestCase):

    def setUp(self):
        self.xml, self.changes = tool.drop(PROJECT)

    def test_the_four_baseline_type_lists_lose_the_value(self):
        self.assertEqual(4, len(self.changes))
        self.assertEqual(["Native hedgerow"],
                         offered(self.xml, "Hedgerows Baseline", HEDGE))
        self.assertEqual(["Native hedgerow"],
                         offered(self.xml, "Hedgerows Post-Intervention", HEDGE))
        self.assertEqual(["Ditches"],
                         offered(self.xml, "Watercourses Baseline", RIVER))
        self.assertEqual(["Ditches"],
                         offered(self.xml, "Watercourses Post-Intervention", RIVER))

    def test_another_field_and_another_layer_keep_it(self):
        self.assertEqual(["Other", tool.TO_BE_CREATED],
                         offered(self.xml, "Hedgerows Baseline", "Other column"))
        self.assertEqual(["Native hedgerow", tool.TO_BE_CREATED],
                         offered(self.xml, "Hedgerow Retention Options", HEDGE))

    def test_a_second_run_changes_nothing(self):
        again, changes = tool.drop(self.xml)
        self.assertEqual([], changes)
        self.assertEqual(self.xml, again)


class TemplateTest(unittest.TestCase):
    """The committed templates offer the value in none of the 4 lists."""

    def test_no_template_offers_it_for_a_baseline_type(self):
        for project in support.TEMPLATES_DIR.glob("bng-service*/*.qgz"):
            with self.subTest(project=project.parent.name):
                qgs, payload = tool.read_project(project)
                _, changes = tool.drop(payload[qgs].decode("utf-8"))
                self.assertEqual([], changes)


if __name__ == "__main__":
    unittest.main()
