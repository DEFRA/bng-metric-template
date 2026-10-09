"""Export to the Statutory Metric: a BNG Service site into the workbook.

Each test fills a copy of a blank metric from reference/, in a temporary
folder.
"""

import html
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
AREA_ENHANCEMENT_SHEET = to_metric.LAYOUT["areas"]["enhancement"][0]
AREA_COLUMNS = {stage: to_metric.LAYOUT["areas"][stage][3]
                for stage in ("baseline", "creation", "enhancement")}
TREE_BASELINE = "Individual Trees Baseline"
TREE_PI = "Individual Trees Post-Intervention"
# Module -> (baseline table, post-intervention table).
TABLES = {kind: (base, pi) for kind, base, pi, *_rest in to_metric.MODULES}
TABLES["trees"] = to_metric.TREE_TABLES
# Module -> the module whose sheets it is written on.
SHEETS_OF = {"areas": "areas", "hedgerows": "hedgerows",
             "watercourses": "watercourses", "trees": "areas"}
WATERCOURSE_LINE = [(455900.0, 285300.0), (455950.0, 285310.0)]
WATERCOURSE = {
    "Baseline River Type": "Ditches",
    "Baseline Distinctiveness": "Medium",
    "Baseline Condition": "Fairly Poor",
    "Baseline Strategic Significance": "Low",
    "Baseline Encroachment into Watercourse": "Minor",
    "Baseline Encroachment into riparian zone": "Major/Minor",
}
WATERCOURSE_PROPOSED = {
    "Retention Category": "Enhanced",
    "Proposed River Type": "Ditches",
    "Proposed Condition": "Moderate",
    "Proposed Strategic Significance": "Low",
    "Proposed Encroachment into Watercourse": "No Encroachment",
    "Proposed Encroachment into riparian zone": "Minor/Minor",
    "Spatial risk category": "N/A",
}
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


def cells_by_row(xml, column):
    """Row number -> the text written in one column of a sheet."""
    pattern = re.compile(
        rf'<c r="{column}(\d+)"[^>]*t="inlineStr"><is>'
        rf'<t xml:space="preserve">(.*?)</t></is></c>', re.S)
    return {int(row): html.unescape(text)
            for row, text in pattern.findall(xml)}


def cell_on_row_of(xml, ref_column, ref, column):
    """The text in `column` on the row whose reference cell holds `ref`."""
    rows = [number for number, text in cells_by_row(xml, ref_column).items()
            if text == ref]
    if len(rows) != 1:
        raise AssertionError(f"{ref!r} is on {len(rows)} row(s)")
    return cells_by_row(xml, column).get(rows[0])


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
        """Area habitats and the tree helper's area of every baseline tree."""
        sheet, first_row, last_row, columns = to_metric.LAYOUT["areas"][
            "baseline"]
        sizes = numbers_in_column(sheet_xml(self.out, sheet),
                                  columns["size"], first_row, last_row)
        expected = sum(row["Area"] for row in support.read_rows(
            self.gpkg, "Area Habitats Baseline"))
        expected += sum(
            to_metric.TREE_AREA_HA[row["Baseline Tree Size"]] * row["Count"]
            for row in support.read_rows(self.gpkg, TREE_BASELINE))
        self.assertAlmostEqual(expected, sum(sizes), delta=AREA_TOLERANCE_HA)

    def test_trees_follow_the_area_habitats_on_the_baseline_sheet(self):
        xml = sheet_xml(self.out, AREA_BASELINE_SHEET)
        refs = [row["Habitat Ref"]
                for row in support.read_rows(self.gpkg, TREE_BASELINE)]
        rows = cells_by_row(xml, AREA_COLUMNS["baseline"]["ref"])
        tree_rows = [number for number, text in rows.items() if text in refs]
        self.assertTrue(tree_rows)
        self.assertEqual(sorted(rows)[-len(tree_rows):], sorted(tree_rows))
        broad = cells_by_row(xml, AREA_COLUMNS["baseline"]["broad"])
        for number in tree_rows:
            with self.subTest(row=number):
                self.assertEqual(to_metric.TREES_BROAD, broad[number])

    def test_created_trees_are_on_the_creation_sheet(self):
        planted = [row["Habitat Ref"] for row in support.read_rows(
            self.gpkg, TREE_PI) if row["Retention Category"] == "Created"]
        self.assertTrue(planted)
        self.assert_written(AREA_CREATION_SHEET, planted)

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


def add_watercourse(gpkg):
    """A watercourse enhanced in place, so every module has an enhancement."""
    uuid = "c0ffee00-0000-4000-8000-000000000001"
    support.insert_feature(gpkg, "Watercourses Baseline",
                           support.line(WATERCOURSE_LINE),
                           {"Habitat Ref": "WC-01", "Length": 51.0,
                            "feature_uuid": uuid, **WATERCOURSE})
    support.insert_feature(gpkg, "Watercourses Post-Intervention",
                           support.line(WATERCOURSE_LINE),
                           {"Habitat Ref": "WC-01", "Parent Ref": "WC-01",
                            "parent_uuid": uuid, "Length": 51.0,
                            **WATERCOURSE, **WATERCOURSE_PROPOSED})


class CommentsAndTreesTest(support.TempDirTestCase):
    """Every row commented, and a tree enhanced, then exported."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        site = support.generate_site(cls.tmp / "site", *SITE_ARGS)
        cls.gpkg = support.copy_to(support.site_gpkg(site), cls.tmp,
                                   "commented.gpkg")
        add_watercourse(cls.gpkg)
        support.comment_every_row(cls.gpkg)
        cls.tree = support.enhance_a_tree(cls.gpkg)
        cls.blank = support.copy_to(support.METRIC_XLSX, cls.tmp / "blank")
        cls.out = cls.tmp / "commented.xlsx"
        cls.report = to_metric.convert(cls.gpkg, cls.blank, cls.out)
        cls.parents = {}
        cls.rows = {}
        for kind, (base, pi) in TABLES.items():
            baseline = support.read_rows(cls.gpkg, base)
            cls.rows[kind] = (baseline, support.read_rows(cls.gpkg, pi))
            cls.parents.update(
                {row["feature_uuid"]: (base, row) for row in baseline})

    def sheet(self, kind, stage):
        name, _first, _last, columns = to_metric.LAYOUT[SHEETS_OF[kind]][stage]
        return sheet_xml(self.out, name), columns

    def comments_on(self, kind, stage, ref):
        """The comments on every row of a sheet holding `ref`.

        A kept part and its parent's lost remainder can share a reference.
        """
        xml, columns = self.sheet(kind, stage)
        comments = cells_by_row(xml, columns["comment"])
        return [comments.get(number) for number, text
                in cells_by_row(xml, columns["ref"]).items() if text == ref]

    def test_each_part_carries_its_comments_to_its_own_sheet(self):
        for kind, (_baseline, pi_rows) in self.rows.items():
            pi = TABLES[kind][1]
            for row in pi_rows:
                own = support.comment_for(pi, row["fid"])
                retention = row["Retention Category"]
                parent = self.parents.get(row["parent_uuid"])
                with self.subTest(kind=kind, ref=row["Habitat Ref"]):
                    if retention == "Created" or parent is None:
                        self.assertEqual([own], self.comments_on(
                            kind, "creation", row["Habitat Ref"]))
                        continue
                    base_comment = support.comment_for(parent[0],
                                                       parent[1]["fid"])
                    on_baseline = self.comments_on(kind, "baseline",
                                                   row["Habitat Ref"])
                    if retention == "Enhanced":
                        self.assertIn(base_comment, on_baseline)
                        self.assertEqual([own], self.comments_on(
                            kind, "enhancement", row["Habitat Ref"]))
                    else:
                        self.assertIn(
                            f"{base_comment} | Post-intervention: {own}",
                            on_baseline)

    def test_a_lost_line_carries_its_baseline_comment(self):
        xml, columns = self.sheet("areas", "baseline")
        comments = set(cells_by_row(xml, columns["comment"]).values())
        kept = {row["parent_uuid"] for row in self.rows["trees"][1]
                if row["Retention Category"] in KEPT}
        lost = [row for row in self.rows["trees"][0]
                if row["feature_uuid"] not in kept]
        self.assertTrue(lost)
        for row in lost:
            with self.subTest(ref=row["Habitat Ref"]):
                self.assertIn(support.comment_for(TREE_BASELINE, row["fid"]),
                              comments)

    def test_an_enhanced_tree_is_on_the_enhancement_sheet(self):
        part = next(row for row in self.rows["trees"][1]
                    if row["Habitat Ref"] == self.tree)
        parent = self.parents[part["parent_uuid"]][1]
        xml, columns = self.sheet("trees", "enhancement")
        self.assertEqual(part["Proposed Condition"], cell_on_row_of(
            xml, columns["ref"], self.tree, columns["condition"]))
        self.assertEqual(part["Proposed Rural or Urban Tree"], cell_on_row_of(
            xml, columns["ref"], self.tree, columns["habitat"]))
        xml, columns = self.sheet("trees", "baseline")
        rows = [n for n, text in cells_by_row(xml, columns["ref"]).items()
                if text == self.tree]
        enhanced = numbers_in_column(xml, columns["enhanced"], rows[0],
                                     rows[0])
        area = to_metric.TREE_AREA_HA[parent["Baseline Tree Size"]]
        self.assertAlmostEqual(area * part["Count"], enhanced[0], places=6)

    def test_the_enhancement_rows_follow_the_enhanced_baseline_rows(self):
        """The nth enhancement row belongs to the nth enhanced baseline row."""
        for kind in ("areas", "hedgerows", "watercourses"):
            xml, columns = self.sheet(kind, "baseline")
            first = to_metric.LAYOUT[kind]["baseline"][1]
            last = to_metric.LAYOUT[kind]["baseline"][2]
            refs = cells_by_row(xml, columns["ref"])
            enhanced = re.findall(
                rf'<c r="{columns["enhanced"]}(\d+)"[^>]*><v>([^<]+)</v>', xml)
            in_order = [refs[int(row)] for row, value in enhanced
                        if first <= int(row) <= last and float(value) > 0]
            xml, columns = self.sheet(kind, "enhancement")
            written = [text for _row, text in sorted(
                cells_by_row(xml, columns["ref"]).items())]
            with self.subTest(kind=kind):
                self.assertTrue(written)
                self.assertEqual(in_order, written)

    def test_the_workbook_can_score_every_condition(self):
        result = support.run_python(
            support.TOOLS_DIR / "check_metric_lookups.py", self.out)
        self.assertEqual(0, result.returncode, support.describe(result))

    def test_consolidating_keeps_every_comment(self):
        out = self.tmp / "consolidated.xlsx"
        to_metric.convert(self.gpkg, self.blank, out, consolidate=True)
        xml, columns = sheet_xml(out, AREA_CREATION_SHEET), AREA_COLUMNS[
            "creation"]
        written = " | ".join(cells_by_row(xml, columns["comment"]).values())
        for row in self.rows["areas"][1]:
            if row["Retention Category"] != "Created":
                continue
            with self.subTest(ref=row["Habitat Ref"]):
                self.assertIn(support.comment_for(
                    "Area Habitats Post-Intervention", row["fid"]), written)


class TreeWarningsTest(support.TempDirTestCase):
    """What the metric refuses from a tree layer is named in the report."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        site = support.generate_site(cls.tmp / "site", *SITE_ARGS)
        cls.gpkg = support.copy_to(support.site_gpkg(site), cls.tmp,
                                   "trees.gpkg")
        cls.tree = support.enhance_a_tree(cls.gpkg)
        part = next(row for row in support.read_rows(cls.gpkg, TREE_PI)
                    if row["Habitat Ref"] == cls.tree)
        support.update(cls.gpkg, TREE_PI,
                       {"Proposed Condition": part["Baseline Condition"],
                        "Proposed Tree Size": "Very large",
                        "Comment": "Bad\x0bcharacter"},
                       "fid", part["fid"])
        cls.blank = support.copy_to(support.METRIC_XLSX, cls.tmp / "blank")
        cls.out = cls.tmp / "trees.xlsx"
        cls.report = to_metric.convert(cls.gpkg, cls.blank, cls.out)

    def warnings_mentioning(self, text):
        return [w for w in self.report.warnings if text in w]

    def test_an_enhanced_tree_that_does_not_improve_is_named(self):
        found = self.warnings_mentioning("do not move to a better condition")
        self.assertEqual(1, len(found))
        self.assertIn(self.tree, found[0])

    def test_an_enhanced_tree_that_grows_is_named(self):
        found = self.warnings_mentioning("proposed size class")
        self.assertEqual(1, len(found))
        self.assertIn(self.tree, found[0])

    def test_a_character_xml_cannot_hold_is_left_out(self):
        xml = sheet_xml(self.out, AREA_ENHANCEMENT_SHEET)
        self.assertIn(inline("Badcharacter"), xml)
        self.assertNotIn("\x0b", xml)


class OldTableNamesTest(support.TempDirTestCase):
    """A file from before the "Area Habitats" / "Individual Trees" rename."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.old = support.make_old_named_gpkg(cls.tmp / "old.gpkg")
        cls.blank = support.copy_to(support.METRIC_XLSX, cls.tmp / "blank")

    def test_refuses_a_file_with_the_old_table_names(self):
        out = self.tmp / "refused.xlsx"
        with self.assertRaisesRegex(ValueError, "earlier version") as caught:
            to_metric.convert(self.old, self.blank, out)
        self.assertIn('"Trees Baseline"', str(caught.exception))
        self.assertFalse(out.exists())

    def test_refuses_a_file_with_no_habitat_tables(self):
        redline_only = support.make_redline_only_gpkg(
            self.tmp / "redline-only.gpkg")
        with self.assertRaisesRegex(ValueError, "none of the BNG Service"):
            to_metric.convert(redline_only, self.blank,
                              self.tmp / "none.xlsx")

    def test_an_empty_current_file_still_warns_it_has_no_habitats(self):
        empty = support.copy_to(support.SERVICE_GPKG, self.tmp / "empty")
        report = to_metric.convert(empty, self.blank, self.tmp / "empty.xlsx")
        self.assertTrue(any(NO_HABITATS in w for w in report.warnings))

    def test_command_line_explains_the_refusal(self):
        result = support.run_python(
            support.PACKAGE_DIR / "to_metric.py", self.old,
            "--metric", self.blank, "-o", self.tmp / "cli.xlsx")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("earlier version", result.stderr + result.stdout)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
