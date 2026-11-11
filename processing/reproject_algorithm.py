# -*- coding: utf-8 -*-
"""Algoritmo Processing: riproietta un layer vettoriale con i grigliati IGM."""

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterCrs,
    QgsProcessingParameterString,
    QgsFeature,
)

from .. import settings
from .. import verto_api
from .. import converter


class VertoReprojectAlgorithm(QgsProcessingAlgorithm):
    INPUT = "INPUT"
    SOURCE_CRS = "SOURCE_CRS"
    TARGET_CRS = "TARGET_CRS"
    UTENTE = "UTENTE"
    CHIAVE = "CHIAVE"
    OUTPUT = "OUTPUT"

    def tr(self, string):
        return QCoreApplication.translate("VertoReproject", string)

    def createInstance(self):
        return VertoReprojectAlgorithm()

    def name(self):
        return "reproiettaigm"

    def displayName(self):
        return self.tr("Riproietta con grigliati IGM (Verto)")

    def group(self):
        return self.tr("Conversione coordinate")

    def groupId(self):
        return "conversione"

    def shortHelpString(self):
        return self.tr(
            "Riproietta un layer vettoriale convertendone tutti i vertici "
            "tramite l'API IGM \"Verto on line\" (grigliati nazionali), piu' "
            "precisa delle trasformazioni PROJ standard tra datum italiani.\n\n"
            "Utente e chiave IGM, se lasciati vuoti, sono quelli salvati "
            "nelle Impostazioni del plugin (consigliato: cosi' la chiave non "
            "resta nella cronologia di Processing).\n\n"
            "Il CRS di origine, se non specificato, e' quello del layer. Il "
            "CRS di destinazione deve essere un sistema supportato da IGM "
            "(es. EPSG:6706 RDN2008, EPSG:3003/3004 Monte Mario, EPSG:23032 "
            "ED50). Richiede connessione internet."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, self.tr("Layer di input"),
            [QgsProcessing.SourceType.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterCrs(
            self.SOURCE_CRS, self.tr("CRS di origine (vuoto = CRS del layer)"),
            optional=True))
        self.addParameter(QgsProcessingParameterCrs(
            self.TARGET_CRS, self.tr("CRS di destinazione"),
            defaultValue="EPSG:6706"))
        self.addParameter(QgsProcessingParameterString(
            self.UTENTE, self.tr("Utente IGM (opzionale)"),
            defaultValue="", optional=True))
        self.addParameter(QgsProcessingParameterString(
            self.CHIAVE, self.tr("Chiave IGM (opzionale)"),
            defaultValue="", optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Layer convertito")))

    def prepareAlgorithm(self, parameters, context, feedback):
        # Eseguito nel thread principale: qui si leggono le credenziali
        # salvate (la chiave puo' stare nel gestore di autenticazione).
        self._utente = (self.parameterAsString(parameters, self.UTENTE, context)
                        or settings.get_utente())
        self._chiave = (self.parameterAsString(parameters, self.CHIAVE, context)
                        or settings.get_chiave())
        self._endpoint = settings.get_endpoint()
        self._max_coord = settings.get_max_coord()
        return True

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException(
                self.invalidSourceError(parameters, self.INPUT))

        source_crs = self.parameterAsCrs(parameters, self.SOURCE_CRS, context)
        if source_crs is None or not source_crs.isValid():
            source_crs = source.sourceCrs()
        target_crs = self.parameterAsCrs(parameters, self.TARGET_CRS, context)

        in_epsg = converter.crs_to_epsg(source_crs)
        out_epsg = converter.crs_to_epsg(target_crs)
        if in_epsg is None:
            raise QgsProcessingException(
                "CRS di origine senza codice EPSG valido.")
        if out_epsg is None:
            raise QgsProcessingException(
                "CRS di destinazione senza codice EPSG valido.")
        if in_epsg == out_epsg:
            raise QgsProcessingException(
                "CRS di origine e destinazione coincidono.")
        if converter.same_datum(in_epsg, out_epsg):
            raise QgsProcessingException(
                "Origine e destinazione appartengono allo stesso datum ({}): "
                "il servizio IGM converte solo tra datum diversi. Usa "
                "l'algoritmo standard \"Riproietta layer\" di QGIS.".format(
                    converter.datum_of(in_epsg)))

        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context,
            source.fields(), source.wkbType(), target_crs)
        if sink is None:
            raise QgsProcessingException(
                self.invalidSinkError(parameters, self.OUTPUT))

        features = list(source.getFeatures())
        geoms = [f.geometry() for f in features]
        _note = verto_api.alias_notice(in_epsg, out_epsg)
        if _note:
            feedback.pushWarning(_note)
        feedback.pushInfo(
            "Conversione di {} elementi (EPSG:{} -> EPSG:{}) via IGM Verto..."
            .format(len(features), in_epsg, out_epsg))

        def progress_cb(done, tot):
            if feedback.isCanceled():
                raise QgsProcessingException("Operazione annullata.")
            feedback.setProgress(int(done * 100.0 / tot) if tot else 0)

        try:
            new_geoms = converter.convert_geometries(
                geoms, in_epsg, out_epsg,
                utente=self._utente, chiave=self._chiave,
                endpoint=self._endpoint,
                max_coord=self._max_coord,
                progress_cb=progress_cb)
        except verto_api.VertoError as exc:
            raise QgsProcessingException("Errore IGM Verto: {}".format(exc))

        for f, g in zip(features, new_geoms):
            if feedback.isCanceled():
                break
            nf = QgsFeature(source.fields())
            nf.setAttributes(f.attributes())
            nf.setGeometry(g)
            sink.addFeature(nf)

        return {self.OUTPUT: dest_id}
