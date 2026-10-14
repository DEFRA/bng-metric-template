"""development/tools/limit_vertical_habitats.py: the broad habitat lists.

The tool keeps or drops Value Map entries by name. A name stored in a way it
does not expect must stop it, not drop every entry, or none.
"""

import sys
import unittest

from tests import support

if str(support.TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(support.TOOLS_DIR))

import limit_vertical_habitats as tool  # noqa: E402

INDENT = "            "


def value_map(*values):
    """A Value Map widget with one entry for each value, as QGIS writes it."""
    entries = "".join(
        f'{INDENT}<Option type="Map">\n'
        f'{INDENT}  <Option name="{value}" type="QString" value="{value}"/>\n'
        f'{INDENT}</Option>\n' for value in values)
    return ('<Option name="map" type="List">\n' + entries + "</Option>")


AREA_BROAD = value_map(tool.NULL_VALUE, "Cropland",
                       "Intertidal hard structures", "Urban")


class LimitVerticalHabitatsTest(unittest.TestCase):

    def test_vertical_layer_keeps_only_the_vertical_broad_habitats(self):
        self.assertEqual(
            {tool.NULL_VALUE, "Intertidal hard structures", "Urban"},
            tool.map_values(tool.limit_value_map(AREA_BROAD)))

    def test_area_layer_drops_only_the_vertical_only_broad_habitats(self):
        self.assertEqual(
            {tool.NULL_VALUE, "Cropland", "Urban"},
            tool.map_values(tool.drop_vertical_only(AREA_BROAD)))

    def test_a_vertical_broad_habitat_stored_otherwise_stops_the_tool(self):
        renamed = value_map(tool.NULL_VALUE, "Intertidal Hard Structures",
                            "Urban")
        with self.assertRaisesRegex(SystemExit, "lost Intertidal hard"):
            tool.limit_value_map(renamed)

    def test_a_list_without_urban_stops_the_area_drop(self):
        with self.assertRaisesRegex(SystemExit, "lost Urban"):
            tool.drop_vertical_only(value_map(
                tool.NULL_VALUE, "Intertidal hard structures"))

    def test_a_broad_habitat_stored_otherwise_stops_the_area_drop(self):
        """Not matched, it would be left on the area layer without a word."""
        renamed = value_map(tool.NULL_VALUE, "Cropland",
                            "Intertidal Hard Structures", "Urban")
        known = tool.known_broad_habitats(support.SERVICE_PROJECT)
        with self.assertRaisesRegex(SystemExit, "unknown Intertidal Hard"):
            tool.drop_vertical_only(renamed, known)

    def test_the_template_names_only_known_broad_habitats(self):
        known = tool.known_broad_habitats(support.SERVICE_PROJECT)
        self.assertIn("Intertidal hard structures", known)
        self.assertIn("Urban", known)
        tool.drop_vertical_only(AREA_BROAD, known)

    def test_running_again_changes_nothing(self):
        once = tool.drop_vertical_only(AREA_BROAD)
        self.assertEqual(once, tool.drop_vertical_only(once))
        once = tool.limit_value_map(AREA_BROAD)
        self.assertEqual(once, tool.limit_value_map(once))
