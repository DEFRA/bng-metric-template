"""Processing provider holding the two conversion algorithms."""

import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .algorithms import ALGORITHMS

PROVIDER_ID = "bngtemplate"


class BngTemplateProvider(QgsProcessingProvider):
    def loadAlgorithms(self):
        for algorithm in ALGORITHMS:
            self.addAlgorithm(algorithm())

    def id(self):
        return PROVIDER_ID

    def name(self):
        return "BNG Template Convert"

    def longName(self):
        return "BNG Template Convert"

    def icon(self):
        path = os.path.join(os.path.dirname(__file__), "icon.svg")
        return QIcon(path) if os.path.exists(path) else QgsProcessingProvider.icon(self)
