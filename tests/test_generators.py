"""The two site generators and the drop-down check they end with.

The NSIP generator writes to a fixed folder beside itself. These tests run it
in a child process with that folder pointed at a temporary one, and build a
small section of the route only: the whole corridor is about 100 MB.
"""

import filecmp
import shutil
import unittest
import zipfile

from tests import support

# support puts the converter modules and the NSIP generator on sys.path.
import gpkg_common

# A 5% section builds in about a second, with every layer populated.
NSIP_FRACTION = "0.05"
NSIP_SECTION = "site-5pc"
# Below about 4% the route is shorter than the canal the generator draws
# beside it (see test_a_short_section_builds_or_says_why).
NSIP_SHORT_FRACTION = "0.02"
NSIP_LAYERS = ("Area Habitats Baseline", "Area Habitats Post-Intervention",
               "Hedgerows Baseline", "Watercourses Baseline",
               "Individual Trees Baseline", "Red Line Boundary")
ALL_VALUES_OFFERED = "every drop-down value is one the template offers"

SITE_HABITATS = 12
SITE_HEDGEROWS = 2
SITE_TREES = 5
SITE_AREA_HA = 3.0
SITE_ARGS = ("--habitats", str(SITE_HABITATS), "--hedgerows",
             str(SITE_HEDGEROWS), "--trees", str(SITE_TREES), "--area-ha",
             str(SITE_AREA_HA), "--landscape", "arable", "--scheme", "solar")
SQ_M_PER_HA = 10000
# generate_site.py promises the parcels tile the red line to 0.01 sq m.
TILING_TOLERANCE_SQ_M = 0.01
LEGACY_FOLDERS = ("legacy-ne-baseline", "legacy-ne-post-intervention")
LEGACY_GPKG = support.Path("Layers") / "Net Gain Habitat Mapping Layers.gpkg"
# The GeoPackages a generated site holds, relative to the site.
SITE_GPKGS = (
    support.Path(support.SERVICE_SITE_FOLDER) / support.SERVICE_GPKG_IN_SITE,
    *(support.Path(folder) / LEGACY_GPKG for folder in LEGACY_FOLDERS))
METRIC_NAME = "The_Statutory_Metric_Macro_Enabled_1.0.4.xlsm"
USAGE_ERROR = 2
BAD_VALUE = "Not a condition"


def run_nsip_generator(working_dir, fraction):
    """Run generate.py with its working copy moved into `working_dir`."""
    snippet = (
        "import sys\n"
        f"sys.path.insert(0, {str(support.NSIP_GENERATOR_DIR)!r})\n"
        "import generate\n"
        f"generate.WORKING_DIR = {str(working_dir)!r}\n"
        f"generate.main(['--fraction', {fraction!r}])\n")
    return support.run_python("-c", snippet)


def zip_contents(path):
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}




class NsipGeneratorTest(support.TempDirTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.result = run_nsip_generator(cls.tmp / "site", NSIP_FRACTION)
        cls.site = cls.tmp / NSIP_SECTION
        cls.gpkg = cls.site / support.SERVICE_GPKG_IN_SITE

    def test_builds_a_section_and_checks_every_value(self):
        self.assertEqual(0, self.result.returncode,
                         support.describe(self.result))
        self.assertIn(ALL_VALUES_OFFERED, self.result.stdout)

    def test_every_layer_is_populated(self):
        for table in NSIP_LAYERS:
            with self.subTest(table=table):
                self.assertTrue(support.read_rows(self.gpkg, table))

    def test_copies_the_template_project_and_lists(self):
        self.assertEqual(support.SERVICE_PROJECT.read_bytes(),
                         (self.site / support.SERVICE_PROJECT.name)
                         .read_bytes())
        comparison = filecmp.dircmp(
            support.SERVICE_TEMPLATE_DIR / support.CSV_REFERENCES,
            self.site / support.CSV_REFERENCES)
        self.assertEqual([], comparison.left_only + comparison.right_only
                         + comparison.diff_files)

    def test_same_section_gives_the_same_bytes(self):
        again = run_nsip_generator(self.tmp / "again" / "site", NSIP_FRACTION)
        self.assertEqual(0, again.returncode, support.describe(again))
        copy = self.tmp / "again" / NSIP_SECTION / support.SERVICE_GPKG_IN_SITE
        self.assertEqual(self.gpkg.read_bytes(), copy.read_bytes())

    def test_dropdown_check_passes_on_the_section(self):
        result = support.run_python(support.DROPDOWN_CHECK, self.site)
        self.assertEqual(0, result.returncode, support.describe(result))
        self.assertIn(ALL_VALUES_OFFERED, result.stdout)

    def test_dropdown_check_names_a_value_no_list_offers(self):
        site = self.tmp / "bad-value"
        shutil.copytree(self.site, site)
        gpkg = site / support.SERVICE_GPKG_IN_SITE
        ref = support.read_rows(gpkg, "Area Habitats Baseline")[0]
        support.update(gpkg, "Area Habitats Baseline",
                       {"Baseline Condition": BAD_VALUE},
                       "Habitat Ref", ref["Habitat Ref"])
        result = support.run_python(support.DROPDOWN_CHECK, site)
        self.assertEqual(1, result.returncode, support.describe(result))
        self.assertIn("Area Habitats Baseline / Baseline Condition",
                      result.stdout)
        self.assertIn(repr(BAD_VALUE), result.stdout)

    # BUG: --fraction accepts any value above 0, but below about 0.04 the
    # run dies with an IndexError traceback. corridor_linear.build_watercourses
    # (scale-test-nsip/generator/corridor_linear.py:224-229) always draws the
    # four canal stretches from station int(stations * 0.155) to 43 stations
    # beyond it, without clipping them to the route, so a short section asks
    # corridor_mesh.node (corridor_mesh.py:214) for stations that do not
    # exist. generate.py should build the section or refuse the fraction.
    @unittest.expectedFailure
    def test_a_short_section_builds_or_says_why(self):
        result = run_nsip_generator(self.tmp / "short" / "site",
                                    NSIP_SHORT_FRACTION)
        self.assertNotIn("Traceback", result.stderr)


class SiteGeneratorTest(support.TempDirTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.first = support.generate_site(cls.tmp / "first", *SITE_ARGS)
        cls.second = support.generate_site(cls.tmp / "second", *SITE_ARGS)
        cls.other_seed = support.generate_site(
            cls.tmp / "other-seed", *SITE_ARGS, "--seed", "7")
        cls.gpkg = support.site_gpkg(cls.first)

    def test_same_inputs_give_the_same_geopackages(self):
        for relative in SITE_GPKGS:
            with self.subTest(file=str(relative)):
                self.assertEqual((self.first / relative).read_bytes(),
                                 (self.second / relative).read_bytes())

    def test_same_inputs_give_the_same_metric_contents(self):
        """The zip dates differ between runs; the parts inside do not."""
        self.assertEqual(zip_contents(self.first / METRIC_NAME),
                         zip_contents(self.second / METRIC_NAME))

    def test_another_seed_gives_another_site(self):
        relative = SITE_GPKGS[0]
        self.assertNotEqual((self.first / relative).read_bytes(),
                            (self.other_seed / relative).read_bytes())

    def test_site_has_what_was_asked_for(self):
        counts = {
            "Area Habitats Baseline": SITE_HABITATS,
            "Hedgerows Baseline": SITE_HEDGEROWS,
            "Individual Trees Baseline": SITE_TREES,
        }
        for table, expected in counts.items():
            with self.subTest(table=table):
                self.assertEqual(expected,
                                 len(support.read_rows(self.gpkg, table)))

    def test_parcels_tile_the_red_line(self):
        redline = support.read_rows(self.gpkg, "Red Line Boundary")
        parcels = support.read_rows(self.gpkg, "Area Habitats Baseline")
        redline_area = sum(gpkg_common.polygon_blob_area_sqm(row["geom"])
                           for row in redline)
        parcel_area = sum(gpkg_common.polygon_blob_area_sqm(row["geom"])
                          for row in parcels)
        self.assertAlmostEqual(SITE_AREA_HA * SQ_M_PER_HA, redline_area,
                               delta=TILING_TOLERANCE_SQ_M)
        self.assertAlmostEqual(redline_area, parcel_area,
                               delta=TILING_TOLERANCE_SQ_M)

    def test_area_column_is_hectares(self):
        for row in support.read_rows(self.gpkg, "Area Habitats Baseline"):
            measured = gpkg_common.polygon_blob_area_sqm(row["geom"])
            with self.subTest(ref=row["Habitat Ref"]):
                self.assertAlmostEqual(measured / SQ_M_PER_HA, row["Area"],
                                       delta=TILING_TOLERANCE_SQ_M
                                       / SQ_M_PER_HA)

    def test_every_baseline_significance_is_low(self):
        for row in support.read_rows(self.gpkg, "Area Habitats Baseline"):
            with self.subTest(ref=row["Habitat Ref"]):
                self.assertEqual("Low",
                                 row["Baseline Strategic Significance"])

    def test_writes_both_legacy_templates_and_the_metric(self):
        for folder in LEGACY_FOLDERS:
            with self.subTest(folder=folder):
                self.assertTrue((self.first / folder / LEGACY_GPKG).is_file())
        self.assertTrue(zipfile.is_zipfile(self.first / METRIC_NAME))

    def test_refuses_inputs_out_of_range(self):
        result = support.run_python(support.SITE_GENERATOR, "--out",
                                    self.tmp / "refused", "--habitats", "51")
        self.assertEqual(USAGE_ERROR, result.returncode)
        self.assertFalse((self.tmp / "refused").exists())

    # BUG: dropdown_check.check_site (scale-test-nsip/generator/
    # dropdown_check.py:330) opens the GeoPackage as f"file:{gpkg}?mode=ro".
    # SQLite reads everything after a `#` as a URI fragment, so a site folder
    # named "Site #3" opens a database that is not there and fails with
    # "no such table: Area Habitats Baseline". gpkg_common.read_only_uri
    # exists to avoid exactly this. The site generator runs the same check,
    # so it fails on such a folder too.
    @unittest.expectedFailure
    def test_builds_into_a_folder_whose_name_has_a_hash(self):
        result = support.run_python(
            support.SITE_GENERATOR, "--out", self.tmp / "Site #3",
            "--habitats", "3", "--no-legacy", "--no-metric")
        self.assertEqual(0, result.returncode, support.describe(result))


if __name__ == "__main__":
    unittest.main()
