"""
Processing algorithms wrapping the two converters.

The conversion logic lives in new_to_old.py / old_to_new.py, which are plain
Python and run equally well from a command line. These classes only translate
between the Processing dialog and those functions, and add the guards that only
make sense when running inside QGIS — chiefly, refusing to read a GeoPackage
whose edits are still sitting unsaved in the map.
"""

import os

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterFolderDestination,
    QgsProject,
    QgsVectorLayer,
)

from . import new_to_old, old_to_new, to_metric

GEOPACKAGE_FILTER = "GeoPackage (*.gpkg *.GPKG)"
# Natural England publishes the metric with macros and without. Both are
# accepted, and the filled copy keeps the form of the blank it came from.
METRIC_FILTER = "Statutory Metric workbook (*.xlsm *.xlsx *.XLSM *.XLSX)"
SOURCE_SEPARATOR = "|"


def _layer_file(layer):
    """The GeoPackage path behind a layer, or None."""
    source = layer.source() or ""
    path = source.split(SOURCE_SEPARATOR, 1)[0]
    return os.path.normpath(path) if path else None


def _same_file(left, right):
    """Whether two paths name the same file.

    samefile answers it properly when both exist. The fallback is for when one
    does not, and it folds case as well as separators: on Windows the same
    GeoPackage can reach us as C:\\Site\\x.gpkg from one place and
    c:/site/x.gpkg from another, and a plain string comparison would call
    those different files. Getting that wrong means the guards below quietly
    stop guarding.
    """
    if not left or not right:
        return False
    try:
        return os.path.samefile(left, right)
    except OSError:
        return (os.path.normcase(os.path.normpath(left))
                == os.path.normcase(os.path.normpath(right)))


def _layers_for_file(path):
    """Every vector layer in the current project backed by this file."""
    matches = []
    for layer in QgsProject.instance().mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue
        if _same_file(_layer_file(layer), path):
            matches.append(layer)
    return matches


def require_saved_edits(path, feedback=None):
    """Stop if any layer from this file still has unsaved edits.

    Committed edits are safe to read even before QGIS folds them back into the
    GeoPackage: they live in the file's write-ahead log, and the converters
    open the file in a mode that reads it. Edits still sitting in a layer's
    edit buffer, though, exist only in memory and would be silently missed.
    """
    unsaved = [
        layer.name()
        for layer in _layers_for_file(path)
        if layer.isEditable() and layer.isModified()
    ]
    if unsaved:
        raise QgsProcessingException(
            "These layers have unsaved edits, which would be missing from the "
            "conversion:\n  - "
            + "\n  - ".join(unsaved)
            + "\n\nSave them first (Layer > Save Layer Edits, or the Save "
            "button on the Digitising toolbar), then run this again."
        )
    if feedback is not None:
        feedback.pushInfo(f"Reading: {path}")


def refuse_open_target(path, feedback):
    """Stop if the file we are about to write into is open in this project."""
    open_layers = [layer.name() for layer in _layers_for_file(path)]
    if open_layers:
        raise QgsProcessingException(
            f"{os.path.basename(path)} is open in this project "
            f"({len(open_layers)} layer(s)), so it cannot be written to safely."
            "\n\nRun this from a different project — for example a new empty "
            "one — and open the template project afterwards to see the result."
        )


def report_to_feedback(report, feedback):
    """Show a converter's report in the Processing log."""
    feedback.pushInfo("")
    feedback.pushInfo("Rows written")
    for key, value in report.counts.items():
        feedback.pushInfo(f"    {key}: {value}")

    if report.lines:
        feedback.pushInfo("")
        feedback.pushInfo("What happened")
        for line in report.lines:
            feedback.pushInfo(f"    - {line}")

    if report.warnings:
        feedback.pushInfo("")
        for line in report.warnings:
            feedback.pushWarning(f"CHECK THIS: {line}")


class ConvertToLegacyAlgorithm(QgsProcessingAlgorithm):
    """BNG Service GeoPackage -> the legacy baseline + post-intervention pair."""

    INPUT = "INPUT"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"
    CARRY_LINEAGE = "CARRY_LINEAGE"
    OUTPUT_FORMAT = "OUTPUT_FORMAT"
    CONSOLIDATE = "CONSOLIDATE"
    SPLIT_IRREPLACEABLE = "SPLIT_IRREPLACEABLE"

    # Index order is the order shown in the dropdown; the tuples are what
    # new_to_old.convert expects.
    FORMAT_CHOICES = [
        ("Both", ("gpkg", "csv")),
        ("Legacy GeoPackages only (for the older service)", ("gpkg",)),
        ("GIS import tool CSVs only (for the Excel metric)", ("csv",)),
    ]

    def prepareAlgorithm(self, parameters, context, feedback):
        # Anything that reads the open project has to happen here. This runs
        # on the interface's own thread; processAlgorithm does not, which is
        # what keeps QGIS answering while a large site is converted.
        source = self.parameterAsFile(parameters, self.INPUT, context)
        require_saved_edits(source)
        return True

    def name(self):
        return "converttolegacy"

    def displayName(self):
        return "Convert to legacy template (for the older service)"

    def group(self):
        return "BNG template conversion"

    def groupId(self):
        return "bngtemplate"

    def shortHelpString(self):
        return (
            "<p>Takes the single GeoPackage used by the <b>BNG Service "
            "template</b> and writes the <b>two</b> GeoPackages the older "
            "Biodiversity Metric service expects — a baseline file and a "
            "post-intervention file, which you upload one after the other."
            "</p>"
            "<p><b>Save your edits first.</b> Anything still unsaved in the "
            "map cannot be converted, and this tool will stop and tell you "
            "which layers to save.</p>"
            "<p><b>Things the legacy format cannot hold</b> are listed as "
            "warnings when the tool finishes — read them. Vertical area "
            "habitats in particular have no legacy layer at all, so their "
            "biodiversity units will be missing from the legacy calculation."
            "</p>"
            "<p><i>Record lineage in comments</i> writes each feature's parent "
            "reference into the legacy Comment column. The older service "
            "ignores it, but it lets the companion tool restore the links "
            "exactly if you ever convert back. Leave it ticked unless you need "
            "the comment column untouched.</p>"
            "<p><b>What to produce.</b> Two different destinations want two "
            "different things:</p>"
            "<ul>"
            "<li><b>Legacy GeoPackages</b> are what you upload to the older "
            "Biodiversity Metric service, baseline first.</li>"
            "<li><b>GIS import tool CSVs</b> are what you feed to the Excel "
            "<i>GIS import tool</i>, which fills in the Statutory Biodiversity "
            "Metric or the Small Sites Metric. Three files, one per module, "
            "written into a <i>GIS import tool CSVs</i> folder. Import each "
            "into its matching tab, then choose On Site or Off Site in the tool "
            "before exporting.</li>"
            "</ul>"
            "<p><b>Individual trees are not in the CSVs.</b> The import tool "
            "cannot read tree points at all, so trees have to be typed into the "
            "metric by hand. They are still in the GeoPackages.</p>"
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT,
                "BNG Service GeoPackage (usually Layers/BNG Service Layers.gpkg)",
                behavior=QgsProcessingParameterFile.File,
                fileFilter=GEOPACKAGE_FILTER,
            )
        )
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_FOLDER,
                "Folder to write into (the legacy files, or a 'GIS import "
                "tool CSVs' folder, depending on the choice below)"
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.OUTPUT_FORMAT,
                "What to produce",
                options=[label for label, _ in self.FORMAT_CHOICES],
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.CARRY_LINEAGE,
                "Record lineage in comments (recommended)",
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.CONSOLIDATE,
                "CSVs: merge rows with matching values (only if you run out "
                "of rows in the import tool)",
                defaultValue=False,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.SPLIT_IRREPLACEABLE,
                "CSVs: keep irreplaceable habitat in its own rows (recommended)",
                defaultValue=True,
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsFile(parameters, self.INPUT, context)
        out_dir = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)
        carry = self.parameterAsBool(parameters, self.CARRY_LINEAGE, context)
        consolidate = self.parameterAsBool(parameters, self.CONSOLIDATE, context)
        split = self.parameterAsBool(
            parameters, self.SPLIT_IRREPLACEABLE, context)
        choice = self.parameterAsEnum(parameters, self.OUTPUT_FORMAT, context)
        label, formats = self.FORMAT_CHOICES[choice]

        if not source or not os.path.exists(source):
            raise QgsProcessingException(f"Cannot find the input file: {source}")
        feedback.pushInfo(f"Reading: {source}")
        feedback.pushInfo(f"Converting to the legacy template — {label}…")
        report = new_to_old.convert(
            source, out_dir, carry, False, formats,
            consolidate=consolidate, split_irreplaceable=split)
        report_to_feedback(report, feedback)

        feedback.pushInfo("")
        feedback.pushInfo("Next steps")
        if "gpkg" in formats:
            feedback.pushInfo(
                "    - Older service: upload the Baseline file first, then the "
                "Post-intervention file."
            )
            feedback.pushInfo(
                "    - Legacy QGIS template: take a copy of the whole template "
                "folder for each stage, put the matching file in its Layers "
                "folder, and rename it to 'Net Gain Habitat Mapping "
                "Layers.gpkg'. The project looks for that exact name."
            )
        if "csv" in formats:
            feedback.pushInfo(
                "    - Excel metric: open the GIS import tool, and on each of "
                "the Habitats, Hedges and Rivers tabs use 'Import GIS CSV "
                "Data' to load the matching CSV. Choose On Site or Off Site "
                "before exporting."
            )
            if split:
                feedback.pushInfo(
                    "    - Do NOT press 'Consolidate Data' in the import "
                    "tool. It cannot see the irreplaceable habitat flag and "
                    "would merge those parcels into ordinary habitat."
                )
        return {self.OUTPUT_FOLDER: out_dir}

    def createInstance(self):
        return ConvertToLegacyAlgorithm()


class ConvertFromLegacyAlgorithm(QgsProcessingAlgorithm):
    """The legacy pair -> a single BNG Service GeoPackage."""

    BASELINE = "BASELINE"
    POST_INTERVENTION = "POST_INTERVENTION"
    TEMPLATE = "TEMPLATE"
    OUTPUT_FILE = "OUTPUT_FILE"

    def prepareAlgorithm(self, parameters, context, feedback):
        # See the note on the same method above: the project may only be read
        # from the interface's own thread.
        baseline = self.parameterAsFile(parameters, self.BASELINE, context)
        post = self.parameterAsFile(parameters, self.POST_INTERVENTION, context)
        template = self.parameterAsFile(parameters, self.TEMPLATE, context)
        require_saved_edits(baseline)
        if post:
            require_saved_edits(post)
        if template:
            refuse_open_target(template, feedback)
        return True

    def name(self):
        return "convertfromlegacy"

    def displayName(self):
        return "Convert from legacy template (into the BNG Service template)"

    def group(self):
        return "BNG template conversion"

    def groupId(self):
        return "bngtemplate"

    def shortHelpString(self):
        return (
            "<p>Joins a legacy <b>baseline</b> and <b>post-intervention</b> "
            "GeoPackage back into the single GeoPackage the BNG Service "
            "template uses.</p>"
            "<p><b>The usual way to use this:</b> copy the whole BNG Service "
            "Template folder for your site, then set <i>Existing template "
            "GeoPackage to fill</i> to the copy's "
            "<i>Layers/BNG Service Layers.gpkg</i>. Open that copy's project "
            "afterwards and your habitats are there, with all the template's "
            "styling and drop-downs. Leave it blank instead to get a plain new "
            "GeoPackage.</p>"
            "<p><b>Lineage.</b> The legacy files never recorded which baseline "
            "feature each post-intervention feature came from. This tool links "
            "what it can prove — matching references, or breadcrumbs left by "
            "the companion tool — and deliberately leaves the rest blank so "
            "the service works them out from the shapes and tells you which "
            "ones it guessed. The log says how many were linked.</p>"
            "<p><b>Strategic significance.</b> The template holds Low or "
            "High. Legacy's middle value, <i>Location ecologically desirable "
            "but not in local strategy</i>, is left blank, and the log names "
            "those rows.</p>"
            "<p><b>Afterwards you must</b> fill in Irreplaceable Habitat where "
            "the habitat allows either answer (no legacy column exists), "
            "choose Low or High where significance was left blank, and add any "
            "vertical area habitats such as green walls.</p>"
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                self.BASELINE,
                "Legacy baseline GeoPackage",
                behavior=QgsProcessingParameterFile.File,
                fileFilter=GEOPACKAGE_FILTER,
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.POST_INTERVENTION,
                "Legacy post-intervention GeoPackage (leave blank for baseline only)",
                behavior=QgsProcessingParameterFile.File,
                fileFilter=GEOPACKAGE_FILTER,
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.TEMPLATE,
                "Existing template GeoPackage to fill (recommended)",
                behavior=QgsProcessingParameterFile.File,
                fileFilter=GEOPACKAGE_FILTER,
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_FILE,
                "…or write a new GeoPackage here",
                fileFilter=GEOPACKAGE_FILTER,
                optional=True,
                createByDefault=False,
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        baseline = self.parameterAsFile(parameters, self.BASELINE, context)
        post = self.parameterAsFile(parameters, self.POST_INTERVENTION, context)
        template = self.parameterAsFile(parameters, self.TEMPLATE, context)
        destination = self.parameterAsString(parameters, self.OUTPUT_FILE, context)

        if not baseline or not os.path.exists(baseline):
            raise QgsProcessingException(
                f"Cannot find the baseline file: {baseline}"
            )
        if not template and not destination:
            raise QgsProcessingException(
                "Choose either an existing template GeoPackage to fill, or a "
                "place to write a new GeoPackage."
            )
        if template and destination:
            feedback.pushWarning(
                "Both an existing template and a new file were given — filling "
                "the existing template and ignoring the new file."
            )

        feedback.pushInfo(f"Reading: {baseline}")
        if post:
            feedback.pushInfo(f"Reading: {post}")
        else:
            feedback.pushInfo(
                "No post-intervention file given — converting the baseline only."
            )

        if template:
            feedback.pushInfo(f"Filling: {template}")
            report = old_to_new.convert(
                baseline, post or None, ".", template, False, False
            )
        else:
            feedback.pushInfo(f"Writing: {destination}")
            report = old_to_new.convert(
                baseline,
                post or None,
                os.path.dirname(destination) or ".",
                None,
                False,
                False,
                out_file=destination,
            )

        report_to_feedback(report, feedback)
        feedback.pushInfo("")
        feedback.pushInfo(
            "Next: open the template project, check the parent links, fill in "
            "any blank Irreplaceable Habitat and strategic significance, and "
            "add any vertical area habitats."
        )
        return {self.OUTPUT_FILE: template or destination}

    def createInstance(self):
        return ConvertFromLegacyAlgorithm()


class ExportToMetricAlgorithm(QgsProcessingAlgorithm):
    """BNG Service GeoPackage -> a filled copy of the Statutory Metric."""

    INPUT = "INPUT"
    METRIC = "METRIC"
    OUTPUT_FILE = "OUTPUT_FILE"
    CONSOLIDATE = "CONSOLIDATE"

    def prepareAlgorithm(self, parameters, context, feedback):
        # See the note on the same method above.
        source = self.parameterAsFile(parameters, self.INPUT, context)
        require_saved_edits(source)
        return True

    def name(self):
        return "exporttometric"

    def displayName(self):
        return "Export to the Statutory Metric (Excel)"

    def group(self):
        return "BNG template conversion"

    def groupId(self):
        return "bngtemplate"

    def shortHelpString(self):
        return (
            "<p>Fills a copy of the <b>Statutory Biodiversity Metric</b> "
            "workbook straight from your habitats, with no GIS import tool in "
            "between.</p>"
            "<p><b>Point it at a blank metric.</b> Give it your own copy of "
            "either version Natural England publishes: "
            "<i>The_Statutory_Metric_Macro_Enabled</i> (.xlsm) or "
            "<i>The_Statutory_Metric_Macro_Disabled</i> (.xlsx). The sheets "
            "and the calculation are the same in both. The filled copy keeps "
            "the version you give it, so the .xlsx opens with no macro "
            "prompt. The blank file is not changed: a filled copy is written "
            "to wherever you choose. If the workbook already holds habitats "
            "the tool stops rather than overwrite them.</p>"
            "<p><b>Open the result in Excel and let it recalculate.</b> Macros, "
            "where the workbook has them, and sheet protection are carried "
            "over untouched.</p>"
            "<p><b>A site part-way through works.</b> Every baseline feature "
            "is written, so the baseline figures are right as soon as the "
            "baseline is drawn. Whatever has not been carried forward to "
            "post-intervention counts as lost, exactly as the template means "
            "it, so post-intervention figures are only as finished as that "
            "layer. Any value the metric needs and your layers leave blank is "
            "listed in the log, layer by layer: until it is filled in, the "
            "metric cannot score that row, and a total including it can read "
            "Check Data.</p>"
            "<p><b>What it fills:</b> the on-site tabs for area habitats, "
            "hedgerows and watercourses (A, B and C). Each parcel lands on the "
            "baseline tab with its size split into retained or enhanced, and "
            "the creation and enhancement tabs are filled to match.</p>"
            "<p><b>What it does not fill:</b> individual trees, whose size the "
            "metric derives from a band lookup; the off-site tabs (D, E and F), "
            "which have a different layout; and the separate <i>Irreplaceable "
            "Habitats</i> sheet. Enter those by hand.</p>"
            "<p><b>Irreplaceable habitat is half filled, and this is the half "
            "that matters most.</b> The Yes or No flag against every on-site "
            "baseline habitat row is written, so the metric prices those "
            "parcels correctly and raises its own warning where the flag "
            "disagrees with the habitat type. What is left for you is the "
            "<i>Irreplaceable Habitats</i> sheet, which asks for the name of "
            "each irreplaceable habitat and whether bespoke compensation has "
            "been agreed. The template records neither: it holds a flag, not a "
            "name, and compensation is a planning outcome rather than "
            "something on the map. Watercourses have no flag at all, because "
            "the template has no irreplaceable column on them.</p>"
            "<p><b>A site too large for one workbook is written as "
            "several.</b> Every sheet in the metric holds 248 rows, and 246 "
            "on the enhancement tabs. A site needing more is dealt evenly "
            "into numbered workbooks, each a complete and valid metric for "
            "its own share of the site. An enhancement always stays in the "
            "same workbook as the baseline parcel it improves. Add the unit "
            "totals across the set: a net gain percentage read off one "
            "workbook describes only the part of the site it holds.</p>"
            "<p><i>Merge rows with matching values</i> does what the import "
            "tool's <i>consolidate</i> button does: rows agreeing on everything "
            "but size become one row with the sizes added up. The totals do not "
            "change, because units scale with size. Use it to fit a large site "
            "into fewer workbooks. It costs the parcel-by-parcel audit trail, "
            "so it is off by default.</p>"
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT,
                "BNG Service GeoPackage (usually Layers/BNG Service Layers.gpkg)",
                behavior=QgsProcessingParameterFile.File,
                fileFilter=GEOPACKAGE_FILTER,
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.METRIC,
                "Blank Statutory Metric workbook (.xlsm or .xlsx)",
                behavior=QgsProcessingParameterFile.File,
                fileFilter=METRIC_FILTER,
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_FILE,
                "Filled metric workbook to write (a site over 248 rows is "
                "written as several, numbered)",
                fileFilter=METRIC_FILTER,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.CONSOLIDATE,
                "Merge rows with matching values (only if you run out of "
                "rows). Irreplaceable habitat is never merged with habitat "
                "that is not irreplaceable.",
                defaultValue=False,
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsFile(parameters, self.INPUT, context)
        metric = self.parameterAsFile(parameters, self.METRIC, context)
        destination = self.parameterAsFileOutput(
            parameters, self.OUTPUT_FILE, context)
        consolidate = self.parameterAsBool(parameters, self.CONSOLIDATE, context)

        for path, label in ((source, "GeoPackage"), (metric, "metric workbook")):
            if not path or not os.path.exists(path):
                raise QgsProcessingException(f"Cannot find the {label}: {path}")
        feedback.pushInfo(f"Reading: {source}")
        feedback.pushInfo("Filling the metric workbook…")

        def progress(fraction, message):
            """Move the bar, and stop between workbooks if Cancel was pressed."""
            feedback.setProgress(fraction * 100)
            feedback.setProgressText(message)
            return not feedback.isCanceled()

        try:
            report = to_metric.convert(source, metric, destination,
                                       consolidate, progress=progress)
        except ValueError as error:
            raise QgsProcessingException(str(error))
        report_to_feedback(report, feedback)

        # A site too large for one workbook is written as several, numbered
        # beside the name that was asked for, so the chosen path itself may
        # not exist. Hand back the first part rather than a path QGIS would
        # then fail to open.
        written = report.paths or [destination]

        feedback.pushInfo("")
        feedback.pushInfo("Next steps")
        if len(written) > 1:
            feedback.pushInfo(
                f"    - This site needed {len(written)} workbooks. Open each "
                "in Excel and let it recalculate.")
            feedback.pushInfo(
                "    - Add the unit totals across all of them. A net gain "
                "percentage from one workbook covers only part of the site.")
        else:
            feedback.pushInfo(
                "    - Open the workbook in Excel and let it recalculate.")
        feedback.pushInfo(
            "    - Add individual trees, the Irreplaceable Habitats sheet and "
            "any off-site parcels by hand. The irreplaceable flag on the "
            "on-site baseline habitat rows is already filled in.")
        return {self.OUTPUT_FILE: written[0]}

    def createInstance(self):
        return ExportToMetricAlgorithm()


ALGORITHMS = (ConvertToLegacyAlgorithm, ConvertFromLegacyAlgorithm,
              ExportToMetricAlgorithm)
