# -*- coding: utf-8 -*-
"""Provider Processing che espone gli algoritmi IGM Verto."""

import os

from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsProcessingProvider

from .reproject_algorithm import VertoReprojectAlgorithm


class VertoProcessingProvider(QgsProcessingProvider):

    def id(self):
        return "igmverto"

    def name(self):
        return "IGM Verto"

    def longName(self):
        return "IGM Verto - conversione coordinate con grigliati IGM"

    def icon(self):
        path = os.path.join(os.path.dirname(__file__), "..", "icon.svg")
        return QIcon(path)

    def loadAlgorithms(self):
        self.addAlgorithm(VertoReprojectAlgorithm())
