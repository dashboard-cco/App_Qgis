# -*- coding: utf-8 -*-
"""Aba "Frota e equipe": adequa o plano já feito à frota e ao pessoal do edital novo."""
import os

from qgis.core import QgsTask
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout,
                                 QHeaderView, QLabel, QMessageBox, QPushButton, QSpinBox,
                                 QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import frota
from .abas_plano import carregar_camada

_PAPEL = Qt.ItemDataRole.UserRole
_ICONE = {"excede": "🔴", "fora_do_edital": "🔴", "ok": "🟢", "sobra": "🔵"}
_TXT = {"excede": "acima do edital", "fora_do_edital": "não existe no edital", "ok": "igual",
        "sobra": "sobra no edital"}
_METODOS = [("Automático (o que equilibra melhor)", "auto"), ("Só juntar circuitos", "juntar"),
            ("Dividir entre 2-3 vizinhos", "dividir")]


class AbaFrota(QWidget):
    def __init__(self, janela):
        super().__init__()
        self.j = janela
        self.proposta = None
        self.recusadas = set()   # (codigo, turno) de trocas desmarcadas
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Compara os veículos e o pessoal que o plano usa com o que o edital "
                             "dá (seções <i>recursos</i> e <i>equipes</i> do perfil) e propõe "
                             "como caber: trocar equipamento e tirar circuitos, juntando-os a "
                             "um vizinho ou dividindo-os entre vizinhos."))
        linha = QHBoxLayout()
        linha.addWidget(QLabel("Plano:"))
        self.cb = QComboBox()
        self.cb.currentIndexChanged.connect(self._limpar)
        linha.addWidget(self.cb, 1)
        self.bt_comparar = QPushButton("Comparar com o edital")
        self.bt_comparar.clicked.connect(self._comparar)
        linha.addWidget(self.bt_comparar)
        lay.addLayout(linha)
        self.lb = QLabel("Adicione o plano na aba 4.")
        self.lb.setWordWrap(True)
        lay.addWidget(self.lb)
        self.tab = QTreeWidget()
        self.tab.setHeaderLabels(["Veículo / função", "Turno", "Plano", "Edital", "Situação",
                                  "Dia de pico"])
        self.tab.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tab.setRootIsDecorated(False)
        lay.addWidget(self.tab, 2)

        linha = QHBoxLayout()
        linha.addWidget(QLabel("Adequar:"))
        self.cb_metodo = QComboBox()
        for txt, _ in _METODOS:
            self.cb_metodo.addItem(txt)
        linha.addWidget(self.cb_metodo)
        linha.addWidget(QLabel("vizinhos até"))
        self.sp_dist = QDoubleSpinBox()
        self.sp_dist.setRange(50, 20000)
        self.sp_dist.setValue(1500)
        self.sp_dist.setSuffix(" m")
        linha.addWidget(self.sp_dist)
        linha.addWidget(QLabel("dividir em até"))
        self.sp_rec = QSpinBox()
        self.sp_rec.setRange(2, 3)
        self.sp_rec.setValue(3)
        linha.addWidget(self.sp_rec)
        self.ck_regiao = QCheckBox("permitir outra região")
        self.ck_regiao.setToolTip("Em último caso, junta/divide com vizinho de outra região "
                                  "(campo de região/RA do plano).")
        linha.addWidget(self.ck_regiao)
        linha.addStretch()
        self.bt_propor = QPushButton("Propor")
        self.bt_propor.clicked.connect(self._propor)
        linha.addWidget(self.bt_propor)
        lay.addLayout(linha)

        self.arv = QTreeWidget()
        self.arv.setHeaderLabels(["Proposta", "Detalhe"])
        self.arv.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.arv.setColumnWidth(0, 360)
        self.arv.itemChanged.connect(self._troca_marcada)
        self.arv.itemDoubleClicked.connect(self._ir_para)
        lay.addWidget(self.arv, 3)
        linha = QHBoxLayout()
        self.lb2 = QLabel("<small>Clique duas vezes num circuito para vê-lo no mapa. Desmarque "
                          "uma troca para não fazê-la.</small>")
        self.lb2.setWordWrap(True)
        linha.addWidget(self.lb2, 1)
        self.bt_xlsx = QPushButton("Relatório .xlsx")
        self.bt_xlsx.clicked.connect(self._xlsx)
        linha.addWidget(self.bt_xlsx)
        self.bt_gravar = QPushButton("Gravar cópia adequada…")
        self.bt_gravar.clicked.connect(self._gravar)
        linha.addWidget(self.bt_gravar)
        lay.addLayout(linha)
        self._botoes()

    # ------------------------------------------------------------ util
    def atualizar(self):
        atual = self.cb.currentText()
        self.cb.blockSignals(True)
        self.cb.clear()
        self.cb.addItems(self.j.aba_plano.planos())
        if atual:
            self.cb.setCurrentText(atual)
        self.cb.blockSignals(False)

    def _limpar(self, *_):
        self.proposta = None
        self.recusadas = set()
        self.tab.clear()
        self.arv.clear()
        self._botoes()

    def _botoes(self):
        tem = self.proposta is not None
        self.bt_xlsx.setEnabled(tem)
        self.bt_gravar.setEnabled(tem and bool(self.proposta["operacoes"] or
                                               any(t["para"] for t in self.proposta["trocas"])))

    def _pronto(self, titulo):
        p = self.cb.currentText()
        if not p or not self.j.perfil:
            QMessageBox.information(self, titulo, "Escolha um plano (aba 4) e tenha um perfil.")
            return None
        if not (self.j.perfil.get("recursos")):
            QMessageBox.information(
                self, titulo, "O perfil ainda não tem a frota e o pessoal do edital (seções "
                "recursos e equipes). Use 'Ler com IA' na aba 1 ou um perfil pronto.")
            return None
        return p

    def _tabela(self, linhas):
        self.tab.clear()
        for l in linhas:
            ed = "—" if l["edital"] is None else str(l["edital"])
            nome = ("🚛 " if l["categoria"] == "equipamento" else "👷 ") + l["nome"]
            it = QTreeWidgetItem(self.tab, [nome, l["turno"], str(l["plano"]), ed,
                                            f"{_ICONE[l['situacao']]} {_TXT[l['situacao']]}",
                                            l["dia_pico"]])
            for c in (2, 3):
                it.setTextAlignment(c, Qt.AlignmentFlag.AlignCenter)

    # ------------------------------------------------------------ comparar
    def _comparar(self):
        p = self._pronto("Comparar")
        if not p:
            return
        prf, srv, sinal = self.j.perfil, self.j.aba_plano.servicos(p), self.j._sinal

        def trabalho(task):
            sinal.msg.emit("Lendo os circuitos do plano…")
            return frota.comparar(prf, p, srv)

        def fim(exc, res=None):
            self.j._ocupado(False)
            self.bt_comparar.setEnabled(True)
            if exc or not res:
                QMessageBox.warning(self, "Comparar", f"Erro: {exc}")
                return
            self.proposta = None
            self.arv.clear()
            self._tabela(res["linhas"])
            m = res["mapa"]
            txt = (f"<b>{'✅ Cabe no edital' if res['cabe'] else '⛔ Não cabe no edital'}</b> — "
                   f"serviços {', '.join(res['servicos']) or '?'} · lote {res['lote'] or '?'} · "
                   f"{res['circuitos']} circuitos em <i>{m['camada']}</i> (dias, "
                   f"{m['inicio']}/{m['fim']}, {m['turno'] or 'turno pelo horário'}, "
                   f"{m['equipamento']}).")
            if res["avisos"]:
                txt += "<br>⚠ " + "<br>⚠ ".join(res["avisos"][:6])
                if len(res["avisos"]) > 6:
                    txt += f"<br>… e mais {len(res['avisos']) - 6} aviso(s)."
            self.lb.setText(txt)
            self._botoes()
            self.j._status("Comparação concluída.")

        self.bt_comparar.setEnabled(False)
        self.j._rodar(QgsTask.fromFunction("Comparando frota", trabalho, on_finished=fim))

    # ------------------------------------------------------------ propor
    def _propor(self):
        p = self._pronto("Propor")
        if not p:
            return
        prf, srv, sinal = self.j.perfil, self.j.aba_plano.servicos(p), self.j._sinal
        metodo = _METODOS[self.cb_metodo.currentIndex()][1]
        dist, rec, outra = self.sp_dist.value(), self.sp_rec.value(), self.ck_regiao.isChecked()
        subst = {k: "" for k in self.recusadas}

        def trabalho(task):
            sinal.msg.emit("Montando a proposta (trocas e circuitos a tirar)…")
            return frota.propor(prf, p, srv, metodo=metodo, distancia=dist,
                                max_receptores=rec, outra_regiao=outra, substituicoes=subst)

        def fim(exc, res=None):
            self.j._ocupado(False)
            self.bt_propor.setEnabled(True)
            if exc or not res:
                QMessageBox.warning(self, "Propor", f"Erro: {exc}")
                return
            self.proposta = res
            self._mostrar()

        self.bt_propor.setEnabled(False)
        self.j._rodar(QgsTask.fromFunction("Propondo adequação", trabalho, on_finished=fim))

    def _mostrar(self):
        r = self.proposta
        self._tabela(r["depois"])
        self.tab.headerItem().setText(2, "Plano depois")
        self.arv.blockSignals(True)
        self.arv.clear()
        if r["trocas"]:
            g = QTreeWidgetItem(self.arv, ["Trocas de equipamento",
                                           "o edital não tem este equipamento neste turno"])
            g.setExpanded(True)
            for t in r["trocas"]:
                alt = "; ".join(f"{a['nome']} (sobra {a['sobra']})" for a in t["alternativas"])
                it = QTreeWidgetItem(g, [f"{t['nome_de']} ({t['turno']}) → "
                                         f"{t['nome_para'] or 'sem substituto'}",
                                         f"{len(t['circuitos'])} circuito(s)"])
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                recusada = (t["de"], t["turno"]) in self.recusadas
                it.setCheckState(0, Qt.CheckState.Unchecked if recusada or not t["para"]
                                 else Qt.CheckState.Checked)
                it.setToolTip(0, "Opções do edital: " + alt)
                it.setData(0, _PAPEL, ("troca", t["de"], t["turno"], t["circuitos"]))
        if r["operacoes"]:
            g = QTreeWidgetItem(self.arv, [f"Circuitos retirados ({len(r['operacoes'])})",
                                           "o que sai e para quem vai"])
            g.setExpanded(True)
            for op in r["operacoes"]:
                verbo = "juntar em" if op["tipo"] == "juntar" else \
                    f"dividir em {len(op['recebem'])}"
                it = QTreeWidgetItem(g, [f"{op['circuito']} — {verbo}",
                                         f"{op['turno']} · {', '.join(op['dias'])} · "
                                         f"{op['carga']:.1f} km"])
                it.setData(0, _PAPEL, ("op", op["circuito"],
                                       [x["codigo"] for x in op["recebem"]]))
                for x in op["recebem"]:
                    extra = []
                    if x["dias_a_mais"]:
                        extra.append("passa a ser atendido também " + ", ".join(x["dias_a_mais"]))
                    if x["outra_regiao"]:
                        extra.append("outra região")
                    filho = QTreeWidgetItem(it, [f"→ {x['codigo']}",
                                                 f"+{x['km']:.1f} km (fica com "
                                                 f"{x['carga_depois']:.1f} km)" +
                                                 (" · ⚠ " + "; ".join(extra) if extra else "")])
                    filho.setData(0, _PAPEL, ("op", x["codigo"], []))
        for n in r["nao_coube"]:
            QTreeWidgetItem(self.arv, ["⛔ " + n.split(":")[0], n.split(":", 1)[-1].strip()])
        if not r["trocas"] and not r["operacoes"] and not r["nao_coube"]:
            QTreeWidgetItem(self.arv, ["✅ O plano já cabe no edital.", ""])
        self.arv.blockSignals(False)
        self.lb.setText(f"<b>{'✅ Com a proposta, cabe no edital' if r['cabe'] else '⛔ Mesmo com a proposta, não cabe tudo'}</b>"
                        f" — {len(r['trocas'])} troca(s), {len(r['operacoes'])} circuito(s) "
                        "retirado(s). Nada foi gravado ainda.")
        self._botoes()
        self.j._status("Proposta pronta.")

    def _troca_marcada(self, it, col):
        dado = it.data(0, _PAPEL)
        if col != 0 or not dado or dado[0] != "troca":
            return
        chave = (dado[1], dado[2])
        if it.checkState(0) == Qt.CheckState.Checked:
            self.recusadas.discard(chave)
        else:
            self.recusadas.add(chave)
        self._propor()

    # ------------------------------------------------------------ mapa
    def _ir_para(self, it, _col):
        dado = it.data(0, _PAPEL)
        if not dado or not self.proposta:
            return
        m, plano = self.proposta["mapa"], self.proposta["plano"]
        codigos = [dado[1]] + list(dado[2]) if dado[0] == "op" else list(dado[3])
        lyr = carregar_camada(plano, m["camada"])
        if lyr is None:
            return
        lista = ",".join("'" + str(c).replace("'", "''") + "'" for c in codigos)
        lyr.selectByExpression(f'"{m["codigo"]}" IN ({lista})')
        if lyr.selectedFeatureCount() == 0:   # código numérico
            lyr.selectByExpression(f'to_string("{m["codigo"]}") IN ({lista})')
        try:
            self.j.iface.mapCanvas().zoomToSelected(lyr)
            self.j.iface.setActiveLayer(lyr)
        except Exception:
            pass
        self.j._status(f"Circuitos selecionados: {', '.join(codigos)}")

    # ------------------------------------------------------------ gravar
    def _xlsx(self):
        if not self.proposta:
            return
        base = os.path.splitext(os.path.basename(self.proposta["plano"].rstrip("/\\")))[0]
        sug = os.path.join(self.j.pasta, f"frota_{base}.xlsx")
        arq, _ = QFileDialog.getSaveFileName(self, "Relatório de frota e equipe", sug,
                                             "Excel (*.xlsx)")
        if arq:
            frota.relatorio_xlsx(self.proposta, arq)
            self.j._status(f"Relatório salvo: {arq}")

    def _gravar(self):
        r = self.proposta
        if not r:
            return
        sug = frota.destino_padrao(r["plano"])
        if os.path.isdir(r["plano"]):
            saida = QFileDialog.getSaveFileName(self, "Cópia adequada (.gdb)", sug,
                                                "File Geodatabase (*.gdb)")[0]
        else:
            ext = os.path.splitext(r["plano"])[1]
            saida = QFileDialog.getSaveFileName(self, "Cópia adequada", sug, f"*{ext}")[0]
        if not saida:
            return
        if os.path.isdir(r["plano"]) and not saida.lower().endswith(".gdb"):
            saida += ".gdb"
        prf, sinal, plano = self.j.perfil, self.j._sinal, r["plano"]

        def trabalho(task):
            sinal.msg.emit("Gravando a cópia adequada…")
            return frota.aplicar(prf, plano, r, saida)

        def fim(exc, res=None):
            self.j._ocupado(False)
            self.bt_gravar.setEnabled(True)
            if exc or not res:
                QMessageBox.warning(self, "Gravar", f"Não foi possível: {exc}")
                return
            if res["saida"] not in self.j.estado.setdefault("planos", []):
                self.j.estado["planos"].append(res["saida"])
                self.j._salvar_estado()
            self.j.aba_plano.atualizar()
            self.j.aba_validar.atualizar()
            self.atualizar()
            msg = (f"Gravado em:\n{res['saida']}\n\n{res['trocas']} circuito(s) com equipamento "
                   f"trocado, {res['operacoes']} circuito(s) retirado(s).\n\n" +
                   "\n".join(res["avisos"]) + "\n\nAbrir no QGIS?")
            if QMessageBox.question(self, "Gravar", msg) == QMessageBox.StandardButton.Yes:
                m = r["mapa"]
                for cam in [m["camada"]] + [c for c, _ in m["linhas"] + m["pontos"]]:
                    carregar_camada(res["saida"], cam)
            self.j._status("Cópia adequada gravada.")

        self.bt_gravar.setEnabled(False)
        self.j._rodar(QgsTask.fromFunction("Gravando cópia adequada", trabalho, on_finished=fim))
