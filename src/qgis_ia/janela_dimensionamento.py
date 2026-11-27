# -*- coding: utf-8 -*-
"""Tela do DIMENSIONAMENTO (Criar Todos → 📐): a análise de cada serviço ANTES de criar.

À esquerda os serviços que terão circuitos; à direita os parâmetros do edital (editáveis),
a conta (capacidade do circuito, frota, alertas) e a divisão por bairros (nº de circuitos,
km e t por circuito). "Recalcular" refaz a conta com o que foi digitado; "Usar estes
valores" grava em App_Qgis/Contrato/criar_todos.json e o Criar usa esses números.
"""
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QLabel, QListWidget,
                                 QListWidgetItem, QMessageBox, QProgressDialog, QPushButton,
                                 QSplitter, QTableWidget, QTableWidgetItem, QTextBrowser,
                                 QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

try:
    from . import criar_todos as CT
    from . import dimensionamento as DM
except ImportError:  # testes
    import criar_todos as CT
    import dimensionamento as DM

FREQ = {"diaria": "Diária", "trissemanal": "Trissemanal", "bissemanal": "Bissemanal",
        "semanal": "Semanal", "quinzenal": "Quinzenal", "rodizio": "Rodízio", "zona": "Área"}


class DialogoDimensionamento(QDialog):
    def __init__(self, parent, A, ids=None, municipio="", uf="", rodar=None):
        super().__init__(parent)
        self.A, self.ids, self.municipio, self.uf = A, ids, municipio, uf
        self.rodar = rodar            # em_segundo_plano (injetado para não importar inicio)
        self.dados = None
        self.params = {}
        self.atual = None
        self.setWindowTitle("Dimensionamento — análise antes de criar os planos")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)
        self.resize(1150, 760)
        lay = QVBoxLayout(self)
        self.lb_topo = QLabel(
            "Para cada serviço: frota, frequência e jornada do edital → capacidade de um "
            "circuito → nº de circuitos → divisão pelos bairros. Mude os valores e clique em "
            "<b>Recalcular</b>. A frequência de cada bairro pode ser mudada no arquivo de "
            "bairros (campo <i>frequencia</i>: diaria, trissemanal, bissemanal, semanal, "
            "quinzenal ou nao).")
        self.lb_topo.setWordWrap(True)
        lay.addWidget(self.lb_topo)
        sp = QSplitter(Qt.Orientation.Horizontal)
        self.lista = QListWidget()
        self.lista.currentRowChanged.connect(self._mostrar_servico)
        sp.addWidget(self.lista)
        dir_ = QWidget()
        dl = QVBoxLayout(dir_)
        dl.setContentsMargins(0, 0, 0, 0)
        self.tab = QTableWidget(0, 2)
        self.tab.setHorizontalHeaderLabels(["Parâmetro", "Valor"])
        self.tab.horizontalHeader().setStretchLastSection(True)
        self.tab.setColumnWidth(0, 430)
        self.tab.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        dl.addWidget(self.tab, 3)
        self.txt = QTextBrowser()
        dl.addWidget(self.txt, 2)
        self.arv = QTreeWidget()
        self.arv.setHeaderLabels(["Bairros", "Frequência", "Circuitos", "km/circuito",
                                  "t por coleta"])
        self.arv.setColumnWidth(0, 430)
        dl.addWidget(self.arv, 3)
        sp.addWidget(dir_)
        sp.setSizes([280, 870])
        lay.addWidget(sp, 1)
        rod = QHBoxLayout()
        b = QPushButton("↺ Valores do edital")
        b.setToolTip("Volta os parâmetros deste serviço para o que o edital diz")
        b.clicked.connect(self._padrao)
        rod.addWidget(b)
        self.bt_bairros = QPushButton("🗺 Abrir os bairros no QGIS")
        self.bt_bairros.clicked.connect(self._abrir_bairros)
        rod.addWidget(self.bt_bairros)
        rod.addStretch()
        b = QPushButton("Recalcular")
        b.clicked.connect(self.recalcular)
        rod.addWidget(b)
        b = QPushButton("✔ Usar estes valores")
        b.setDefault(True)
        b.clicked.connect(self._usar)
        rod.addWidget(b)
        b = QPushButton("Cancelar")
        b.clicked.connect(self.reject)
        rod.addWidget(b)
        lay.addLayout(rod)

    # ------------------------------------------------------------------ cálculo
    def calcular(self, params=None):
        pd = QProgressDialog("Preparando a base do município (vias, IBGE, bairros)…",
                             "Cancelar", 0, 0, self)
        pd.setWindowTitle("Dimensionamento")
        pd.setMinimumDuration(0)
        pd.setWindowModality(Qt.WindowModality.WindowModal)

        def fn(prog, canc):
            return CT.dimensionar(self.A, self.ids, self.municipio, self.uf, params,
                                  progresso=prog, cancelado=canc)
        d = self.rodar(fn, pd) if self.rodar else fn(lambda *a, **k: None, lambda: False)
        if d is None:
            return False
        self.dados = d
        self.params = {s["chave"]: dict(s["par"]) for s in d["servicos"]}
        linha = self.lista.currentRow()
        self.lista.blockSignals(True)
        self.lista.clear()
        for s in d["servicos"]:
            pl = s["plano"] or {}
            al = "⚠ " if pl.get("alertas") else ""
            it = QListWidgetItem(f"{al}{s['servico']} {s['nome'][:40]} (lote {s['lote']})\n"
                                 f"    {pl.get('circuitos', '?')} circuitos")
            it.setToolTip(s["nome"])
            self.lista.addItem(it)
        self.lista.blockSignals(False)
        if d["servicos"]:
            self.lista.setCurrentRow(max(0, min(linha, len(d["servicos"]) - 1)))
            self._mostrar_servico(self.lista.currentRow())
        else:
            self.txt.setHtml("Nenhum plano marcado tem circuitos para dimensionar (coleta, "
                             "varrição). " + "<br>".join(d.get("avisos") or []))
        self.bt_bairros.setEnabled(os.path.exists(d.get("bairros") or ""))
        return True

    def _ler_tabela(self):
        if self.atual is None:
            return
        par = self.params[self.atual]
        for r in range(self.tab.rowCount()):
            k = self.tab.item(r, 0).data(Qt.ItemDataRole.UserRole)
            par[k] = self.tab.item(r, 1).text().strip()
        self.params[self.atual] = DM.converter(par)

    def recalcular(self):
        self._ler_tabela()
        self.A["_territorio"] = None          # relê o arquivo de bairros (pode ter mudado)
        self.A.pop("_setorizados", None)
        return self.calcular(self.params)

    def _padrao(self):
        if self.atual is None:
            return
        s = next(x for x in self.dados["servicos"] if x["chave"] == self.atual)
        A = self.A
        if "_qtds" not in A:
            A["_qtds"] = DM.quantidades_edital(A["pasta"])
        self.params[self.atual] = DM.padrao(A["perfil"], s["servico"], s["lote"], qtds=A["_qtds"])
        self.atual = None
        self.calcular(self.params)

    # ------------------------------------------------------------------ mostrar
    def _mostrar_servico(self, i):
        if i < 0 or not self.dados or i >= len(self.dados["servicos"]):
            return
        if self.atual is not None and self.atual != self.dados["servicos"][i]["chave"]:
            self._ler_tabela()
        s = self.dados["servicos"][i]
        self.atual = s["chave"]
        par = self.params[self.atual]
        campos = DM.CAMPOS.get(par.get("tipo"), [])
        self.tab.setRowCount(len(campos))
        for r, (k, rot, _) in enumerate(campos):
            a = QTableWidgetItem(rot)
            a.setFlags(a.flags() & ~Qt.ItemFlag.ItemIsEditable)
            a.setData(Qt.ItemDataRole.UserRole, k)
            self.tab.setItem(r, 0, a)
            self.tab.setItem(r, 1, QTableWidgetItem(str(par.get(k, ""))))
        pl = s["plano"] or {}
        h = [f"<b>{s['servico']} {s['nome']}</b> — lote {s['lote']} · "
             f"{DM.ROTULOS_TIPO.get(par.get('tipo'), '')}"]
        h += [f"• {x}" for x in DM.resumo_parametros(par)]
        if pl:
            h.append(f"• Vias do serviço: {pl['km_vias']:.0f} km → <b>{pl['circuitos']} "
                     f"circuitos</b> ({pl.get('slots_usados') or 0:.1f} de {pl['slots']} "
                     "veículos/equipes-turno por dia).")
            if pl.get("ocupacao"):
                h.append(f"• Cada circuito usa {pl['ocupacao']:.0%} da capacidade de um turno.")
            for x in pl["alertas"]:
                h.append(f"<span style='color:#b45f06'>⚠ {x}</span>")
        else:
            h.append("<i>Sem as vias do município ainda: a divisão aparece depois de baixar "
                     "a base.</i>")
        for x in self.dados.get("avisos") or []:
            h.append(f"<span style='color:#777'>ℹ {x}</span>")
        if self.dados.get("fonte_bairros"):
            h.append(f"<small>Bairros: {self.dados['fonte_bairros']}.</small>")
        self.txt.setHtml("<br>".join(h))
        self.arv.clear()
        for g in pl.get("grupos") or []:
            QTreeWidgetItem(self.arv, [
                ", ".join(g["bairros"]) or "Município", FREQ.get(g["freq"], g["freq"]),
                str(g["n"]), f"{g['km_circ']:.1f}",
                f"{g['t_circ']:.1f}" if g.get("t_circ") else ""])

    def _abrir_bairros(self):
        arq = (self.dados or {}).get("bairros")
        if not arq or not os.path.exists(arq):
            return
        try:
            from qgis.core import QgsProject, QgsVectorLayer
            lyr = QgsVectorLayer(arq + "|layername=bairros", "Bairros (frequência da coleta)", "ogr")
            if lyr.isValid():
                QgsProject.instance().addMapLayer(lyr)
                QMessageBox.information(
                    self, "Bairros", "A camada Bairros foi aberta no QGIS. Mude o campo "
                    "'frequencia' dos bairros que precisar, salve a camada e clique em "
                    "Recalcular aqui.")
        except Exception as e:
            QMessageBox.warning(self, "Bairros", str(e))

    def _usar(self):
        self._ler_tabela()
        CT.guardar_dimensionamento(self.A["pasta"], self.params)
        self.A.pop("_setorizados", None)
        self.accept()
