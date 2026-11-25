# -*- coding: utf-8 -*-
"""Abas 4 (Plano existente) e 5 (Validar) da janela Planos do Contrato."""
import os
import shutil

from qgis.core import QgsProject, QgsTask, QgsVectorLayer
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                                 QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem,
                                 QVBoxLayout, QWidget)

from . import estrutura, perfil, validacao

_PAPEL = Qt.ItemDataRole.UserRole


def _escolher_plano(parent, titulo, pasta):
    """.gdb é pasta; .gpkg/.shp é arquivo. Pergunta qual."""
    caixa = QMessageBox(parent)
    caixa.setWindowTitle(titulo)
    caixa.setText("Qual o formato?")
    b_gdb = caixa.addButton("File Geodatabase (.gdb)", QMessageBox.ButtonRole.AcceptRole)
    b_arq = caixa.addButton("GeoPackage / Shapefile", QMessageBox.ButtonRole.AcceptRole)
    caixa.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
    caixa.exec()
    if caixa.clickedButton() is b_gdb:
        p = QFileDialog.getExistingDirectory(parent, titulo + " (.gdb)", pasta)
        if p and not p.lower().rstrip("/\\").endswith(".gdb"):
            QMessageBox.warning(parent, titulo, "Escolha uma pasta terminada em .gdb.")
            return ""
        return os.path.normpath(p) if p else ""
    if caixa.clickedButton() is b_arq:
        p, _ = QFileDialog.getOpenFileName(parent, titulo, pasta,
                                           "Dados (*.gpkg *.shp *.geojson)")
        return os.path.normpath(p) if p else ""
    return ""


def carregar_camada(plano, camada):
    """Camada do plano no projeto (adiciona num grupo com o nome do arquivo, se faltar)."""
    prj = QgsProject.instance()
    alvo = os.path.normcase(os.path.normpath(plano))
    for lyr in prj.mapLayers().values():
        if isinstance(lyr, QgsVectorLayer) and lyr.name() == camada and \
                alvo in os.path.normcase(os.path.normpath(lyr.source().split("|")[0])):
            return lyr
    uri = f"{plano}|layername={camada}" if not plano.lower().endswith(".shp") else plano
    lyr = QgsVectorLayer(uri, camada, "ogr")
    if not lyr.isValid():
        return None
    raiz = prj.layerTreeRoot()
    nome_grupo = os.path.basename(plano.rstrip("/\\"))
    grupo = raiz.findGroup(nome_grupo) or raiz.insertGroup(0, nome_grupo)
    prj.addMapLayer(lyr, False)
    grupo.addLayer(lyr)
    return lyr


# ====================================================================== aba 4
class AbaPlano(QWidget):
    def __init__(self, janela):
        super().__init__()
        self.j = janela
        lay = QVBoxLayout(self)

        lay.addWidget(QLabel("<b>Modelos do contratante</b> — use os .gdb/.gpkg modelo (ou um "
                             "plano já aceito) para pôr no perfil os nomes exatos de camadas, "
                             "campos e domínios."))
        linha = QHBoxLayout()
        b = QPushButton("Completar perfil com modelo…")
        b.clicked.connect(self._modelo)
        linha.addWidget(b)
        linha.addStretch()
        lay.addLayout(linha)

        lay.addWidget(QLabel("<br><b>Plano existente</b> — aproveita o seu plano e cria só o "
                             "que falta (camadas e campos). Nada é apagado; antes é feita uma "
                             "cópia de segurança."))
        linha = QHBoxLayout()
        self.cb = QComboBox()
        self.cb.currentIndexChanged.connect(self._mostrar_falta)
        linha.addWidget(self.cb, 1)
        for txt, fn in (("Adicionar plano…", self._adicionar), ("Remover", self._remover)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            linha.addWidget(b)
        lay.addLayout(linha)
        self.arv = QTreeWidget()
        self.arv.setHeaderLabels(["O que falta no plano", "Detalhe"])
        self.arv.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.arv, 1)
        linha = QHBoxLayout()
        self.lb = QLabel("")
        self.lb.setWordWrap(True)
        linha.addWidget(self.lb, 1)
        b = QPushButton("Abrir no QGIS")
        b.clicked.connect(self._abrir)
        linha.addWidget(b)
        self.bt_criar = QPushButton("Criar o que falta")
        self.bt_criar.clicked.connect(self._criar)
        linha.addWidget(self.bt_criar)
        lay.addLayout(linha)

    # ------------------------------------------------------------ planos
    def planos(self):
        return [p for p in self.j.estado.setdefault("planos", []) if p]

    def atualizar(self):
        atual = self.cb.currentText()
        self.cb.blockSignals(True)
        self.cb.clear()
        self.cb.addItems(self.planos())
        if atual in self.planos():
            self.cb.setCurrentText(atual)
        self.cb.blockSignals(False)
        self._mostrar_falta()

    def plano(self):
        return self.cb.currentText()

    def _adicionar(self):
        p = _escolher_plano(self, "Plano existente", self.j.pasta)
        if not p:
            return
        if p not in self.planos():
            self.j.estado["planos"].append(p)
            self.j._salvar_estado()
        self.atualizar()
        self.cb.setCurrentText(p)
        self.j.aba_validar.atualizar()

    def _remover(self):
        p = self.plano()
        if p in self.planos():
            self.j.estado["planos"].remove(p)
            self.j._salvar_estado()
            self.atualizar()
            self.j.aba_validar.atualizar()

    def servicos(self, plano):
        srv = estrutura.servicos_do_arquivo(self.j.perfil, plano) if self.j.perfil else []
        return srv or list(self.j.estado.get("servicos") or [])

    def _mostrar_falta(self, *_):
        self.arv.clear()
        p = self.plano()
        if not p or not self.j.perfil:
            self.lb.setText("Escolha um plano." if self.j.perfil else "Sem perfil do contrato.")
            return
        if not os.path.exists(p):
            self.lb.setText("⚠ Plano não encontrado no disco.")
            return
        srv = self.servicos(p)
        try:
            falta = estrutura.o_que_falta(self.j.perfil, p, srv)
        except Exception as e:
            self.lb.setText(f"Erro ao ler o plano: {e}")
            return
        for nome in falta["camadas"]:
            cam = next(c for c in estrutura.camadas_exigidas(self.j.perfil, srv)
                       if c["nome"] == nome)
            QTreeWidgetItem(self.arv, [f"🔴 camada {nome}",
                                       f"{cam['geometria']}, {len(cam['campos'])} campos"])
        for camada, campos in falta["campos"].items():
            it = QTreeWidgetItem(self.arv, [f"🟡 {camada}", f"{len(campos)} campo(s)"])
            for c in campos:
                QTreeWidgetItem(it, [c, ""])
            it.setExpanded(True)
        n = len(falta["camadas"]) + sum(len(v) for v in falta["campos"].values())
        escopo = ", ".join(srv) if srv else "todos os serviços (marque na aba 2)"
        self.lb.setText(f"Serviços: {escopo}. " +
                        ("✅ Estrutura completa." if n == 0 else f"Faltam {n} item(ns)."))
        self.bt_criar.setEnabled(n > 0)

    def _criar(self):
        p = self.plano()
        if not p:
            return
        if QMessageBox.question(self, "Criar o que falta",
                                f"Criar as camadas e campos que faltam em\n{p}?\n\n"
                                "Antes será feita uma cópia de segurança ao lado do arquivo.") \
                != QMessageBox.StandardButton.Yes:
            return
        nomes = {os.path.normcase(l.source().split("|")[0]) for l in
                 QgsProject.instance().mapLayers().values()}
        if os.path.normcase(os.path.normpath(p)) in {os.path.normcase(os.path.normpath(n)) for n in nomes}:
            QMessageBox.information(self, "Criar o que falta",
                                    "O plano está aberto no QGIS. Se der erro de arquivo em uso, "
                                    "remova as camadas dele do projeto e tente de novo.")
        try:
            rel = estrutura.completar_plano(self.j.perfil, p, self.servicos(p))
        except Exception as e:
            QMessageBox.warning(self, "Criar o que falta", f"Não foi possível: {e}")
            return
        partes = []
        if rel["camadas_criadas"]:
            partes.append("Camadas criadas: " + ", ".join(rel["camadas_criadas"]))
        for c, cs in rel["campos_criados"].items():
            partes.append(f"{c}: " + ", ".join(cs))
        if rel["backup"]:
            partes.append(f"Cópia de segurança: {rel['backup']}")
        if rel["avisos"]:
            partes.append("Avisos: " + "; ".join(rel["avisos"]))
        QMessageBox.information(self, "Criar o que falta", "\n".join(partes) or "Nada a criar.")
        self._mostrar_falta()

    def _abrir(self):
        p = self.plano()
        if not p:
            return
        srv = self.servicos(p)
        n = 0
        for cam in estrutura.camadas_exigidas(self.j.perfil, srv) if self.j.perfil else []:
            if carregar_camada(p, cam["nome"]):
                n += 1
        self.j._status(f"{n} camada(s) do plano no projeto.")

    def _modelo(self):
        if not self.j.perfil:
            QMessageBox.information(self, "Modelo", "Monte o perfil do contrato primeiro (aba 1).")
            return
        m = _escolher_plano(self, "Modelo do contratante", self.j.pasta)
        if not m:
            return
        try:
            est = estrutura.ler(m)
        except Exception as e:
            QMessageBox.warning(self, "Modelo", f"Não consegui ler: {e}")
            return
        srv = estrutura.servicos_do_arquivo(self.j.perfil, m) or self.j.estado.get("servicos")
        novo, rel = estrutura.completar_perfil(self.j.perfil, est, srv)
        txt = [f"Modelo: {os.path.basename(m)} (serviços {', '.join(srv or []) or 'todos'})", ""]
        for l in rel["ligadas"]:
            txt.append(f"• {l['edital']}  →  {l['modelo']} ({l['campos']} campos)")
        for n in rel["novas"]:
            txt.append(f"• nova camada do modelo: {n}")
        for c, cs in rel["campos_so_no_perfil"].items():
            txt.append(f"⚠ {c}: campos do edital sem nome técnico no modelo: " + ", ".join(cs))
        txt += ["", "Aplicar ao perfil? (o atual fica em contrato_antes_modelo.json)"]
        if QMessageBox.question(self, "Completar perfil com modelo", "\n".join(txt)) \
                != QMessageBox.StandardButton.Yes:
            return
        arq = os.path.join(self.j.pasta, "contrato.json")
        if os.path.exists(arq):
            shutil.copy2(arq, os.path.join(self.j.pasta, "contrato_antes_modelo.json"))
        novo["_meta"].setdefault("modelos", []).append(os.path.basename(m))
        self.j.perfil = novo
        self.j._salvar_perfil()
        self.j._mostrar_perfil()
        self._mostrar_falta()
        self.j._status(f"Perfil completado com o modelo {os.path.basename(m)}.")


# ====================================================================== aba 5
class AbaValidar(QWidget):
    def __init__(self, janela):
        super().__init__()
        self.j = janela
        self.resultado = None
        lay = QVBoxLayout(self)
        linha = QHBoxLayout()
        linha.addWidget(QLabel("Plano:"))
        self.cb = QComboBox()
        linha.addWidget(self.cb, 1)
        self.bt = QPushButton("Validar")
        self.bt.clicked.connect(self._validar)
        linha.addWidget(self.bt)
        lay.addLayout(linha)
        self.lb = QLabel("Adicione o plano na aba 4 e clique em Validar.")
        self.lb.setWordWrap(True)
        lay.addWidget(self.lb)
        self.arv = QTreeWidget()
        self.arv.setHeaderLabels(["Camada / problema", "Campo", "Qtd.", "Detalhe"])
        self.arv.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.arv.setColumnWidth(0, 300)
        self.arv.itemDoubleClicked.connect(self._ir_para)
        lay.addWidget(self.arv, 1)
        linha = QHBoxLayout()
        linha.addWidget(QLabel("<small>Clique duas vezes num problema para selecionar as "
                               "feições no mapa.</small>"), 1)
        self.bt_xlsx = QPushButton("Relatório .xlsx")
        self.bt_xlsx.clicked.connect(self._xlsx)
        self.bt_xlsx.setEnabled(False)
        linha.addWidget(self.bt_xlsx)
        lay.addLayout(linha)

    def atualizar(self):
        atual = self.cb.currentText()
        self.cb.clear()
        self.cb.addItems(self.j.aba_plano.planos())
        if atual:
            self.cb.setCurrentText(atual)

    def _validar(self):
        p = self.cb.currentText()
        if not p or not self.j.perfil:
            QMessageBox.information(self, "Validar", "Escolha um plano (aba 4) e tenha um perfil.")
            return
        prf, srv, sinal = self.j.perfil, self.j.aba_plano.servicos(p), self.j._sinal

        def trabalho(task):
            return validacao.validar(prf, p, srv, progresso=sinal.msg.emit)

        def fim(exc, res=None):
            self.j._ocupado(False)
            self.bt.setEnabled(True)
            if exc or not res:
                QMessageBox.warning(self, "Validar", f"Erro: {exc}")
                return
            self.resultado = res
            self._mostrar()

        self.bt.setEnabled(False)
        self.j._rodar(QgsTask.fromFunction("Validando o plano", trabalho, on_finished=fim))

    def _mostrar(self):
        r = self.resultado
        self.arv.clear()
        s = r["resumo"]
        self.lb.setText(
            f"<b>{'✅ Aprovado' if s['aprovado'] else '⛔ Com erros'}</b> — serviços "
            f"{', '.join(r['servicos']) or 'todos'} · {s['feicoes_lidas']} feições lidas · "
            f"🔴 {s['erros']} erros · 🟡 {s['avisos']} avisos")
        self.j._status("Validação concluída.")
        grupos = {}
        for g in r["erros"]:
            pai = grupos.get(g["camada"])
            if pai is None:
                pai = grupos[g["camada"]] = QTreeWidgetItem(self.arv, [g["camada"]])
                pai.setExpanded(True)
            ic = "🔴" if g["severidade"] == validacao.ERRO else "🟡"
            it = QTreeWidgetItem(pai, [f"{ic} {g['regra'].replace('_', ' ')}", g["campo"] or "",
                                       str(g["quantidade"]), g["mensagem"]])
            it.setToolTip(3, g["mensagem"])
            it.setData(0, _PAPEL, (g["camada"], g["fids"]))
        for pai in grupos.values():
            n = sum(int(pai.child(i).text(2)) for i in range(pai.childCount()))
            pai.setText(2, str(n))
        self.bt_xlsx.setEnabled(True)

    def _ir_para(self, it, _col):
        dado = it.data(0, _PAPEL)
        if not dado or not self.resultado:
            return
        camada, fids = dado
        lyr = carregar_camada(self.resultado["plano"], camada)
        if lyr is None:
            return
        if fids:
            lyr.selectByIds(fids)
            try:
                self.j.iface.mapCanvas().zoomToSelected(lyr)
            except Exception:
                pass
            self.j._status(f"{len(fids)} feição(ões) selecionada(s) em {camada}.")
        try:
            self.j.iface.setActiveLayer(lyr)
        except Exception:
            pass

    def _xlsx(self):
        if not self.resultado:
            return
        base = os.path.splitext(os.path.basename(self.resultado["plano"].rstrip("/\\")))[0]
        sug = os.path.join(self.j.pasta, f"validacao_{base}.xlsx")
        arq, _ = QFileDialog.getSaveFileName(self, "Relatório da validação", sug, "Excel (*.xlsx)")
        if not arq:
            return
        validacao.relatorio_xlsx(self.resultado, arq)
        self.j._status(f"Relatório salvo: {arq}")
