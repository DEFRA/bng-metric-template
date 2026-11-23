"""The GeoPackage specification, spec/gpkg-spec.json and spec/gpkg-spec.md.

gpkg_spec.py generates it from the template. These tests check that it
describes all of the template, that it comes out the same each time, and
that the committed copy is what the template gives now.
"""

import json
import shutil
import sys

from tests import support

if str(support.TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(support.TOOLS_DIR))

# support puts the converter modules on sys.path.
import gpkg_common  # noqa: E402
import gpkg_spec  # noqa: E402

LINEAGE = ("feature_uuid", "Parent Ref", "parent_uuid", "parent_geom")
POST = "Post-Intervention"
BASELINE = "Baseline"


def table_of(spec, name):
    return next(table for table in spec["tables"] if table["name"] == name)


def column_of(spec, table, name):
    return next(column for column in table_of(spec, table)["columns"]
                if column["name"] == name)


class SpecContentTest(support.TempDirTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.spec = gpkg_spec.build_spec()

    def test_every_table_and_column_of_the_template_is_described(self):
        tables = support.feature_tables(support.SERVICE_GPKG)
        described = [table["name"] for table in self.spec["tables"]]
        self.assertEqual(sorted(tables), sorted(described))
        for table in tables:
            with self.subTest(table=table):
                self.assertEqual(
                    support.columns(support.SERVICE_GPKG, table),
                    [column["name"]
                     for column in table_of(self.spec, table)["columns"]])

    def test_every_table_has_its_geometry_type_and_coordinate_system(self):
        for table in self.spec["tables"]:
            with self.subTest(table=table["name"]):
                self.assertIn(table["geometryType"],
                              ("POLYGON", "LINESTRING", "POINT"))
                self.assertEqual(27700, table["srsId"])
        self.assertEqual(["OSGB36 / British National Grid"],
                         [system["name"]
                          for system in self.spec["coordinateSystems"]])

    def test_text_widths_are_the_template_limits(self):
        for table in self.spec["tables"]:
            for column in table["columns"]:
                limit = gpkg_common.TEXT_LIMITS.get(column["name"])
                if column["type"].upper().startswith("TEXT"):
                    with self.subTest(table=table["name"],
                                      column=column["name"]):
                        self.assertEqual(limit, column["width"])

    def test_the_version_record_names_the_format_and_version(self):
        record = self.spec["versionRecord"]
        self.assertEqual(gpkg_common.TEMPLATE_METADATA_URI,
                         record["mdStandardUri"])
        self.assertEqual({"format": gpkg_common.FORMAT_NAME,
                          "version": gpkg_common.TEMPLATE_VERSION},
                         record["metadata"])
        self.assertEqual("geopackage",
                         record["reference"]["referenceScope"])
        self.assertEqual(gpkg_common.TEMPLATE_VERSION,
                         self.spec["templateVersion"])

    def test_lineage_columns_are_marked_on_their_stage(self):
        self.assertEqual(set(LINEAGE), {entry["column"] for entry in
                                        self.spec["lineageColumns"]})
        for table in self.spec["tables"]:
            for column in table["columns"]:
                with self.subTest(table=table["name"], column=column["name"]):
                    self.assertEqual(column["name"] in LINEAGE,
                                     column["lineage"])
        self.assertTrue(column_of(self.spec, "Hedgerows Baseline",
                                  "feature_uuid")["lineage"])
        self.assertTrue(column_of(self.spec, f"Hedgerows {POST}",
                                  "parent_geom")["lineage"])

    def test_a_list_drop_down_names_a_list_that_is_described(self):
        lists = {entry["list"]: entry for entry in self.spec["lists"]}
        for table in self.spec["tables"]:
            for column in table["columns"]:
                drop_down = column["dropDown"]
                if drop_down and drop_down["kind"] == "list":
                    with self.subTest(table=table["name"],
                                      column=column["name"]):
                        described = lists[drop_down["list"]]
                        self.assertIn(drop_down["storedColumn"],
                                      described["columns"])
                        self.assertTrue(
                            (support.SERVICE_TEMPLATE_DIR
                             / drop_down["list"]).is_file())

    def test_a_list_that_depends_on_another_column_names_it(self):
        drop_down = column_of(self.spec, f"Area Habitats {BASELINE}",
                              "Baseline Habitat Type")["dropDown"]
        self.assertEqual(["Baseline Broad Habitat Type"],
                         drop_down["dependsOn"])
        self.assertIn("current_value", drop_down["filter"])

    def test_a_fixed_list_holds_its_values_but_not_the_blank_marker(self):
        drop_down = column_of(self.spec, f"Hedgerows {POST}",
                              "Habitat created in advance/years")["dropDown"]
        self.assertEqual("fixed list", drop_down["kind"])
        stored = [value["stored"] for value in drop_down["values"]]
        self.assertEqual("0", stored[0])
        self.assertEqual("30+", stored[-1])
        self.assertNotIn(gpkg_spec.VALUE_MAP_NULL, stored)
        self.assertTrue(drop_down["blankOffered"])

    def test_defaults_and_locked_columns_come_from_the_project(self):
        spatial_risk = column_of(self.spec, f"Hedgerows {POST}",
                                 "Spatial risk category")
        self.assertEqual("N/A", spatial_risk["default"]["value"])
        self.assertFalse(spatial_risk["editable"])
        self.assertTrue(column_of(self.spec, f"Hedgerows {POST}",
                                  "Comment")["editable"])

    def test_the_shape_rule_is_described(self):
        rule = column_of(self.spec, f"Hedgerows {POST}", "Habitat Ref")["rule"]
        self.assertEqual("hard", rule["strength"])
        self.assertIn("$geometry IS NOT NULL", rule["expression"])

    def test_a_template_with_a_lineage_column_missing_is_refused(self):
        spec = json.loads(gpkg_spec.render_json(self.spec))
        table = table_of(spec, f"Watercourses {POST}")
        table["columns"] = [column for column in table["columns"]
                            if column["name"] != "parent_uuid"]
        with self.assertRaisesRegex(gpkg_spec.SpecError,
                                    "Watercourses Post-Intervention.*"
                                    "parent_uuid"):
            gpkg_spec.check_lineage(spec["tables"])


class SpecOutputTest(support.TempDirTestCase):

    def test_two_runs_give_the_same_bytes(self):
        first = gpkg_spec.outputs(gpkg_spec.build_spec())
        second = gpkg_spec.outputs(gpkg_spec.build_spec())
        self.assertEqual(first, second)

    def test_the_committed_specification_is_up_to_date(self):
        found = gpkg_spec.differences(
            gpkg_spec.outputs(gpkg_spec.build_spec()))
        self.assertEqual(
            [], found,
            "Run python3 development/tools/gpkg_spec.py and commit spec/.")

    def test_a_stale_copy_is_reported_with_its_differences(self):
        stale = self.tmp / "spec"
        shutil.copytree(gpkg_spec.SPEC_DIR, stale)
        path = stale / gpkg_spec.MARKDOWN_NAME
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("TEXT(999)", "TEXT(500)", 1),
                        encoding="utf-8")
        found = gpkg_spec.differences(
            gpkg_spec.outputs(gpkg_spec.build_spec()), stale)
        self.assertEqual(1, len(found))
        self.assertIn(f"committed spec/{gpkg_spec.MARKDOWN_NAME}", found[0])
        self.assertIn("-| `Site Name` | `TEXT(500)`", found[0])
        self.assertIn("+| `Site Name` | `TEXT(999)`", found[0])

    def test_check_writes_nothing_and_passes_on_the_committed_copy(self):
        before = {name: (gpkg_spec.SPEC_DIR / name).read_bytes()
                  for name in (gpkg_spec.JSON_NAME, gpkg_spec.MARKDOWN_NAME)}
        result = support.run_python(support.TOOLS_DIR / "gpkg_spec.py",
                                    "--check")
        self.assertEqual(0, result.returncode, support.describe(result))
        for name, content in before.items():
            self.assertEqual(content, (gpkg_spec.SPEC_DIR / name).read_bytes())
