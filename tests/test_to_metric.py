"""Export to the Statutory Metric: a BNG Service site into the workbook.

Each test fills a copy of a blank metric from reference/, in a temporary
folder.
"""

import re
import unittest
import zipfile

from tests import support

# support puts the converter modules on sys.path.
import reference_lists as rl
import to_metric

SITE_ARGS = ("--habitats", "10", "--area-ha", "4", "--hedgerows", "2",
             "--trees", "6", "--seed", "5", "--no-legacy", "--no-metric")
AREA_PI = "Area Habitats Post-Intervention"
AREA_BASELINE_SHEET = to_metric.LAYOUT["areas"]["baseline"][0]
AREA_CREATION_SHEET = to_metric.LAYOUT["areas"]["creation"][0]
KEPT = ("Retained", "Enhanced")
# Sizes are written to 6 decimal places, so each line can be 5e-7 ha out.
AREA_TOLERANCE_HA = 1e-4
HEDGE_BASELINE_SHEET = to_metric.LAYOUT["hedgerows"]["baseline"][0]
VBA_PART = "xl/vbaProject.bin"
FULL_CALC = 'fullCalcOnLoad="1"'
NO_HABITATS = "holds no habitats"


def sheet_xml(workbook, sheet):
    with zipfile.ZipFile(workbook) as archive:
        return archive.read(to_metric.sheet_paths(archive)[sheet]).decode(
            "utf-8")


def numbers_in_column(xml, column, first_row, last_row):
    """Every number written in one column of a sheet's data rows."""
    pattern = re.compile(
        rf'<c r="{column}(\d+)"[^>]*><v>([^<]+)</v></c>')
    return [float(value) for row, value in pattern.findall(xml)
            if first_row <= int(row) <= last_row]


def inline(text):
    """A value as to_metric writes it into a cell."""
    return f'<t xml:space="preserve">{to_metric.escape(text)}</t>'


class ToMetricTest(support.TempDirTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        site = support.generate_site(cls.tmp / "site", *SITE_ARGS)
        cls.gpkg = support.site_gpkg(site)
        cls.blank = support.copy_to(support.METRIC_XLSX, cls.tmp / "blank")
        cls.out = cls.tmp / "filled.xlsx"
        cls.report = to_metric.convert(cls.gpkg, cls.blank, cls.out)

    def test_writes_one_valid_workbook(self):
        self.assertEqual([self.out], [support.Path(p)
                                      for p in self.report.paths])
        with zipfile.ZipFile(self.out) as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn("[Content_Types].xml", archive.namelist())
            self.assertIn(FULL_CALC, archive.read("xl/workbook.xml").decode())

    def assert_written(self, sheet, values):
        xml = sheet_xml(self.out, sheet)
        for value in values:
            with self.subTest(sheet=sheet, value=value):
                self.assertTrue(inline(value) in xml, value)

    def test_baseline_sheet_holds_each_habitat_type(self):
        rows = support.read_rows(self.gpkg, "Area Habitats Baseline")
        self.assert_written(AREA_BASELINE_SHEET,
                            {row["Baseline Habitat Type"] for row in rows})

    def test_each_kept_part_has_its_own_baseline_line(self):
        rows = support.read_rows(self.gpkg, AREA_PI)
        self.assert_written(AREA_BASELINE_SHEET,
                            [row["Habitat Ref"] for row in rows
                             if row["Retention Category"] in KEPT])

    def test_each_created_part_has_a_creation_line(self):
        rows = support.read_rows(self.gpkg, AREA_PI)
        self.assert_written(AREA_CREATION_SHEET,
                            [row["Habitat Ref"] for row in rows
                             if row["Retention Category"] == "Created"])

    def test_baseline_sizes_add_up_to_the_baseline_area(self):
        sheet, first_row, last_row, columns = to_metric.LAYOUT["areas"][
            "baseline"]
        sizes = numbers_in_column(sheet_xml(self.out, sheet),
                                  columns["size"], first_row, last_row)
        expected = sum(row["Area"] for row in support.read_rows(
            self.gpkg, "Area Habitats Baseline"))
        self.assertAlmostEqual(expected, sum(sizes), delta=AREA_TOLERANCE_HA)

    def test_significance_takes_the_metric_wording(self):
        xml = sheet_xml(self.out, AREA_BASELINE_SHEET)
        self.assertTrue(inline(rl.NE_SIGNIFICANCE_LOW) in xml)
        self.assertFalse(inline(rl.SIGNIFICANCE_LOW) in xml)

    def test_conditions_are_plain_words(self):
        rows = support.read_rows(self.gpkg, "Area Habitats Baseline")
        self.assert_written(AREA_BASELINE_SHEET,
                            {row["Baseline Condition"] for row in rows})

    def test_hedgerows_are_written(self):
        rows = support.read_rows(self.gpkg, "Hedgerows Baseline")
        self.assert_written(HEDGE_BASELINE_SHEET,
                            {row["Baseline Hedge Type"] for row in rows})

    def test_the_workbook_can_score_every_condition(self):
        result = support.run_python(
            support.TOOLS_DIR / "check_metric_lookups.py", self.out)
        self.assertEqual(0, result.returncode, support.describe(result))

    def test_the_blank_is_not_changed(self):
        self.assertEqual(support.METRIC_XLSX.read_bytes(),
                         self.blank.read_bytes())

    def test_refuses_a_workbook_that_already_holds_habitats(self):
        with self.assertRaisesRegex(ValueError, "already holds habitat"):
            to_metric.convert(self.gpkg, self.out, self.tmp / "again.xlsx")

    def test_allow_occupied_writes_over_a_filled_workbook(self):
        target = self.tmp / "occupied.xlsx"
        report = to_metric.convert(self.gpkg, self.out, target,
                                   allow_occupied=True)
        self.assertEqual([target], [support.Path(p) for p in report.paths])
        self.assertTrue(zipfile.is_zipfile(target))

    def test_macro_enabled_blank_gives_a_macro_enabled_copy(self):
        blank = support.copy_to(support.METRIC_XLSM, self.tmp / "blank")
        report = to_metric.convert(self.gpkg, blank,
                                   self.tmp / "macro.xlsx")
        written = support.Path(report.paths[0])
        self.assertEqual(".xlsm", written.suffix)
        with zipfile.ZipFile(written) as archive:
            self.assertIn(VBA_PART, archive.namelist())
        self.assertTrue(inline(rl.NE_SIGNIFICANCE_LOW)
                        in sheet_xml(written, AREA_BASELINE_SHEET))

    def test_refuses_the_gis_import_tool(self):
        with self.assertRaisesRegex(ValueError, "not a readable"):
            to_metric.convert(self.gpkg, support.GIS_IMPORT_TOOL,
                              self.tmp / "import-tool.xlsx")

    def test_command_line_reports_a_filled_workbook(self):
        result = support.run_python(
            support.PACKAGE_DIR / "to_metric.py", self.gpkg,
            "--metric", self.out, "-o", self.tmp / "cli.xlsx")
        self.assertEqual(1, result.returncode)
        self.assertIn("already holds habitat data", result.stderr)


class OldTableNamesTest(support.TempDirTestCase):
    """A file from before the "Area Habitats" / "Individual Trees" rename."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.old = support.make_old_named_gpkg(cls.tmp / "old.gpkg")
        cls.blank = support.copy_to(support.METRIC_XLSX, cls.tmp / "blank")

    def test_warns_that_nothing_was_written(self):
        report = to_metric.convert(self.old, self.blank,
                                   self.tmp / "empty.xlsx")
        self.assertTrue(any(NO_HABITATS in w for w in report.warnings))

    # BUG (doc vs code): plugin/README.md says "A file or template with the
    # older table names (`Habitats Baseline`, `Trees Baseline`) is refused".
    # to_metric.read_staged (to_metric.py:298-314) reads a missing table as
    # empty, so the old file gives a blank metric and only the warning
    # "the GeoPackage holds no habitats", which does not name the cause.
    @unittest.expectedFailure
    def test_refuses_a_file_with_the_old_table_names(self):
        with self.assertRaises(ValueError):
            to_metric.convert(self.old, self.blank, self.tmp / "refused.xlsx")


if __name__ == "__main__":
    unittest.main()
