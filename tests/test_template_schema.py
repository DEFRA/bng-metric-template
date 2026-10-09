"""The GeoPackage of the BNG Service template, opened read-only."""

import unittest

from tests import support

# support puts the converter modules on sys.path.
import new_to_old
import old_to_new

STAGES = ("Baseline", "Post-Intervention")
HABITAT_LAYERS = ("Area Habitats", "Vertical Area Habitats", "Hedgerows",
                  "Watercourses", "Individual Trees")
RED_LINE = "Red Line Boundary"
EXPECTED_TABLES = {RED_LINE} | {f"{layer} {stage}"
                                for layer in HABITAT_LAYERS
                                for stage in STAGES}
OLD_TABLE_NAMES = ("Habitats Baseline", "Habitats Post-Intervention",
                   "Trees Baseline", "Trees Post-Intervention")
GEOMETRY_TYPES = {
    "Area Habitats": "POLYGON",
    "Vertical Area Habitats": "LINESTRING",
    "Hedgerows": "LINESTRING",
    "Watercourses": "LINESTRING",
    "Individual Trees": "POINT",
}
BNG_SRS_ID = 27700
REF = "Habitat Ref"
PARENT_REF = "Parent Ref"
BASELINE_ONLY = ("feature_uuid",)
POST_ONLY = (PARENT_REF, "parent_uuid", "parent_geom")
GONE = ("parent_checksum", "Parcel Ref", "Tree Ref")
COMMENT = "Comment"


def habitat_tables(stage):
    return [f"{layer} {stage}" for layer in HABITAT_LAYERS]


class TemplateSchemaTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tables = support.feature_tables(support.SERVICE_GPKG)
        cls.columns = {table: support.columns(support.SERVICE_GPKG, table)
                       for table in cls.tables}

    def test_feature_tables_are_exactly_the_current_names(self):
        self.assertEqual(EXPECTED_TABLES, self.tables)

    def test_old_table_names_are_gone(self):
        for name in OLD_TABLE_NAMES:
            with self.subTest(table=name):
                self.assertNotIn(name, self.tables)

    def test_geometry_types_and_srs(self):
        conn = support.connect_read_only(support.SERVICE_GPKG)
        try:
            found = {table: (kind, srs) for table, kind, srs in conn.execute(
                "SELECT table_name, geometry_type_name, srs_id "
                "FROM gpkg_geometry_columns")}
        finally:
            conn.close()
        self.assertEqual(("POLYGON", BNG_SRS_ID), found[RED_LINE])
        for layer, kind in GEOMETRY_TYPES.items():
            for stage in STAGES:
                with self.subTest(table=f"{layer} {stage}"):
                    self.assertEqual((kind, BNG_SRS_ID),
                                     found[f"{layer} {stage}"])

    def test_every_habitat_table_has_one_habitat_ref(self):
        for table in habitat_tables("Baseline") + habitat_tables(
                "Post-Intervention"):
            with self.subTest(table=table):
                self.assertEqual(1, self.columns[table].count(REF))

    def test_lineage_columns_sit_on_the_right_stage(self):
        for table in habitat_tables("Baseline"):
            with self.subTest(table=table):
                for column in BASELINE_ONLY:
                    self.assertIn(column, self.columns[table])
                for column in POST_ONLY:
                    self.assertNotIn(column, self.columns[table])
        for table in habitat_tables("Post-Intervention"):
            with self.subTest(table=table):
                for column in POST_ONLY:
                    self.assertIn(column, self.columns[table])
                for column in BASELINE_ONLY:
                    self.assertNotIn(column, self.columns[table])

    def test_every_habitat_table_has_a_comment_before_its_hidden_columns(self):
        """A free-text note on both stages, after the columns a user fills."""
        for stage in STAGES:
            hidden = BASELINE_ONLY if stage == "Baseline" else POST_ONLY[1:]
            for table in habitat_tables(stage):
                with self.subTest(table=table):
                    names = self.columns[table]
                    self.assertEqual(1, names.count(COMMENT))
                    self.assertEqual(names.index(hidden[0]) - 1,
                                     names.index(COMMENT))

    def test_retired_columns_are_gone(self):
        for table, names in self.columns.items():
            for column in GONE:
                with self.subTest(table=table, column=column):
                    self.assertNotIn(column, names)

    def test_template_ships_empty(self):
        for table in self.tables:
            with self.subTest(table=table):
                self.assertEqual([], support.read_rows(support.SERVICE_GPKG,
                                                       table))

    def test_converter_schema_matches_the_template(self):
        """old_to_new writes a new file with these columns, in this order."""
        for table, spec in old_to_new.STAGED_LAYERS.items():
            with self.subTest(table=table):
                expected = ["fid", spec["geom_column"]] + [
                    name for name, _type in spec["columns"]]
                self.assertEqual(expected, self.columns[table])

    def test_converters_read_the_template_table_names(self):
        staged = {name for spec in new_to_old.STAGED_TABLES.values()
                  for stage in ("baseline", "pi") for name in spec[stage]}
        staged.add(new_to_old.STAGED_REDLINE_TABLE)
        self.assertEqual(EXPECTED_TABLES, staged)
        self.assertEqual(EXPECTED_TABLES, set(old_to_new.STAGED_LAYERS))


class LegacyTemplateSchemaTest(unittest.TestCase):

    def test_legacy_template_carries_every_layer_the_converter_writes(self):
        gpkg = (support.LEGACY_TEMPLATE_DIR / "Layers"
                / "Net Gain Habitat Mapping Layers.gpkg")
        tables = support.feature_tables(gpkg)
        for table in new_to_old.LEGACY_LAYERS:
            with self.subTest(table=table):
                self.assertIn(table, tables)


if __name__ == "__main__":
    unittest.main()
