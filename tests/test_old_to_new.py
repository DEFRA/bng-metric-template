"""Convert from legacy: a Natural England pair into the BNG Service template.

The legacy pair is made by converting a generated site with new_to_old, so
the round trip can be checked against the site it came from. A copy of the
pair then gets the values the template cannot hold (Medium significance,
High on a Retained row, an off-site spatial risk, a blank distinctiveness,
a text advance value), to check what the converter does with each.
"""

import unittest

from tests import support

# support puts the converter modules on sys.path.
import gpkg_common
import new_to_old
import old_to_new
import reference_lists as rl

SITE_ARGS = ("--habitats", "10", "--area-ha", "4", "--hedgerows", "2",
             "--trees", "6", "--seed", "5", "--no-legacy", "--no-metric")
BASELINE_FILE = f"{new_to_old.LEGACY_LAYERS_STEM} - Baseline.gpkg"
PI_FILE = f"{new_to_old.LEGACY_LAYERS_STEM} - Post-intervention.gpkg"
SQ_M_PER_HA = 10000
# Legacy stores whole square metres and whole metres.
AREA_TOLERANCE_HA = 0.5 / SQ_M_PER_HA
LENGTH_TOLERANCE_M = 0.5

REF = "Habitat Ref"
PARENT_REF = "Parent Ref"
PARCEL_REF = old_to_new.PARCEL_REF
RETENTION = "Retention Category"
SPATIAL_RISK = "Spatial risk category"
ADVANCE = "Habitat created in advance/years"
DELAY = "Delay in starting habitat creation/years"
MUTATED_COPY = "mutated"
VERSION_FIELD = "version"
BASELINE_SIGNIFICANCE = rl.BASELINE_SIGNIFICANCE
PROPOSED_SIGNIFICANCE = rl.PROPOSED_SIGNIFICANCE
OFF_SITE_RISK = "Compensation inside LPA boundary or NCA of impact site"
BLANKET_BOG = ("Wetland", "Blanket bog")

AREA_BASELINE = old_to_new.AREA_HABITATS_BASELINE
AREA_PI = "Area Habitats Post-Intervention"
BASELINE_TABLES = (old_to_new.AREA_HABITATS_BASELINE, "Hedgerows Baseline",
                   "Watercourses Baseline", old_to_new.INDIVIDUAL_TREES_BASELINE)
PI_TABLES = ("Area Habitats Post-Intervention", old_to_new.HEDGEROWS_POST_INTERVENTION,
             "Watercourses Post-Intervention",
             old_to_new.INDIVIDUAL_TREES_POST_INTERVENTION)
LAYER_KEYS = {
    "Area Habitats": old_to_new.AREAS,
    old_to_new.HEDGEROWS: old_to_new.HEDGEROWS_KEY,
    "Watercourses": old_to_new.WATERCOURSES_KEY,
    "Individual Trees": old_to_new.TREES_KEY,
}
CONDITION_COLUMNS = ("Baseline Condition", old_to_new.PROPOSED_CONDITION)
ROUND_TRIP_TABLES = BASELINE_TABLES + PI_TABLES
ROUND_TRIP_FIELDS = {
    AREA_BASELINE: (old_to_new.BASELINE_HABITAT_TYPE, "Baseline Condition",
                    old_to_new.BASELINE_DISTINCTIVENESS, BASELINE_SIGNIFICANCE),
    AREA_PI: (PARENT_REF, RETENTION, "Proposed Habitat Type",
              old_to_new.PROPOSED_CONDITION, PROPOSED_SIGNIFICANCE, SPATIAL_RISK),
    old_to_new.HEDGEROWS_POST_INTERVENTION: (PARENT_REF, RETENTION,
                                    "Proposed Hedge Type",
                                    PROPOSED_SIGNIFICANCE),
    old_to_new.INDIVIDUAL_TREES_POST_INTERVENTION: (PARENT_REF, RETENTION, "Category",
                                           old_to_new.PROPOSED_CONDITION,
                                           PROPOSED_SIGNIFICANCE),
}


def layer_key(table):
    """The converter's key for a template table: "areas", "trees"..."""
    return next(key for prefix, key in LAYER_KEYS.items()
                if table.startswith(prefix))


def first(rows, predicate):
    return next(row for row in rows if predicate(row))


def legacy_pair(service_gpkg, folder):
    new_to_old.convert(service_gpkg, folder, carry_lineage=True,
                       dry_run=False)
    return folder / BASELINE_FILE, folder / PI_FILE


def template_copy(folder, name="target.gpkg"):
    return support.copy_to(support.SERVICE_GPKG, folder, name)


def fill(baseline, pi, into, force=False):
    return old_to_new.convert(str(baseline), str(pi), None, str(into), force,
                              dry_run=False)


class Mutations:
    """The legacy rows changed for the test, by their reference."""

    def __init__(self, baseline, pi):
        habitats = support.read_rows(baseline, old_to_new.HABITATS)
        pi_habitats = support.read_rows(pi, old_to_new.HABITATS)
        self.high_baseline = habitats[0][PARCEL_REF]
        self.blank_distinctiveness = habitats[1][PARCEL_REF]
        self.bog = habitats[2][PARCEL_REF]
        self.medium = first(pi_habitats,
                            lambda r: r[RETENTION] == "Created")[PARCEL_REF]
        self.retained_high = first(
            pi_habitats, lambda r: r[RETENTION] == old_to_new.RETAINED)[PARCEL_REF]
        self.off_site = first(
            pi_habitats, lambda r: r[PARCEL_REF] != self.medium)[PARCEL_REF]
        hedges = support.read_rows(pi, old_to_new.HEDGEROWS)
        self.text_timing = hedges[0][PARCEL_REF]
        self.many_trees = support.read_rows(baseline, "Urban Trees")[0][
            old_to_new.TREE_REF]
        self.apply(baseline, pi)

    def apply(self, baseline, pi):
        support.update(baseline, old_to_new.HABITATS,
                       {BASELINE_SIGNIFICANCE: rl.NE_SIGNIFICANCE_HIGH},
                       PARCEL_REF, self.high_baseline)
        support.update(baseline, old_to_new.HABITATS,
                       {old_to_new.BASELINE_DISTINCTIVENESS: None},
                       PARCEL_REF, self.blank_distinctiveness)
        support.update(baseline, old_to_new.HABITATS,
                       {"Baseline Broad Habitat Type": BLANKET_BOG[0],
                        old_to_new.BASELINE_HABITAT_TYPE: BLANKET_BOG[1]},
                       PARCEL_REF, self.bog)
        support.update(pi, old_to_new.HABITATS,
                       {PROPOSED_SIGNIFICANCE: rl.NE_SIGNIFICANCE_MEDIUM},
                       PARCEL_REF, self.medium)
        support.update(pi, old_to_new.HABITATS,
                       {PROPOSED_SIGNIFICANCE: rl.NE_SIGNIFICANCE_HIGH},
                       PARCEL_REF, self.retained_high)
        support.update(pi, old_to_new.HABITATS, {SPATIAL_RISK: OFF_SITE_RISK},
                       PARCEL_REF, self.off_site)
        support.update(pi, old_to_new.HEDGEROWS, {
            ADVANCE: "Habitat already in target condition",
            DELAY: "5",
        }, PARCEL_REF, self.text_timing)
        support.update(baseline, "Urban Trees", {"Count": 3},
                       old_to_new.TREE_REF, self.many_trees)


class OldToNewTest(support.TempDirTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        site = support.generate_site(cls.tmp / "site", *SITE_ARGS)
        cls.source = support.site_gpkg(site)
        cls.baseline, cls.pi = legacy_pair(cls.source, cls.tmp / "legacy")
        cls.base_copy = support.copy_to(cls.baseline, cls.tmp / MUTATED_COPY)
        cls.pi_copy = support.copy_to(cls.pi, cls.tmp / MUTATED_COPY)
        cls.changed = Mutations(cls.base_copy, cls.pi_copy)
        cls.target = template_copy(cls.tmp / MUTATED_COPY)
        cls.report = fill(cls.base_copy, cls.pi_copy, cls.target)

    def rows(self, table):
        return support.read_rows(self.target, table)

    def row(self, table, ref):
        return first(self.rows(table), lambda r: r[REF] == ref)

    def warnings_mentioning(self, *texts):
        return [w for w in self.report.warnings
                if all(text in w for text in texts)]

    def test_a_point_of_several_trees_becomes_one_tree_with_a_warning(self):
        rows = [row for row in self.rows(old_to_new.INDIVIDUAL_TREES_BASELINE)
                if row[REF] == self.changed.many_trees]
        self.assertEqual(1, len(rows))
        self.assertNotIn("Count", rows[0])
        self.assertEqual(1, len(self.warnings_mentioning(
            self.changed.many_trees, "Count above 1")))

    def test_every_baseline_row_is_low(self):
        for table in BASELINE_TABLES:
            for row in self.rows(table):
                with self.subTest(table=table, ref=row[REF]):
                    self.assertEqual(rl.SIGNIFICANCE_LOW,
                                     row[BASELINE_SIGNIFICANCE])
        self.assertTrue(self.warnings_mentioning(self.changed.high_baseline,
                                                 "Baseline Strategic"))

    def test_medium_significance_is_left_blank_with_a_warning(self):
        row = self.row(AREA_PI, self.changed.medium)
        self.assertIsNone(row[PROPOSED_SIGNIFICANCE])
        self.assertTrue(self.warnings_mentioning(rl.NE_SIGNIFICANCE_MEDIUM,
                                                 self.changed.medium))

    def test_retained_rows_are_low(self):
        for table in PI_TABLES:
            for row in self.rows(table):
                if row[RETENTION] != old_to_new.RETAINED:
                    continue
                with self.subTest(table=table, ref=row[REF]):
                    self.assertEqual(rl.SIGNIFICANCE_LOW,
                                     row[PROPOSED_SIGNIFICANCE])
        self.assertTrue(self.warnings_mentioning(
            old_to_new.RETAINED, self.changed.retained_high))

    def test_proposed_significance_is_low_high_or_blank(self):
        for table in PI_TABLES:
            for row in self.rows(table):
                with self.subTest(table=table, ref=row[REF]):
                    self.assertIn(row[PROPOSED_SIGNIFICANCE],
                                  (rl.SIGNIFICANCE_LOW, rl.SIGNIFICANCE_HIGH,
                                   None))

    def test_baseline_significance_on_pi_rows_follows_the_baseline_part(self):
        found = set()
        for table in PI_TABLES:
            key = layer_key(table)
            for row in self.rows(table):
                expected = (rl.SIGNIFICANCE_LOW
                            if rl.has_baseline_part(key, row) else None)
                found.add(row[BASELINE_SIGNIFICANCE])
                with self.subTest(table=table, ref=row[REF]):
                    self.assertEqual(expected, row[BASELINE_SIGNIFICANCE])
        # The site plants trees and a hedge, which have no baseline part.
        self.assertEqual({rl.SIGNIFICANCE_LOW, None}, found)

    def test_spatial_risk_is_not_applicable(self):
        for table in PI_TABLES:
            for row in self.rows(table):
                with self.subTest(table=table, ref=row[REF]):
                    self.assertEqual(rl.NOT_APPLICABLE, row[SPATIAL_RISK])
        self.assertTrue(self.warnings_mentioning(SPATIAL_RISK,
                                                 self.changed.off_site))

    def test_a_text_advance_or_delay_is_left_blank(self):
        row = self.row(old_to_new.HEDGEROWS_POST_INTERVENTION,
                       self.changed.text_timing)
        self.assertIsNone(row[ADVANCE])
        self.assertEqual("5", row[DELAY])
        self.assertTrue(self.warnings_mentioning(
            self.changed.text_timing, "left blank"))
        self.assertFalse(self.warnings_mentioning(
            self.changed.text_timing, "both"))

    def test_blank_distinctiveness_is_filled_from_the_list(self):
        row = self.row(AREA_BASELINE, self.changed.blank_distinctiveness)
        lookup, _type = rl.DISTINCTIVENESS_LISTS[old_to_new.AREAS][
            old_to_new.BASELINE_DISTINCTIVENESS]
        self.assertEqual(lookup.only(row[old_to_new.BASELINE_HABITAT_TYPE]),
                         row[old_to_new.BASELINE_DISTINCTIVENESS])
        self.assertIsNotNone(row[old_to_new.BASELINE_DISTINCTIVENESS])

    def test_only_yes_habitat_is_irreplaceable(self):
        bog = self.row(AREA_BASELINE, self.changed.bog)
        self.assertEqual("Yes", bog[old_to_new.IRREPLACEABLE_COLUMN])

    def test_irreplaceable_is_filled_only_where_one_answer_is_allowed(self):
        for row in self.rows(AREA_BASELINE):
            answer = rl.IRREPLACEABLE_LIST.only(row[old_to_new.BASELINE_HABITAT_TYPE])
            with self.subTest(ref=row[REF]):
                self.assertEqual(answer, row[old_to_new.IRREPLACEABLE_COLUMN])

    def test_a_planted_tree_is_not_irreplaceable_and_an_existing_one_is_left(self):
        rows = self.rows(old_to_new.INDIVIDUAL_TREES_POST_INTERVENTION)
        self.assertTrue(rows)
        for row in rows:
            expected = "No" if row["Category"] == "Newly Planted" else None
            with self.subTest(ref=row[REF]):
                self.assertEqual(expected, row[old_to_new.IRREPLACEABLE_COLUMN])
        for row in self.rows(old_to_new.INDIVIDUAL_TREES_BASELINE):
            with self.subTest(ref=row[REF]):
                self.assertIsNone(row[old_to_new.IRREPLACEABLE_COLUMN])
        self.assertEqual(1, len(self.warnings_mentioning(
            "Irreplaceable Habitat is blank", "individual tree")))

    def test_list_numbers_are_taken_off(self):
        for table in BASELINE_TABLES + PI_TABLES:
            for row in self.rows(table):
                for column in CONDITION_COLUMNS + (RETENTION,):
                    value = row.get(column)
                    if not value:
                        continue
                    with self.subTest(table=table, ref=row[REF],
                                      column=column):
                        self.assertNotRegex(value,
                                            gpkg_common.NUMBERED_LABEL)

    def test_linked_rows_record_their_parent(self):
        uuids = {row[REF]: row["feature_uuid"]
                 for row in self.rows(AREA_BASELINE)}
        linked = [row for row in self.rows(AREA_PI) if row[PARENT_REF]]
        self.assertTrue(linked)
        for row in linked:
            with self.subTest(ref=row[REF]):
                self.assertEqual(uuids[row[PARENT_REF]], row["parent_uuid"])
                self.assertTrue(row["parent_geom"].startswith("POLYGON"))

    def test_refuses_a_template_that_already_holds_features(self):
        with self.assertRaisesRegex(ValueError, "already has"):
            fill(self.base_copy, self.pi_copy, self.target)

    def test_force_adds_to_a_used_template(self):
        target = support.copy_to(self.target, self.tmp / "forced")
        before = len(support.read_rows(target, AREA_BASELINE))
        fill(self.base_copy, self.pi_copy, target, force=True)
        self.assertEqual(2 * before,
                         len(support.read_rows(target, AREA_BASELINE)))

    def test_refuses_a_template_with_the_old_table_names(self):
        old = support.make_old_named_gpkg(self.tmp / "old-template.gpkg")
        with self.assertRaisesRegex(ValueError, old_to_new.AREA_HABITATS_BASELINE):
            fill(self.base_copy, self.pi_copy, old)

    def test_dry_run_writes_nothing(self):
        target = template_copy(self.tmp / "dry-run")
        before = target.read_bytes()
        old_to_new.convert(str(self.baseline), str(self.pi), None,
                           str(target), False, dry_run=True)
        self.assertEqual(before, target.read_bytes())

    def test_writes_a_new_file_without_into(self):
        out = self.tmp / "new-file"
        old_to_new.convert(str(self.baseline), str(self.pi), str(out), None,
                           False, dry_run=False)
        written = out / f"{self.baseline.stem} - Staged.gpkg"
        self.assertEqual(set(old_to_new.STAGED_LAYERS),
                         support.feature_tables(written))
        self.assertEqual(
            {"format": gpkg_common.FORMAT_NAME,
             VERSION_FIELD: gpkg_common.TEMPLATE_VERSION},
            support.template_version(written))

    def test_a_template_copy_keeps_its_version_and_is_not_warned_about(self):
        self.assertEqual(gpkg_common.TEMPLATE_VERSION,
                         support.template_version(self.target)[VERSION_FIELD])
        self.assertEqual([], self.warnings_mentioning(VERSION_FIELD))

    def test_an_intertidal_hard_structure_on_area_habitats_is_warned_about(self):
        folder = self.tmp / "intertidal"
        baseline = support.copy_to(self.baseline, folder)
        pi = support.copy_to(self.pi, folder)
        carried = {row[PARCEL_REF] for row in support.read_rows(pi, old_to_new.HABITATS)}
        ref = first(support.read_rows(baseline, old_to_new.HABITATS),
                    lambda r: r[PARCEL_REF] in carried)[PARCEL_REF]
        structure = {"Baseline Broad Habitat Type": "Intertidal hard structures",
                     old_to_new.BASELINE_HABITAT_TYPE: "Artificial hard structures"}
        support.update(baseline, old_to_new.HABITATS, structure, PARCEL_REF, ref)
        support.update(pi, old_to_new.HABITATS, structure, PARCEL_REF, ref)
        report = fill(baseline, pi, template_copy(folder))
        warnings = [w for w in report.warnings
                    if "Vertical Area Habitats layers" in w]
        self.assertEqual(1, len(warnings))
        self.assertIn(ref, warnings[0])
        # The ref is on both stages, and is named once.
        self.assertTrue(warnings[0].startswith("1 area habitat row(s)"),
                        warnings[0])

    def test_a_target_without_a_version_is_warned_about_and_left_alone(self):
        target = template_copy(self.tmp / "no-version")
        conn = support.open_for_writing(target)
        try:
            conn.execute("DELETE FROM gpkg_metadata")
            conn.execute("DELETE FROM gpkg_metadata_reference")
            conn.commit()
        finally:
            conn.close()
        report = fill(self.base_copy, self.pi_copy, target)
        self.assertEqual(1, len([w for w in report.warnings
                                 if "does not record its version" in w]))
        self.assertIsNone(support.template_version(target))


class RoundTripTest(support.TempDirTestCase):
    """BNG Service -> legacy -> BNG Service keeps what legacy can carry."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        site = support.generate_site(cls.tmp / "site", *SITE_ARGS)
        cls.source = support.copy_to(support.site_gpkg(site), cls.tmp,
                                     "source.gpkg")
        support.comment_every_row(cls.source)
        cls.enhanced_tree = support.enhance_a_tree(cls.source)
        baseline, pi = legacy_pair(cls.source, cls.tmp / "legacy")
        cls.target = template_copy(cls.tmp / "back")
        fill(baseline, pi, cls.target)

    def test_comments_survive_without_the_lineage_breadcrumbs(self):
        for table in ROUND_TRIP_TABLES:
            before, after = self.both(table)
            for ref, row in before.items():
                with self.subTest(table=table, ref=ref):
                    self.assertEqual(row[old_to_new.COMMENT], after[ref][old_to_new.COMMENT])

    def test_an_older_template_without_comments_is_warned_about(self):
        """A template from before post-intervention layers had a Comment."""
        older = template_copy(self.tmp / "older")
        conn = support.open_for_writing(older)
        try:
            for table in PI_TABLES + ("Vertical Area Habitats "
                                      "Post-Intervention",):
                conn.execute(f'ALTER TABLE "{table}" DROP COLUMN "Comment"')
            conn.commit()
        finally:
            conn.close()
        baseline, pi = legacy_pair(self.source, self.tmp / "legacy-older")
        report = fill(baseline, pi, older)
        dropped = [w for w in report.warnings
                   if "comment(s) were not written" in w]
        self.assertEqual(1, len(dropped))
        for table in PI_TABLES:
            if not support.read_rows(self.source, table):
                continue
            with self.subTest(table=table):
                self.assertIn(table, dropped[0])

    def test_an_enhanced_tree_survives(self):
        before, after = self.both(old_to_new.INDIVIDUAL_TREES_POST_INTERVENTION)
        self.assertEqual("Enhanced", after[self.enhanced_tree][RETENTION])
        self.assertEqual(before[self.enhanced_tree][old_to_new.PROPOSED_CONDITION],
                         after[self.enhanced_tree][old_to_new.PROPOSED_CONDITION])

    def both(self, table):
        return (support.by_ref(support.read_rows(self.source, table), REF),
                support.by_ref(support.read_rows(self.target, table), REF))

    def test_every_table_keeps_its_references(self):
        for table in ROUND_TRIP_TABLES:
            before, after = self.both(table)
            with self.subTest(table=table):
                self.assertEqual(set(before), set(after))

    def test_key_fields_survive(self):
        for table, fields in ROUND_TRIP_FIELDS.items():
            before, after = self.both(table)
            for ref, row in before.items():
                for field in fields:
                    with self.subTest(table=table, ref=ref, field=field):
                        self.assertEqual(row[field], after[ref][field])

    def test_areas_survive_to_the_square_metre(self):
        for table in (AREA_BASELINE, AREA_PI):
            before, after = self.both(table)
            for ref, row in before.items():
                with self.subTest(table=table, ref=ref):
                    self.assertAlmostEqual(row["Area"], after[ref]["Area"],
                                           delta=AREA_TOLERANCE_HA)

    def test_hedgerow_lengths_survive_to_the_metre(self):
        before, after = self.both(old_to_new.HEDGEROWS_POST_INTERVENTION)
        for ref, row in before.items():
            with self.subTest(ref=ref):
                self.assertAlmostEqual(row["Length"], after[ref]["Length"],
                                       delta=LENGTH_TOLERANCE_M)


class TimingTextTest(unittest.TestCase):
    """A legacy text advance or delay is blank, and is not a year above 0."""

    def test_text_is_blanked_before_both_above_zero_is_judged(self):
        post = {key: [] for key in old_to_new.LEGACY_REFS}
        post[old_to_new.HEDGEROWS_KEY] = [{
            old_to_new.PARCEL_REF: "H-1",
            ADVANCE: "Habitat already in target condition",
            DELAY: "0",
        }]
        post[old_to_new.WATERCOURSES_KEY] = [
            {old_to_new.PARCEL_REF: "W-1", ADVANCE: "N/A", DELAY: "12"},
            {old_to_new.PARCEL_REF: "W-2", ADVANCE: "N/A", DELAY: "N/A"},
            {old_to_new.PARCEL_REF: "W-3", ADVANCE: "4", DELAY: "6"},
            {old_to_new.PARCEL_REF: "W-4", ADVANCE: "30+", DELAY: None},
        ]
        post[old_to_new.TREES_KEY] = [{
            old_to_new.TREE_REF: "T-1",
            "Habitat Created/Enhanced in advance/years": "N/A",
            "Delay in starting habitat creation/enhancement in years": "1",
        }]
        report = old_to_new.Report()
        old_to_new._post_timing(post, report)

        self.assertIsNone(post[old_to_new.HEDGEROWS_KEY][0][ADVANCE])
        self.assertEqual("0", post[old_to_new.HEDGEROWS_KEY][0][DELAY])
        self.assertIsNone(post[old_to_new.WATERCOURSES_KEY][0][ADVANCE])
        self.assertEqual("12", post[old_to_new.WATERCOURSES_KEY][0][DELAY])
        self.assertIsNone(post[old_to_new.WATERCOURSES_KEY][1][ADVANCE])
        self.assertIsNone(post[old_to_new.WATERCOURSES_KEY][1][DELAY])
        self.assertEqual("4", post[old_to_new.WATERCOURSES_KEY][2][ADVANCE])
        self.assertEqual("6", post[old_to_new.WATERCOURSES_KEY][2][DELAY])
        self.assertEqual("30+", post[old_to_new.WATERCOURSES_KEY][3][ADVANCE])
        self.assertIsNone(post[old_to_new.TREES_KEY][0][
            "Habitat Created/Enhanced in advance/years"])
        self.assertEqual("1", post[old_to_new.TREES_KEY][0][
            "Delay in starting habitat creation/enhancement in years"])

        blanked = [w for w in report.warnings if "left blank" in w]
        named = " ".join(blanked)
        self.assertIn("H-1", named)
        self.assertIn("W-1", named)
        self.assertIn("W-2", named)
        self.assertIn("T-1", named)
        self.assertNotIn("W-3", named)
        self.assertNotIn("W-4", named)
        both = [w for w in report.warnings if "above 0" in w]
        self.assertEqual(1, len(both))
        self.assertIn("W-3", both[0])
        self.assertNotIn("W-1", both[0])
        self.assertNotIn("H-1", both[0])


class BaselineCommentTest(unittest.TestCase):
    """A breadcrumb typed or pasted onto a legacy baseline row is lineage,
    not the surveyor's comment, so it is taken out there too."""

    def test_each_baseline_builder_strips_the_breadcrumbs(self):
        report = old_to_new.Report()
        note = "Grazed by sheep [parent=H-1] [pi=H-1]"
        built = {
            old_to_new.AREAS: old_to_new.build_area_baseline(
                [{old_to_new.PARCEL_REF: "A-1", old_to_new.COMMENT: note}], report),
            old_to_new.HEDGEROWS_KEY: old_to_new.build_linear_baseline(
                [{old_to_new.PARCEL_REF: "H-1", "Comments": note}], {}, report,
                old_to_new.HEDGEROWS),
            old_to_new.TREES_KEY: old_to_new.build_tree_baseline(
                [{old_to_new.TREE_REF: "T-1", old_to_new.COMMENT: note}], report),
        }
        for kind, (rows, _index) in built.items():
            with self.subTest(kind=kind):
                self.assertEqual("Grazed by sheep", rows[0][1][old_to_new.COMMENT])


if __name__ == "__main__":
    unittest.main()
