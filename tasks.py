# -*- coding: utf-8 -*-
"""Task in background (QgsTask) per conversioni non bloccanti."""

from qgis.core import QgsTask

try:
    _CAN_CANCEL = QgsTask.Flag.CanCancel
except AttributeError:  # QGIS 3 / PyQt5
    _CAN_CANCEL = QgsTask.CanCancel


class FunctionTask(QgsTask):
    """Esegue una funzione in un thread separato.

    La funzione riceve il task stesso (per setProgress/isCanceled) e il suo
    valore di ritorno viene esposto in self.result; eventuali eccezioni in
    self.error. La costruzione di layer e l'aggiornamento della GUI vanno
    fatti nei callback dei segnali taskCompleted/taskTerminated (thread
    principale), non dentro la funzione di lavoro.
    """

    def __init__(self, description, work):
        super().__init__(description, _CAN_CANCEL)
        self._work = work
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self._work(self)
            return not self.isCanceled()
        except Exception as exc:
            self.error = exc
            return False
