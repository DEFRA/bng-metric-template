"""The drop-down lists the converter reads, and how it reads them."""

import csv
import unittest
from collections import defaultdict

from tests import support

import gpkg_common
import reference_lists as rl

# The Strategic Significance lists of the BNG Service template: Low or High.
SERVICE_SIGNIFICANCE_LISTS = (
    "Habitats/Habitats Strategic Significance.csv",
    "Hedgerows/Hedgerow Strategic Significance.csv",
    "Watercourses/Watercourse Strategic Significance.csv",
    "Watercourses/Watercourse Proposed Strategic Significance.csv",
    "Individual trees/Individual tree Strategic Significance - pre.csv",
    "Individual trees/Individual tree Strategic Significance - post.csv",
)
LOW_HIGH = ["Low", "High"]
ONLY_YES_IRREPLACEABLE = {"Blanket bog", "Coastal sand dunes",
                          "Limestone pavement"}
GRASSLAND = "Modified grassland"
DITCHES = "Ditches"
TO_BE_CREATED = "To be created"


def csv_rows(template, relative):
    folder = support.TEMPLATES_DIR / template / support.CSV_REFERENCES
    with open(folder / relative, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


class ListFilesTest(unittest.TestCase):

    def test_every_list_the_converter_reads_exists_in_its_template(self):
        files = rl.reference_files()
        self.assertTrue(files)
        for template, relative in files:
            with self.subTest(template=template, list=relative):
                path = (support.TEMPLATES_DIR / template
                        / support.CSV_REFERENCES / relative)
                self.assertTrue(path.is_file(), path)

    def test_every_numbered_list_is_read_from_both_templates(self):
        files = set(rl.reference_files())
        for label_list in rl.LABEL_LISTS:
            for template in rl.TEMPLATES:
                with self.subTest(template=template, list=label_list.path):
                    self.assertIn((template, label_list.path), files)

    def test_repository_run_reads_the_lists_in_place(self):
        self.assertFalse((support.PACKAGE_DIR / rl.BUNDLED_DIR).exists(),
                         "a bundled copy in the source tree would shadow "
                         "the templates' own lists")
        for template in rl.TEMPLATES:
            with self.subTest(template=template):
                expected = (support.TEMPLATES_DIR / template
                            / support.CSV_REFERENCES)
                self.assertEqual(
                    expected.resolve(),
                    support.Path(rl.list_folder(template)).resolve())

    def test_unknown_template_names_where_it_looked(self):
        with self.assertRaisesRegex(ValueError, "Cannot find"):
            rl.list_folder("no-such-template")


class SignificanceListsTest(unittest.TestCase):

    def test_service_significance_lists_hold_low_then_high(self):
        for relative in SERVICE_SIGNIFICANCE_LISTS:
            with self.subTest(list=relative):
                rows = csv_rows(rl.SERVICE_TEMPLATE, relative)
                self.assertEqual(LOW_HIGH, [row["Value"] for row in rows])

    def test_legacy_significance_list_holds_the_three_wordings(self):
        rows = csv_rows(rl.LEGACY_TEMPLATE,
                        "Habitats/Habitats Strategic Significance.csv")
        self.assertEqual(
            {rl.NE_SIGNIFICANCE_LOW, rl.NE_SIGNIFICANCE_MEDIUM,
             rl.NE_SIGNIFICANCE_HIGH},
            {row["Value"] for row in rows})

    def test_legacy_tree_list_uses_the_tree_wording(self):
        rows = csv_rows(
            rl.LEGACY_TEMPLATE,
            "Individual trees/Individual tree Strategic Significance - "
            "post.csv")
        values = {row["Significance"] for row in rows}
        self.assertIn(rl.NE_SIGNIFICANCE_HIGH_TREES, values)
        self.assertNotIn(rl.NE_SIGNIFICANCE_HIGH, values)


class LabelFormTest(unittest.TestCase):

    def test_service_lists_store_plain_labels(self):
        for label_list in rl.LABEL_LISTS:
            with self.subTest(list=label_list.path):
                rows = csv_rows(rl.SERVICE_TEMPLATE, label_list.path)
                numbered = [row[label_list.service_key] for row in rows
                            if gpkg_common.NUMBERED_LABEL.match(
                                row[label_list.service_key] or "")]
                self.assertEqual([], numbered)

    def test_legacy_condition_list_stores_numbered_labels(self):
        rows = csv_rows(rl.LEGACY_TEMPLATE, rl.AREA_CONDITION.path)
        self.assertTrue(all(gpkg_common.NUMBERED_LABEL.match(row["Label"])
                            for row in rows if row["Label"]))

    def test_legacy_form_adds_the_number_for_the_context(self):
        self.assertEqual(
            "4. Fairly Poor",
            rl.AREA_CONDITION.legacy_form("Fairly Poor", GRASSLAND))
        self.assertEqual(
            "2. Retained",
            rl.WATERCOURSE_RETENTION.legacy_form("Retained", DITCHES))

    def test_legacy_form_leaves_a_numbered_value_alone(self):
        self.assertEqual(
            "4. Fairly Poor",
            rl.AREA_CONDITION.legacy_form("4. Fairly Poor", GRASSLAND))

    def test_created_on_an_existing_watercourse_takes_the_gap_number(self):
        self.assertEqual(
            "4. Created",
            rl.WATERCOURSE_RETENTION.legacy_form("Created", DITCHES))

    def test_service_form_strips_the_number(self):
        self.assertEqual("Fairly Poor",
                         rl.AREA_CONDITION.service_form("4. Fairly Poor"))
        self.assertEqual("Retained",
                         rl.WATERCOURSE_RETENTION.service_form("2. Retained"))

    def test_service_form_leaves_unknown_and_blank_values_alone(self):
        self.assertEqual("7. Nonsense",
                         rl.AREA_CONDITION.service_form("7. Nonsense"))
        self.assertIsNone(rl.AREA_CONDITION.service_form(None))

    def test_tree_proposed_condition_stays_unnumbered(self):
        rows = csv_rows(rl.LEGACY_TEMPLATE, rl.TREE_PROPOSED_CONDITION.path)
        new_values = {row["New"] for row in rows if row["New"]}
        self.assertTrue(new_values)
        self.assertFalse(any(gpkg_common.NUMBERED_LABEL.match(value)
                             for value in new_values))


class SignificanceMappingTest(unittest.TestCase):

    def legacy(self, key, column, **row):
        return rl.legacy_significance(key, column, row)

    def test_low_and_high_take_the_natural_england_wording(self):
        column = rl.PROPOSED_SIGNIFICANCE
        self.assertEqual(rl.NE_SIGNIFICANCE_LOW,
                         self.legacy("areas", column, **{column: "Low"}))
        self.assertEqual(rl.NE_SIGNIFICANCE_HIGH,
                         self.legacy("areas", column, **{column: "High"}))

    def test_high_on_a_tree_takes_the_tree_wording(self):
        column = rl.PROPOSED_SIGNIFICANCE
        self.assertEqual(rl.NE_SIGNIFICANCE_HIGH_TREES,
                         self.legacy("trees", column, **{column: "High"}))

    def test_blank_on_a_created_hedgerow_is_not_applicable(self):
        column = rl.BASELINE_SIGNIFICANCE
        row = {column: None, "Baseline Hedge Type": TO_BE_CREATED}
        self.assertEqual(rl.NOT_APPLICABLE,
                         self.legacy("hedgerows", column, **row))

    def test_blank_on_a_newly_planted_tree_is_not_applicable(self):
        column = rl.BASELINE_SIGNIFICANCE
        row = {column: None, "Category": rl.TREE_NEWLY_PLANTED}
        self.assertEqual(rl.NOT_APPLICABLE,
                         self.legacy("trees", column, **row))

    def test_blank_on_an_area_habitat_stays_blank(self):
        column = rl.PROPOSED_SIGNIFICANCE
        self.assertIsNone(self.legacy("areas", column, **{column: None}))

    def test_wordings_read_back_as_low_and_high(self):
        expected = {
            rl.NE_SIGNIFICANCE_LOW: ("Low", True),
            rl.NE_SIGNIFICANCE_HIGH: ("High", True),
            rl.NE_SIGNIFICANCE_HIGH_TREES: ("High", True),
            rl.NE_SIGNIFICANCE_MEDIUM: (None, True),
            rl.NOT_APPLICABLE: (None, True),
            None: (None, True),
            "Something else": (None, False),
        }
        for wording, answer in expected.items():
            with self.subTest(wording=wording):
                self.assertEqual(answer, rl.service_significance(wording))


class TemplateFillTest(unittest.TestCase):

    def test_only_yes_habitats_are_the_three_irreplaceable_ones(self):
        answers = defaultdict(set)
        for row in csv_rows(rl.SERVICE_TEMPLATE,
                            rl.IRREPLACEABLE_LIST.path):
            answers[row["UKHAB"]].add(row["Irreplaceable"])
        only_yes = {habitat for habitat, values in answers.items()
                    if values == {"Yes"}}
        self.assertEqual(ONLY_YES_IRREPLACEABLE, only_yes)

    def test_blanks_are_filled_from_the_template_lists(self):
        rows = [
            {"Baseline Habitat Type": "Blanket bog",
             "Baseline Distinctiveness": None,
             "Irreplaceable Habitat": None},
            {"Baseline Habitat Type": GRASSLAND,
             "Baseline Distinctiveness": "",
             "Irreplaceable Habitat": None},
        ]
        rl.fill_template_values("areas", rows)
        self.assertEqual("Yes", rows[0]["Irreplaceable Habitat"])
        self.assertEqual("V.High", rows[0]["Baseline Distinctiveness"])
        self.assertEqual("No", rows[1]["Irreplaceable Habitat"])
        self.assertEqual("Low", rows[1]["Baseline Distinctiveness"])

    def test_a_value_already_there_is_kept(self):
        rows = [{"Baseline Habitat Type": GRASSLAND,
                 "Baseline Distinctiveness": "Kept"}]
        rl.fill_template_values("areas", rows)
        self.assertEqual("Kept", rows[0]["Baseline Distinctiveness"])


if __name__ == "__main__":
    unittest.main()
