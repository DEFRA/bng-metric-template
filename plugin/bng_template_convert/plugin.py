"""
Plugin entry point.

Registers the Processing provider and puts every algorithm on the Plugins
menu, so the tools can be reached without anyone having to find the Processing
Toolbox first.

Every algorithm belongs on that menu. One of them was once left off, and the
result was a tool nobody could find: it was in the Toolbox, where a user who
does not already know it exists has no reason to look. MENU_ITEMS below is the
whole list, and adding an algorithm means adding it here too.
"""

import os

from qgis.core import QgsApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .provider import PROVIDER_ID, BngTemplateProvider

MENU_TITLE = "&BNG Template Convert"
MENU_ITEMS = (
    ("Convert to legacy template…", f"{PROVIDER_ID}:converttolegacy"),
    ("Convert from legacy template…", f"{PROVIDER_ID}:convertfromlegacy"),
    ("Export to the Statutory Metric…", f"{PROVIDER_ID}:exporttometric"),
)


class BngTemplateConvertPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.actions = []

    def initProcessing(self):
        self.provider = BngTemplateProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()
        icon = self._icon()
        for label, algorithm_id in MENU_ITEMS:
            action = QAction(icon, label, self.iface.mainWindow())
            action.triggered.connect(
                lambda _checked, identifier=algorithm_id: self._run(identifier)
            )
            self.iface.addPluginToMenu(MENU_TITLE, action)
            self.actions.append(action)

    def unload(self):
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
        for action in self.actions:
            self.iface.removePluginMenu(MENU_TITLE, action)
        self.actions = []

    def _run(self, algorithm_id):
        # Imported here so the plugin still loads if Processing is unavailable.
        from processing import execAlgorithmDialog

        execAlgorithmDialog(algorithm_id, {})

    def _icon(self):
        path = os.path.join(os.path.dirname(__file__), "icon.svg")
        return QIcon(path) if os.path.exists(path) else QIcon()
