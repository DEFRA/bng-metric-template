"""Convert to legacy: a BNG Service site into the Natural England pair.

The site comes from the small-site generator. A copy of its GeoPackage gets a
few extra rows (a watercourse, a vertical area habitat) and a few changed
values (High significance on an Enhanced parcel and a planted tree), so every
mapping below is exercised whatever the generator happens to choose.
"""

import csv
import re
import unittest

from tests import support

# support puts the converter modules on sys.path.
import gpkg_common
import new_to_old
import reference_lists as rl

SITE_ARGS = ("--habitats", "10", "--area-ha", "4", "--hedgerows", "2",
             "--trees", "6", "--seed", "5", "--no-legacy", "--no-metric")
SQ_M_PER_HA = 10000
WHOLE_UNIT_TOLERANCE = 0.5
BASELINE_FILE = f"{new_to_old.LEGACY_LAYERS_STEM} - Baseline.gpkg"
PI_FILE = f"{new_to_old.LEGACY_LAYERS_STEM} - Post-intervention.gpkg"
CSV_FILES = ("Habitats.csv", "Hedgerows.csv", "Rivers.csv")

AREA_PI = "Area Habitats Post-Intervention"
TREE_PI = "Individual Trees Post-Intervention"
REF = "Habitat Ref"
RETENTION = "Retention Category"
SIGNIFICANCE = rl.PROPOSED_SIGNIFICANCE

WATERCOURSE_REF = "WC-T01"
WATERCOURSE_LINE = [(455900.0, 285300.0), (455950.0, 285310.0)]
WATERCOURSE_BASELINE = {
    REF: WATERCOURSE_REF,
    "Baseline River Type": "Ditches",
    "Baseline Distinctiveness": "Medium",
    "Baseline Condition": "Fairly Poor",
    "Baseline Strategic Significance": "Low",
    "Baseline Encroachment into Watercourse": "Minor",
    "Baseline Encroachment into riparian zone": "Major/Minor",
    "Length": 51.0,
}
WATERCOURSE_PI = {
    REF: WATERCOURSE_REF,
    "Parent Ref": WATERCOURSE_REF,
    "Baseline River Type": "Ditches",
    "Baseline Distinctiveness": "Medium",
    "Baseline Condition": "Fairly Poor",
    "Baseline Strategic Significance": "Low",
    "Baseline Encroachment into Watercourse": "Minor",
    "Baseline Encroachment into riparian zone": "Major/Minor",
    RETENTION: "Retained",
    "Proposed River Type": "Ditches",
    "Proposed Condition": "Fairly Poor",
    SIGNIFICANCE: "Low",
    "Proposed Encroachment into Watercourse": "Minor",
    "Proposed Encroachment into riparian zone": "Major/Minor",
    "Spatial risk category": "N/A",
    "Length": 51.0,
}
VERTICAL_ROW = {REF: "VA-T01", "Baseline Habitat Type": "Green wall",
                "Baseline Strategic Significance": "Low", "Area": 0.001}
VERTICAL_LINE = [(455910.0, 285320.0), (455915.0, 285320.0)]


def legacy_labels(relative, context_column, label_column="Label"):
    """{context: set of numbered labels} from a Natural England list."""
    folder = (support.LEGACY_TEMPLATE_DIR / support.CSV_REFERENCES)
    found = {}
    with open(folder / relative, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            found.setdefault(row[context_column], set()).add(row[label_column])
    return found


def first(rows, predicate):
    return next(row for row in rows if predicate(row))


def prepare_input(site_dir, folder):
    """Copy the site's GeoPackage and add the rows the tests need."""
    gpkg = support.copy_to(support.site_gpkg(site_dir), folder, "input.gpkg")
    enhanced = first(support.read_rows(gpkg, AREA_PI),
                     lambda row: row[RETENTION] == "Enhanced")
    support.update(gpkg, AREA_PI, {SIGNIFICANCE: rl.SIGNIFICANCE_HIGH},
                   REF, enhanced[REF])
    planted = first(support.read_rows(gpkg, TREE_PI),
                    lambda row: row["Category"] == rl.TREE_NEWLY_PLANTED)
    support.update(gpkg, TREE_PI, {SIGNIFICANCE: rl.SIGNIFICANCE_HIGH},
                   REF, planted[REF])
    support.insert_feature(gpkg, "Watercourses Baseline",
                           support.line(WATERCOURSE_LINE),
                           WATERCOURSE_BASELINE)
    support.insert_feature(gpkg, "Watercourses Post-Intervention",
                           support.line(WATERCOURSE_LINE), WATERCOURSE_PI)
    support.insert_feature(gpkg, "Vertical Area Habitats Baseline",
                           support.line(VERTICAL_LINE), VERTICAL_ROW)
    support.comment_every_row(gpkg)
    support.enhance_a_tree(gpkg)
    return gpkg, enhanced[REF], planted[REF]


# Template table -> its legacy layer and that layer's comment column.
LEGACY_COMMENT = {
    "Area Habitats": ("Habitats", "Comment"),
    "Hedgerows": ("Hedgerows", "Comments"),
    "Watercourses": ("Rivers", "Comments"),
    "Individual Trees": ("Urban Trees", "Comment"),
}


class NewToOldTest(support.TempDirTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        site = support.generate_site(cls.tmp / "site", *SITE_ARGS)
        cls.input, cls.high_area_ref, cls.high_tree_ref = prepare_input(
            site, cls.tmp)
        cls.out = cls.tmp / "legacy"
        cls.report = new_to_old.convert(
            cls.input, cls.out, carry_lineage=True, dry_run=False,
            formats=("gpkg", "csv"))
        cls.baseline = cls.out / BASELINE_FILE
        cls.pi = cls.out / PI_FILE

    def legacy(self, gpkg, table):
        return support.read_rows(gpkg, table)

    def service(self, table):
        return support.read_rows(self.input, table)

    def warnings_mentioning(self, text):
        return [w for w in self.report.warnings if text in w]

    def test_writes_both_files_with_every_legacy_layer(self):
        for gpkg in (self.baseline, self.pi):
            with self.subTest(file=gpkg.name):
                self.assertEqual(set(new_to_old.LEGACY_LAYERS),
                                 support.feature_tables(gpkg))

    def test_legacy_columns_are_the_legacy_schema(self):
        for table, spec in new_to_old.LEGACY_LAYERS.items():
            with self.subTest(table=table):
                expected = ["fid", spec["geom_column"]] + [
                    name for name, _type in spec["columns"]]
                self.assertEqual(expected,
                                 support.columns(self.baseline, table))

    def test_habitat_ref_becomes_parcel_ref(self):
        expected = [row[REF] for row in self.service("Area Habitats Baseline")]
        found = [row["Parcel Ref"]
                 for row in self.legacy(self.baseline, "Habitats")]
        self.assertEqual(expected, found)
        self.assertNotIn(REF, support.columns(self.baseline, "Habitats"))

    def test_habitat_ref_becomes_tree_ref_for_trees(self):
        expected = [row[REF]
                    for row in self.service("Individual Trees Baseline")]
        found = [row["Tree Ref"]
                 for row in self.legacy(self.baseline, "Urban Trees")]
        self.assertEqual(expected, found)

    def test_area_conditions_take_the_legacy_number(self):
        allowed = legacy_labels(rl.AREA_CONDITION.path, "UKHAB")
        for gpkg, prefixes in ((self.baseline, ("Baseline",)),
                               (self.pi, ("Baseline", "Proposed"))):
            for row in self.legacy(gpkg, "Habitats"):
                for prefix in prefixes:
                    habitat = row[f"{prefix} Habitat Type"]
                    value = row[f"{prefix} Condition"]
                    with self.subTest(file=gpkg.name, ref=row["Parcel Ref"],
                                      column=prefix):
                        self.assertRegex(value, gpkg_common.NUMBERED_LABEL)
                        self.assertIn(value, allowed[habitat])

    def test_watercourse_values_take_the_legacy_number(self):
        row = first(self.legacy(self.pi, "Rivers"),
                    lambda r: r["Parcel Ref"] == WATERCOURSE_REF)
        self.assertEqual("4. Fairly Poor", row["Baseline Condition"])
        self.assertEqual("2. Retained", row[RETENTION])
        self.assertEqual("1. Major/Minor",
                         row["Baseline Encroachment into riparian zone"])

    def test_tree_proposed_condition_stays_unnumbered(self):
        for row in self.legacy(self.pi, "Urban Trees"):
            value = row["Proposed Condition"]
            if value:
                with self.subTest(ref=row["Tree Ref"]):
                    self.assertNotRegex(value, gpkg_common.NUMBERED_LABEL)

    def test_baseline_significance_takes_the_low_wording(self):
        for table in ("Habitats", "Hedgerows", "Rivers", "Urban Trees"):
            for row in self.legacy(self.baseline, table):
                with self.subTest(table=table):
                    self.assertEqual(rl.NE_SIGNIFICANCE_LOW,
                                     row[rl.BASELINE_SIGNIFICANCE])

    def test_proposed_significance_takes_the_wording_of_low_and_high(self):
        source = support.by_ref(self.service(AREA_PI), REF)
        wording = {"Low": rl.NE_SIGNIFICANCE_LOW,
                   "High": rl.NE_SIGNIFICANCE_HIGH}
        for row in self.legacy(self.pi, "Habitats"):
            ref = row["Parcel Ref"]
            with self.subTest(ref=ref):
                self.assertEqual(wording[source[ref][SIGNIFICANCE]],
                                 row[SIGNIFICANCE])
        high = first(self.legacy(self.pi, "Habitats"),
                     lambda r: r["Parcel Ref"] == self.high_area_ref)
        self.assertEqual(rl.NE_SIGNIFICANCE_HIGH, high[SIGNIFICANCE])

    def test_high_on_a_tree_takes_the_tree_wording(self):
        tree = first(self.legacy(self.pi, "Urban Trees"),
                     lambda r: r["Tree Ref"] == self.high_tree_ref)
        self.assertEqual(rl.NE_SIGNIFICANCE_HIGH_TREES, tree[SIGNIFICANCE])

    def test_planted_tree_baseline_significance_is_not_applicable(self):
        tree = first(self.legacy(self.pi, "Urban Trees"),
                     lambda r: r["Tree Ref"] == self.high_tree_ref)
        self.assertEqual(rl.NOT_APPLICABLE, tree[rl.BASELINE_SIGNIFICANCE])

    def test_area_is_written_in_whole_square_metres(self):
        source = support.by_ref(self.service("Area Habitats Baseline"), REF)
        for row in self.legacy(self.baseline, "Habitats"):
            hectares = source[row["Parcel Ref"]]["Area"]
            with self.subTest(ref=row["Parcel Ref"]):
                self.assertIsInstance(row["Area"], int)
                self.assertAlmostEqual(hectares * SQ_M_PER_HA, row["Area"],
                                       delta=WHOLE_UNIT_TOLERANCE)

    def test_lost_trees_are_written_as_lost_rows(self):
        baseline = {row[REF] for row in self.service(
            "Individual Trees Baseline")}
        kept = {row["Parent Ref"] for row in self.service(TREE_PI)}
        lost = {row["Tree Ref"] for row in self.legacy(self.pi, "Urban Trees")
                if row[RETENTION] == new_to_old.RETENTION_LOST}
        self.assertTrue(baseline - kept)
        self.assertEqual(baseline - kept, lost)

    # BUG: reference_lists._legacy_blank (reference_lists.py:476-495) and the
    # 1.5.0 changelog say a lost tree's Proposed Strategic Significance is
    # written as "N/A", the only value the Natural England list offers for a
    # Lost tree. But new_to_old.tree_lost_row (new_to_old.py:722) builds the
    # Lost rows after to_legacy_significance has run, and sets no proposed
    # significance, so they are written blank.
    @unittest.expectedFailure
    def test_lost_tree_rows_have_not_applicable_proposed_significance(self):
        lost = [row for row in self.legacy(self.pi, "Urban Trees")
                if row[RETENTION] == new_to_old.RETENTION_LOST]
        self.assertTrue(lost)
        for row in lost:
            with self.subTest(ref=row["Tree Ref"]):
                self.assertEqual(rl.NOT_APPLICABLE, row[SIGNIFICANCE])

    def test_lineage_is_recorded_in_comments(self):
        parented = [row for row in self.legacy(self.pi, "Habitats")
                    if row["Comment"]]
        self.assertTrue(parented)
        for row in parented:
            with self.subTest(ref=row["Parcel Ref"]):
                self.assertRegex(row["Comment"], r"\[parent=[^\]]+\]")

    def test_every_comment_reaches_its_legacy_file(self):
        """Each stage's comments go to that stage's legacy file."""
        for kind, (layer, column) in LEGACY_COMMENT.items():
            for stage, gpkg in (("Baseline", self.baseline),
                                ("Post-Intervention", self.pi)):
                table = f"{kind} {stage}"
                written = [row[column] or "" for row in self.legacy(gpkg, layer)]
                for row in self.service(table):
                    expected = support.comment_for(table, row["fid"])
                    with self.subTest(table=table, ref=row[REF]):
                        self.assertTrue(
                            any(text.startswith(expected) for text in written))

    def test_lineage_follows_the_comment(self):
        """The breadcrumb comes after the surveyor's words, not in place of them."""
        rows = [row for row in self.legacy(self.pi, "Habitats")
                if "[parent=" in (row["Comment"] or "")]
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(ref=row["Parcel Ref"]):
                self.assertRegex(row["Comment"],
                                 r"(?s)^Note on .+ \[parent=[^\]]+\]$")

    def test_enhanced_tree_is_written_with_a_warning(self):
        enhanced = [row for row in self.service(TREE_PI)
                    if row[RETENTION] == "Enhanced"]
        self.assertTrue(enhanced)
        legacy = support.by_ref(self.legacy(self.pi, "Urban Trees"),
                                "Tree Ref")
        for row in enhanced:
            with self.subTest(ref=row[REF]):
                written = legacy[row["Parent Ref"]]
                self.assertEqual("Enhanced", written[RETENTION])
                self.assertEqual(row["Proposed Condition"],
                                 written["Proposed Condition"])
        self.assertEqual(1, len(self.warnings_mentioning("are Enhanced")))

    def test_baseline_comments_are_said_to_be_missing_from_the_csvs(self):
        self.assertTrue(any("baseline comment(s) are not in the import tool"
                            in note for note in self.report.lines))

    def test_consolidating_the_csvs_warns_that_comments_are_replaced(self):
        report = new_to_old.convert(
            self.input, self.tmp / "consolidated", carry_lineage=False,
            dry_run=False, formats=("csv",), consolidate=True)
        replaced = [w for w in report.warnings
                    if "replaced by the consolidation note" in w]
        self.assertTrue(any(w.startswith("Habitats.csv") for w in replaced))

    def test_warns_that_vertical_area_habitats_are_not_carried(self):
        self.assertEqual(
            1, len(self.warnings_mentioning("vertical area habitat")))

    def test_import_tool_csvs_hold_plain_labels(self):
        folder = self.out / new_to_old.CSV_SUBFOLDER
        for name in CSV_FILES:
            with self.subTest(csv=name):
                self.assertTrue((folder / name).is_file())
        with open(folder / "Habitats.csv", newline="",
                  encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        self.assertTrue(rows)
        for row in rows:
            for column in ("Baseline Condition", "Proposed Condition",
                           RETENTION):
                with self.subTest(ref=row["Parcel Ref"], column=column):
                    self.assertNotRegex(row[column],
                                        gpkg_common.NUMBERED_LABEL)

    def test_dry_run_writes_nothing(self):
        out = self.tmp / "dry-run"
        report = new_to_old.convert(self.input, out, carry_lineage=False,
                                    dry_run=True)
        self.assertFalse(out.exists())
        self.assertEqual(len(self.service("Area Habitats Baseline")),
                         report.counts["Habitats (baseline)"])


class OldTableNamesTest(support.TempDirTestCase):
    """Files from before the "Area Habitats" / "Individual Trees" rename."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.old = support.make_old_named_gpkg(cls.tmp / "old.gpkg")
        cls.redline_only = support.make_redline_only_gpkg(
            cls.tmp / "redline-only.gpkg")
        cls.partial = support.make_partial_gpkg(cls.tmp / "partial.gpkg")

    def test_refuses_a_file_with_the_old_table_names(self):
        with self.assertRaisesRegex(ValueError, "earlier version") as caught:
            new_to_old.convert(self.old, self.tmp / "refused",
                               carry_lineage=False, dry_run=False)
        self.assertIn('"Habitats Baseline"', str(caught.exception))
        self.assertFalse((self.tmp / "refused").exists())

    def test_refuses_a_file_with_no_habitat_tables(self):
        with self.assertRaisesRegex(ValueError, "none of the BNG Service"):
            new_to_old.convert(self.redline_only, self.tmp / "none",
                               carry_lineage=False, dry_run=True)

    def test_names_each_missing_table_of_a_partial_file(self):
        report = new_to_old.convert(self.partial, self.tmp / "out",
                                    carry_lineage=False, dry_run=True)
        missing = [w for w in report.warnings
                   if re.search(r"no (baseline|post-intervention) table", w)]
        self.assertTrue(any('"Hedgerows Baseline"' in w for w in missing))
        self.assertTrue(any('"Individual Trees Baseline"' in w
                            for w in missing))
        self.assertFalse(any('"Area Habitats Baseline"' in w
                             for w in missing))

    def test_command_line_explains_the_refusal(self):
        result = support.run_python(
            support.PACKAGE_DIR / "new_to_old.py", self.old,
            "-o", self.tmp / "cli")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("earlier version", result.stderr + result.stdout)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
