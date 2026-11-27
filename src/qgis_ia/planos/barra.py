# -*- coding: utf-8 -*-
"""Barra de progresso da leitura do edital pelo Claude: porcentagem, tempo decorrido e o
passo atual (ex.: "Lendo Anexo G, p. 1-30")."""
import time

from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget


class BarraLeitura(QWidget):
    def __init__(self, titulo="Claude lendo o edital", parent=None):
        super().__init__(parent)
        self.titulo = titulo
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lin = QHBoxLayout()
        self.lb_titulo = QLabel()
        lin.addWidget(self.lb_titulo, 1)
        self.lb_tempo = QLabel()
        lin.addWidget(self.lb_tempo)
        lay.addLayout(lin)
        self.barra = QProgressBar()
        self.barra.setRange(0, 100)
        self.barra.setTextVisible(True)
        self.barra.setFormat("%p%")
        lay.addWidget(self.barra)
        self.lb_passo = QLabel()
        self.lb_passo.setWordWrap(True)
        lay.addWidget(self.lb_passo)
        self._t0 = None
        self._relogio = QTimer(self)
        self._relogio.timeout.connect(self._tempo)
        self.setVisible(False)

    def mostrar(self, pct, texto=""):
        if self._t0 is None:
            self._t0 = time.time()
            self._relogio.start(1000)
        self.setVisible(True)
        self.barra.setValue(max(self.barra.value(), int(pct)))
        self.lb_titulo.setText(f"<b>{self.titulo}</b> — {self.barra.value()}%")
        if texto:
            self.lb_passo.setText(f"<small>{texto}…</small>")
        self._tempo()

    def parar(self, ok=None, texto=""):
        self._relogio.stop()
        self._t0 = None
        self.barra.setValue(0)
        self.setVisible(False)

    def concluir(self, ok, texto=""):
        """Mostra o fim (100% ou falha) sem esconder a barra."""
        self._relogio.stop()
        decorrido = self.lb_tempo.text()
        self._t0 = None
        if ok:
            self.barra.setValue(100)
            self.lb_titulo.setText(f"<b>{self.titulo}</b> — concluído")
        else:
            self.lb_titulo.setText(f"<b>{self.titulo}</b> — <span style='color:#c00'>parou</span>")
        self.lb_passo.setText(f"<small>{texto[:300]}</small>")
        self.lb_tempo.setText(decorrido)

    def _tempo(self):
        if self._t0 is None:
            return
        s = int(time.time() - self._t0)
        self.lb_tempo.setText(f"{s // 60} min {s % 60:02d} s")
