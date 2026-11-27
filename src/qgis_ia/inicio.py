# -*- coding: utf-8 -*-
"""Janela inicial do QGIS_IA: quatro tipos de projeto (Coleta Convencional, Coleta Seletiva,
Varrição Manual e Varrição Mecanizada).

Clicar num tipo → escolher a pasta com os arquivos → o app lê a pasta e sugere os detalhes →
o usuário confere → "Criar plano" gera o plano de serviço do edital.
"""
import json
import os

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QFont
from qgis.PyQt.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog,
                                 QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
                                 QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                                 QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
                                 QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                                 QWidget)

try:
    from . import criar_todos as CT
    from . import pastas as PA
    from .planos.barra import BarraLeitura
    from . import edital_slu as E
    from . import projetos as P
except ImportError:  # testes: pasta do plugin no sys.path
    import criar_todos as CT
    import pastas as PA
    from planos.barra import BarraLeitura
    import edital_slu as E
    import projetos as P

CFG_RECENTES = "qgis_ia/projetos_recentes"
CFG_ULTIMA = "qgis_ia/projetos_ultima_pasta"
_PAPEL = Qt.ItemDataRole.UserRole

NOME_APP = "App_Qgis"
ALTURA_CARTAO = 84
LARGURA_ICONE = 120
ESTILO_CARTAO = """
QPushButton#cartao { background: palette(base); border: 1px solid palette(mid);
                     border-radius: 10px; text-align: left; }
QPushButton#cartao:hover { border: 2px solid #2a7ab8; background: palette(alternate-base); }
"""


def _abrir(caminho):
    QDesktopServices.openUrl(QUrl.fromLocalFile(caminho))


def em_segundo_plano(fn, pd):
    """Roda fn(progresso, cancelado) numa thread, com a janela de progresso 'pd' viva.
    Devolve o resultado, ou None se der erro/cancelar (o erro aparece numa mensagem)."""
    import threading
    import time
    estado = {"txt": None, "res": None, "erro": None, "cancelar": False, "i": 0, "n": 0}

    def prog(t, i=None, n=None):
        estado["txt"] = t
        if n:
            estado["i"], estado["n"] = i or 0, n

    def trabalho():
        try:
            estado["res"] = fn(prog, lambda: estado["cancelar"])
        except Exception as e:
            estado["erro"] = e

    t = threading.Thread(target=trabalho, daemon=True)
    t.start()
    while t.is_alive():
        if estado["txt"]:
            pd.setLabelText(estado["txt"])
        if estado["n"]:
            pd.setMaximum(estado["n"])
            pd.setValue(estado["i"])
        estado["cancelar"] = pd.wasCanceled()
        QApplication.processEvents()
        time.sleep(0.05)
    cancelado = pd.wasCanceled()
    pd.close()
    if cancelado:
        return None
    if estado["erro"] is not None:
        QMessageBox.warning(pd.parent(), NOME_APP, str(estado["erro"]))
        return None
    return estado["res"]


class JanelaInicio(QDialog):
    def __init__(self, iface, abrir_chat=None, abrir_planos=None, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.abrir_chat = abrir_chat          # função: mostra o assistente (chat)
        self.abrir_planos = abrir_planos      # função(pasta, documentos): Planos do Contrato
        self.servico = None
        self.leitura = None
        self.det = None
        self._sugestoes = {}
        self._secao = None
        self._carregando = False
        self.textos = {}
        self.setWindowTitle(NOME_APP)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)
        self.resize(860, 760)
        lay = QVBoxLayout(self)
        self.pilha = QStackedWidget()
        lay.addWidget(self.pilha)
        self.pilha.addWidget(self._pagina_inicio())
        self.pilha.addWidget(self._pagina_projeto())
        self._mostrar_recentes()

    # ================================================================ página inicial
    def _pagina_inicio(self):
        w = QWidget()
        w.setStyleSheet(ESTILO_CARTAO)
        lay = QVBoxLayout(w)
        lay.setSpacing(10)
        t = QLabel(f"<span style='font-size:20pt; font-weight:600'>{NOME_APP}</span>"
                   "<br><span style='font-size:11pt'>Planos de serviço — escolha o tipo de "
                   "projeto</span>")
        lay.addWidget(t)
        self.cartoes = {}
        for tipo in P.TIPOS:
            b = self._cartao(tipo["icone"], tipo["nome"], tipo["descricao"])
            b.clicked.connect(lambda _=False, s=tipo["servico"]: self.novo_projeto(s))
            self.cartoes[tipo["servico"]] = b
            lay.addWidget(b)
        self.bt_todos = self._cartao(
            "".join(t["icone"] for t in P.TIPOS), "Criar Todos",
            "Todos os planos que o contrato pede, a partir de uma pasta (mesmo que tenha só o "
            "edital)", varios=True)
        self.bt_todos.setToolTip("Escolha a pasta: o app descobre os planos que o contrato pede, "
                                 "mostra os problemas e cria todos")
        self.bt_todos.clicked.connect(self.criar_todos)
        lay.addWidget(self.bt_todos)

        lay.addWidget(QLabel("<b>Projetos recentes</b> <small>(clique duplo para abrir)</small>"))
        self.lista_recentes = QListWidget()
        self.lista_recentes.setMaximumHeight(110)
        self.lista_recentes.itemDoubleClicked.connect(self._abrir_recente)
        lay.addWidget(self.lista_recentes)

        rod = QHBoxLayout()
        b = QPushButton("💬 Assistente IA (chat)")
        b.setToolTip("Pedir coisas ao QGIS por mensagem")
        b.clicked.connect(lambda: self.abrir_chat and self.abrir_chat())
        b.setEnabled(bool(self.abrir_chat))
        rod.addWidget(b)
        b = QPushButton("📑 Planos do Contrato")
        b.setToolTip("Ler o edital com IA, checklist, trazer dados, frota e equipe, validar")
        b.clicked.connect(lambda: self.abrir_planos and self.abrir_planos(None, []))
        b.setEnabled(bool(self.abrir_planos))
        rod.addWidget(b)
        rod.addStretch()
        lay.addLayout(rod)
        return w

    def _cartao(self, icone, nome, descricao, varios=False):
        """Cartão no mesmo padrão para todos: ícone(s) na frente, nome e descrição ao lado."""
        b = QPushButton()
        b.setObjectName("cartao")
        b.setFixedHeight(ALTURA_CARTAO)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        h = QHBoxLayout(b)
        h.setContentsMargins(14, 8, 14, 8)
        h.setSpacing(16)
        ic = QLabel(icone)
        f = QFont()
        f.setPointSize(16 if varios else 26)
        ic.setFont(f)
        ic.setFixedWidth(LARGURA_ICONE)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        h.addWidget(ic)
        v = QVBoxLayout()
        v.setSpacing(2)
        for txt, tam, neg in ((nome, 14, True), (descricao, 9, False)):
            lb = QLabel(txt)
            f = QFont()
            f.setPointSize(tam)
            f.setBold(neg)
            lb.setFont(f)
            lb.setWordWrap(True)
            lb.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            v.addWidget(lb)
        h.addLayout(v, 1)
        return b

    def _recentes(self):
        try:
            return json.loads(QgsSettings().value(CFG_RECENTES, "[]") or "[]")
        except (TypeError, ValueError):
            return []

    def _guardar_recente(self, servico, pasta):
        r = [x for x in self._recentes() if not (x["servico"] == servico and x["pasta"] == pasta)]
        r.insert(0, {"servico": servico, "pasta": pasta})
        QgsSettings().setValue(CFG_RECENTES, json.dumps(r[:10], ensure_ascii=False))
        QgsSettings().setValue(CFG_ULTIMA, pasta)
        self._mostrar_recentes()

    def _mostrar_recentes(self):
        self.lista_recentes.clear()
        for x in self._recentes():
            t = P.TIPO.get(x["servico"])
            if not t:
                continue
            it = QListWidgetItem(f"{t['icone']}  {t['nome']} — {x['pasta']}")
            it.setData(_PAPEL, (x["servico"], x["pasta"]))
            if not os.path.isdir(x["pasta"]):
                it.setText(it.text() + "  (pasta não encontrada)")
            self.lista_recentes.addItem(it)

    def _abrir_recente(self, it):
        servico, pasta = it.data(_PAPEL)
        if os.path.isdir(pasta):
            self.abrir_projeto(servico, pasta)

    # ================================================================ criar todos
    def criar_todos(self):
        ini = QgsSettings().value(CFG_ULTIMA, "") or os.path.expanduser("~")
        p = QFileDialog.getExistingDirectory(
            self, "Criar Todos: escolha a pasta com os arquivos do contrato (edital, planos "
                  "atuais…)", ini)
        if not p:
            return
        QgsSettings().setValue(CFG_ULTIMA, os.path.normpath(p))
        dlg = DialogoCriarTodos(self, os.path.normpath(p))
        if dlg.analisar():
            dlg.exec()

    # ================================================================ projeto
    def novo_projeto(self, servico):
        """Clique no cartão: pede a pasta com os arquivos."""
        ini = QgsSettings().value(CFG_ULTIMA, "") or os.path.expanduser("~")
        p = QFileDialog.getExistingDirectory(
            self, f"{P.TIPO[servico]['nome']}: escolha a pasta com os arquivos (edital, "
                  "plano atual .gdb, planilhas…)", ini)
        if p:
            self.abrir_projeto(servico, os.path.normpath(p))

    def abrir_projeto(self, servico, pasta):
        self.servico = servico
        t = P.TIPO[servico]
        self.lb_titulo.setText(f"<span style='font-size:16pt'>{t['icone']}</span> "
                               f"<span style='font-size:14pt; font-weight:600'>{t['nome']}</span>"
                               f"  <small>({servico} do edital)</small>")
        self.ed_pasta.setText(pasta)
        self.pilha.setCurrentIndex(1)
        self._ler(pasta, salvo=P.carregar_projeto(pasta, servico))
        self._guardar_recente(servico, pasta)

    def _pagina_projeto(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        topo = QHBoxLayout()
        b = QPushButton("← Início")
        b.clicked.connect(self._voltar)
        topo.addWidget(b)
        self.lb_titulo = QLabel()
        topo.addWidget(self.lb_titulo, 1)
        lay.addLayout(topo)

        rol = QScrollArea()
        rol.setWidgetResizable(True)
        rol.setFrameShape(QFrame.Shape.NoFrame)
        corpo = QWidget()
        cl = QVBoxLayout(corpo)
        rol.setWidget(corpo)
        lay.addWidget(rol, 1)

        # ---------------------------------------------------------- 1. pasta
        g = QGroupBox("1. Pasta com os arquivos")
        gl = QVBoxLayout(g)
        lin = QHBoxLayout()
        self.ed_pasta = QLineEdit()
        self.ed_pasta.setReadOnly(True)
        lin.addWidget(self.ed_pasta, 1)
        b = QPushButton("Trocar pasta…")
        b.clicked.connect(lambda: self.novo_projeto(self.servico))
        lin.addWidget(b)
        b = QPushButton("Ler de novo")
        b.clicked.connect(lambda: self._ler(self.ed_pasta.text(), manter=True))
        lin.addWidget(b)
        gl.addLayout(lin)
        self.arv_arquivos = QTreeWidget()
        self.arv_arquivos.setHeaderLabels(["Arquivo", "O que tem"])
        self.arv_arquivos.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.arv_arquivos.setColumnWidth(0, 330)
        self.arv_arquivos.setMinimumHeight(170)
        self.arv_arquivos.itemDoubleClicked.connect(self._abrir_item)
        gl.addWidget(self.arv_arquivos)
        cl.addWidget(g)

        # ---------------------------------------------------------- 2. detalhes
        g = QGroupBox("2. Detalhes do projeto")
        fl = QFormLayout(g)
        self.ed_nome = QLineEdit()
        fl.addRow("Nome do projeto:", self.ed_nome)
        self.cb_lote = QComboBox()
        for lote, ras in E.RA_POR_LOTE.items():
            nomes = ", ".join(E.RA[r] for r in sorted(ras))
            self.cb_lote.addItem(f"Lote {lote}", lote)
            self.cb_lote.setItemData(self.cb_lote.count() - 1, nomes,
                                     Qt.ItemDataRole.ToolTipRole)
        self.cb_lote.currentIndexChanged.connect(self._mudou_sugestao)
        fl.addRow("Lote:", self.cb_lote)
        self.ed_empresa = QLineEdit()
        self.ed_empresa.setPlaceholderText("nome da empresa (vai no texto do plano)")
        fl.addRow("Empresa:", self.ed_empresa)
        lin = QHBoxLayout()
        self.ck_diurno = QCheckBox("Diurno")
        self.ck_noturno = QCheckBox("Noturno")
        for ck in (self.ck_diurno, self.ck_noturno):
            ck.toggled.connect(self._mudou_sugestao)
            lin.addWidget(ck)
        lin.addStretch()
        fl.addRow("Turnos:", lin)
        self.cb_plano = QComboBox()
        self.cb_plano.currentIndexChanged.connect(self._mudou_sugestao)
        fl.addRow("Plano de partida:", self.cb_plano)
        lin = QHBoxLayout()
        self.ed_saida = QLineEdit()
        self.ed_saida.textChanged.connect(self._conferir)
        lin.addWidget(self.ed_saida, 1)
        b = QPushButton("Escolher…")
        b.clicked.connect(self._escolher_saida)
        lin.addWidget(b)
        fl.addRow("Salvar o plano em:", lin)
        self.ck_validar = QCheckBox("Conferir o plano com as regras do edital ao criar")
        self.ck_validar.setChecked(True)
        fl.addRow("", self.ck_validar)

        lin = QHBoxLayout()
        self.cb_secao = QComboBox()
        self.cb_secao.currentIndexChanged.connect(self._trocar_secao)
        lin.addWidget(self.cb_secao, 1)
        b = QPushButton("Refazer sugestões")
        b.setToolTip("Preenche de novo as seções vazias com o que foi lido da pasta")
        b.clicked.connect(lambda: self._aplicar_sugestoes(sobrescrever=False))
        lin.addWidget(b)
        fl.addRow("Texto do plano:", lin)
        self.ed_secao = QPlainTextEdit()
        self.ed_secao.setMinimumHeight(110)
        self.ed_secao.textChanged.connect(self._texto_editado)
        fl.addRow("", self.ed_secao)
        self.lb_falta = QLabel()
        self.lb_falta.setWordWrap(True)
        fl.addRow("", self.lb_falta)
        cl.addWidget(g)

        # ---------------------------------------------------------- 3. criar
        g = QGroupBox("3. Criar o plano")
        gl = QVBoxLayout(g)
        lin = QHBoxLayout()
        self.bt_criar = QPushButton("Criar plano")
        f = QFont()
        f.setBold(True)
        f.setPointSize(11)
        self.bt_criar.setFont(f)
        self.bt_criar.setMinimumHeight(36)
        self.bt_criar.clicked.connect(self._criar)
        lin.addWidget(self.bt_criar)
        self.bt_contrato = QPushButton("Ler o edital com IA / frota e equipe…")
        self.bt_contrato.setToolTip("Abre os Planos do Contrato com esta pasta e os documentos "
                                    "encontrados (perfil do edital, checklist, frota e equipe)")
        self.bt_contrato.clicked.connect(self._planos_contrato)
        self.bt_contrato.setEnabled(bool(self.abrir_planos))
        lin.addWidget(self.bt_contrato)
        lin.addStretch()
        self.bt_pasta_saida = QPushButton("Abrir pasta do plano")
        self.bt_pasta_saida.setEnabled(False)
        self.bt_pasta_saida.clicked.connect(lambda: _abrir(self._pasta_plano))
        lin.addWidget(self.bt_pasta_saida)
        gl.addLayout(lin)
        self.lb_resultado = QLabel()
        self.lb_resultado.setWordWrap(True)
        gl.addWidget(self.lb_resultado)
        self.lista_saida = QListWidget()
        self.lista_saida.setMaximumHeight(120)
        self.lista_saida.itemDoubleClicked.connect(lambda it: _abrir(it.data(_PAPEL)))
        gl.addWidget(self.lista_saida)
        cl.addWidget(g)
        self._pasta_plano = ""
        return w

    # ---------------------------------------------------------------- leitura
    def _ler(self, pasta, salvo=None, manter=False):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.leitura = P.ler_pasta(pasta)
        finally:
            QApplication.restoreOverrideCursor()
        self._mostrar_arquivos()
        sug = P.detalhes_sugeridos(self.leitura, self.servico)
        if manter and self.det:
            det = self._ler_formulario()
        elif salvo:
            det = dict(sug, **salvo)
        else:
            det = sug
        self._preencher(det)
        self.lista_saida.clear()
        self.lb_resultado.setText("")
        self.bt_pasta_saida.setEnabled(False)

    def _mostrar_arquivos(self):
        a = self.arv_arquivos
        a.clear()
        L = self.leitura

        def grupo(titulo, n):
            g = QTreeWidgetItem(a, [f"{titulo} ({n})", ""])
            f = g.font(0)
            f.setBold(True)
            g.setFont(0, f)
            g.setExpanded(True)
            return g

        g = grupo("📄 Documentos", len(L["documentos"]))
        for c in L["documentos"]:
            it = QTreeWidgetItem(g, [os.path.relpath(c, L["pasta"]),
                                     f"{os.path.getsize(c) / 1e6:.1f} MB"])
            it.setData(0, _PAPEL, c)
            it.setToolTip(0, c)
        g = grupo("🗺 Planos e camadas", len(L["bancos"]))
        for b in L["bancos"]:
            if b["erro"]:
                det = f"⚠ {b['erro']}"
            else:
                partes = []
                if b["servico"]:
                    partes.append(f"{b['servico']} {E.SERVICOS[b['servico']]['nome']}"
                                  + (f", lote {b['lote']}" if b["lote"] else ""))
                if b["circuitos"]:
                    partes.append(f"{b['circuitos']} circuitos")
                if b["turnos"]:
                    partes.append(", ".join(f"{n} {k.lower()}" for k, n in b["turnos"].items()))
                if b["km_linhas"]:
                    partes.append(f"{b['km_linhas']:.0f} km de vias")
                if not partes:
                    partes.append(", ".join(f"{c['nome']} ({c['feicoes']})"
                                            for c in b["camadas"][:4]))
                det = " · ".join(partes)
            it = QTreeWidgetItem(g, [os.path.relpath(b["caminho"], L["pasta"]), det])
            it.setData(0, _PAPEL, b["caminho"])
            it.setToolTip(1, "\n".join(f"{c['nome']}: {c['feicoes']}" for c in b["camadas"]))
            if b["servico"] == self.servico:
                f = it.font(0)
                f.setBold(True)
                it.setFont(0, f)
        g = grupo("📊 Planilhas", len(L["planilhas"]))
        for c in L["planilhas"]:
            it = QTreeWidgetItem(g, [os.path.relpath(c, L["pasta"]), ""])
            it.setData(0, _PAPEL, c)
        if L["outros"]:
            QTreeWidgetItem(a, [f"Outros arquivos ({L['outros']})", "não usados"])

    def _abrir_item(self, it, _col):
        c = it.data(0, _PAPEL)
        if c and os.path.exists(c):
            _abrir(c if not c.lower().endswith(".gdb") else os.path.dirname(c))

    # ---------------------------------------------------------------- formulário
    def _preencher(self, det):
        self._carregando = True
        self.det = det
        self.ed_nome.setText(det.get("nome") or "")
        i = self.cb_lote.findData(int(det.get("lote") or 1))
        self.cb_lote.setCurrentIndex(max(i, 0))
        self.ed_empresa.setText(det.get("empresa") or "")
        tur = det.get("turnos") or []
        self.ck_diurno.setChecked("Diurno" in tur)
        self.ck_noturno.setChecked("Noturno" in tur)
        self.cb_plano.clear()
        self.cb_plano.addItem("Criar plano novo, vazio, no padrão do edital", "")
        for b in self.leitura["bancos"]:
            if b["erro"] or not b["caminho"].lower().endswith(".gdb"):
                continue
            rot = os.path.basename(b["caminho"])
            if b["circuitos"]:
                rot += f" — {b['circuitos']} circuitos"
            if b["servico"] and b["servico"] != self.servico:
                rot += f" (é {E.SERVICOS[b['servico']]['nome']})"
            self.cb_plano.addItem("Usar o plano atual: " + rot, b["caminho"])
        pe = det.get("plano_existente") or ""
        i = self.cb_plano.findData(pe)
        if i < 0 and pe:
            self.cb_plano.addItem("Usar o plano atual: " + pe, pe)
            i = self.cb_plano.count() - 1
        self.cb_plano.setCurrentIndex(max(i, 0))
        self.ed_saida.setText(det.get("pasta_saida") or "")
        self.ck_validar.setChecked(det.get("validar", True))
        self.textos = dict(det.get("textos") or {})
        self._sugestoes = P.textos_sugeridos(self.servico, self.cb_lote.currentData(),
                                             self._turnos(), self._banco_escolhido())
        self.cb_secao.blockSignals(True)
        self.cb_secao.clear()
        for titulo, orient in E.SECOES_DOCX:
            self.cb_secao.addItem(titulo, titulo)
            self.cb_secao.setItemData(self.cb_secao.count() - 1, orient,
                                      Qt.ItemDataRole.ToolTipRole)
        self.cb_secao.blockSignals(False)
        self._secao = None
        self._carregando = False
        self.cb_secao.setCurrentIndex(0)
        self._trocar_secao()
        self._conferir()

    def _turnos(self):
        return [t for t, ck in (("Diurno", self.ck_diurno), ("Noturno", self.ck_noturno))
                if ck.isChecked()]

    def _banco_escolhido(self):
        c = self.cb_plano.currentData()
        for b in (self.leitura or {}).get("bancos", []):
            if b["caminho"] == c:
                return b
        return None

    def _mudou_sugestao(self, *_):
        """Lote, turno ou plano mudou: atualiza as seções que ainda estão com a sugestão."""
        if getattr(self, "_carregando", False) or not self.servico:
            return
        self._guardar_secao()
        nova = P.textos_sugeridos(self.servico, self.cb_lote.currentData(), self._turnos(),
                                  self._banco_escolhido())
        for k in set(nova) | set(self._sugestoes):
            atual = (self.textos.get(k) or "").strip()
            if not atual or atual == (self._sugestoes.get(k) or "").strip():
                self.textos[k] = nova.get(k, "")
        self._sugestoes = nova
        self._secao = None
        self._trocar_secao()
        self._conferir()

    def _aplicar_sugestoes(self, sobrescrever=False):
        self._guardar_secao()
        for k, v in self._sugestoes.items():
            if sobrescrever or not (self.textos.get(k) or "").strip():
                self.textos[k] = v
        self._secao = None
        self._trocar_secao()

    def _guardar_secao(self):
        if self._secao:
            self.textos[self._secao] = self.ed_secao.toPlainText()

    def _trocar_secao(self, *_):
        self._guardar_secao()
        self._secao = None
        k = self.cb_secao.currentData()
        self.ed_secao.blockSignals(True)
        self.ed_secao.setPlainText(self.textos.get(k, "") if k else "")
        orient = dict(E.SECOES_DOCX).get(k, "")
        self.ed_secao.setPlaceholderText(f"Vazio: no texto fica \"[Preencher: {orient}]\"")
        self.ed_secao.blockSignals(False)
        self._secao = k
        self._marcar_secoes()

    def _texto_editado(self):
        self._guardar_secao()
        self._marcar_secoes()

    def _marcar_secoes(self):
        for i in range(self.cb_secao.count()):
            k = self.cb_secao.itemData(i)
            ok = bool((self.textos.get(k) or "").strip())
            self.cb_secao.setItemText(i, ("✔ " if ok else "○ ") + k)

    def _escolher_saida(self):
        p = QFileDialog.getExistingDirectory(self, "Salvar o plano em",
                                             self.ed_saida.text() or self.ed_pasta.text())
        if p:
            self.ed_saida.setText(os.path.normpath(p))

    def _ler_formulario(self):
        self._guardar_secao()
        return {
            "servico": self.servico,
            "nome": self.ed_nome.text().strip(),
            "lote": self.cb_lote.currentData(),
            "empresa": self.ed_empresa.text().strip(),
            "turnos": self._turnos(),
            "plano_existente": self.cb_plano.currentData() or "",
            "pasta_saida": self.ed_saida.text().strip(),
            "validar": self.ck_validar.isChecked(),
            "textos": dict(self.textos),
        }

    def _conferir(self, *_):
        if getattr(self, "_carregando", False):
            return
        falta = P.faltando(self._ler_formulario())
        n = sum(1 for k, _ in E.SECOES_DOCX if (self.textos.get(k) or "").strip())
        txt = f"Texto: {n} de {len(E.SECOES_DOCX)} seções preenchidas (as vazias ficam para " \
              "completar no .docx)."
        if falta:
            txt = f"<span style='color:#c00'>Falta informar: {', '.join(falta)}.</span><br>" + txt
        self.lb_falta.setText(f"<small>{txt}</small>")
        self.bt_criar.setEnabled(not falta)

    # ---------------------------------------------------------------- ações
    def _salvar(self):
        if not self.servico or not self.ed_pasta.text():
            return
        try:
            P.salvar_projeto(self.ed_pasta.text(), self._ler_formulario())
        except OSError:
            pass

    def _voltar(self):
        self._salvar()
        self._mostrar_recentes()
        self.pilha.setCurrentIndex(0)

    def _criar(self):
        det = self._ler_formulario()
        self._salvar()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            r = P.criar_plano(det)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Criar plano", str(e))
            return
        QApplication.restoreOverrideCursor()
        self._pasta_plano = r["pasta"]
        self.bt_pasta_saida.setEnabled(True)
        self.lista_saida.clear()
        for k, c in r["arquivos"].items():
            it = QListWidgetItem(f"{P.nome_arquivo(k)} — {os.path.basename(c)}")
            it.setData(_PAPEL, c if not c.lower().endswith(".gdb") else os.path.dirname(c))
            it.setToolTip(c)
            self.lista_saida.addItem(it)
        linhas = [f"<b>✅ Plano criado</b> em {r['pasta']}."]
        if r.get("aviso"):
            linhas.append(r["aviso"])
        v = r.get("validacao")
        if v and "falhou" in v:
            linhas.append(f"⚠ A conferência não rodou: {v['falhou']}")
        elif v:
            cor = "#080" if not v["erros"] else "#c60"
            linhas.append(f"<span style='color:{cor}'>Conferência: {v['circuitos']} circuitos, "
                          f"{v['erros']} erros, {v['avisos']} avisos</span> (detalhes na "
                          "planilha de conferência).")
        pend = r.get("secoes_docx_a_preencher") or []
        if pend:
            linhas.append(f"Texto: {len(pend)} seção(ões) ficaram para completar no .docx: "
                          + ", ".join(pend) + ".")
        self.lb_resultado.setText("<br>".join(linhas))

    def _planos_contrato(self):
        if self.abrir_planos:
            self._salvar()
            self.abrir_planos(self.ed_pasta.text(), list((self.leitura or {}).get("documentos", [])))

    def closeEvent(self, ev):
        if self.pilha.currentIndex() == 1:
            self._salvar()
        super().closeEvent(ev)



# ====================================================================== criar todos
class DialogoCriarTodos(QDialog):
    """Mostra os planos que o contrato pede (serviço × lote), os problemas com a solução
    sugerida e cria os marcados."""

    COLS = ["Plano", "Lote", "De onde vem", "Problemas", "Resultado"]

    def __init__(self, parent, pasta, abrir_planos=None):
        super().__init__(parent)
        self.pasta = pasta
        self.abrir_planos = abrir_planos or getattr(parent, "abrir_planos", None)
        self.A = None
        self.resultado = None
        self.itens = {}
        self.setWindowTitle(f"Criar Todos — {pasta}")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)
        self.resize(1080, 780)
        lay = QVBoxLayout(self)
        self.lb_resumo = QLabel()
        self.lb_resumo.setWordWrap(True)
        lay.addWidget(self.lb_resumo)

        lin = QHBoxLayout()
        self.lin_lotes = QHBoxLayout()
        lin.addWidget(QLabel("Lotes:"))
        lin.addLayout(self.lin_lotes)
        lin.addStretch()
        for txt, fn in (("Marcar todos", lambda: self._marcar_todos(True)),
                        ("Desmarcar todos", lambda: self._marcar_todos(False))):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            lin.addWidget(b)
        lay.addLayout(lin)
        self.cks_lote = {}

        self.arv_planos = QTreeWidget()
        self.arv_planos.setHeaderLabels(self.COLS)
        for i, w in enumerate((300, 45, 320, 90)):
            self.arv_planos.setColumnWidth(i, w)
        self.arv_planos.itemChanged.connect(self._contar)
        self.arv_planos.itemDoubleClicked.connect(self._abrir_resultado)
        lay.addWidget(self.arv_planos, 3)

        lay.addWidget(QLabel("<b>Problemas que podem aparecer</b> <small>(clique para ver o "
                             "texto completo)</small>"))
        self.arv_prob = QTreeWidget()
        self.arv_prob.setHeaderLabels(["Problema", "O que acontece", "Solução sugerida"])
        self.arv_prob.setColumnWidth(0, 300)
        self.arv_prob.setColumnWidth(1, 400)
        lay.addWidget(self.arv_prob, 2)
        self.lb_prob = QLabel("")
        self.lb_prob.setWordWrap(True)
        self.lb_prob.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.arv_prob.currentItemChanged.connect(
            lambda it, _a: it and self.lb_prob.setText(
                f"<b>{it.text(0)}</b><br>{it.text(1)}<br><i>Solução:</i> {it.text(2)}"))
        lay.addWidget(self.lb_prob)
        lin = QHBoxLayout()
        self.bt_ia = QPushButton("📖 Ler o edital com o Claude")
        self.bt_ia.setToolTip("Abre os Planos do Contrato com esta pasta e o Claude lê o edital "
                              "(5 a 20 min). Depois clique em Analisar de novo.")
        self.bt_ia.clicked.connect(self._ler_ia)
        lin.addWidget(self.bt_ia)
        self.bt_emp = QPushButton("🏢 Planilha da empresa")
        self.bt_emp.setToolTip(f"Abre a {CT.EMP.NOME}.xlsx da pasta (cria o modelo com a frota "
                               "e o pessoal do edital se ainda não existir)")
        self.bt_emp.clicked.connect(self._planilha_empresa)
        lin.addWidget(self.bt_emp)
        self.bt_ocr = QPushButton("🔎 Ler escaneados com o Claude")
        self.bt_ocr.setToolTip("Páginas sem texto viram imagem e o Claude transcreve "
                               "(≈ 10 s por página; usa a sua assinatura)")
        self.bt_ocr.clicked.connect(self._ler_escaneados)
        self.bt_ocr.setVisible(False)
        lin.addWidget(self.bt_ocr)
        b = QPushButton("🔄 Analisar de novo")
        b.clicked.connect(self.analisar)
        lin.addWidget(b)
        lin.addStretch()
        lay.addLayout(lin)

        fl = QFormLayout()
        self.ed_empresa = QLineEdit()
        self.ed_empresa.setPlaceholderText("nome da empresa (padrão: o da planilha da empresa)")
        fl.addRow("Empresa:", self.ed_empresa)
        lin = QHBoxLayout()
        self.ed_mun = QLineEdit()
        self.ed_mun.setPlaceholderText("município (para o limite do IBGE e as vias do OSM)")
        self.ed_uf = QLineEdit()
        self.ed_uf.setMaxLength(2)
        self.ed_uf.setFixedWidth(50)
        self.ed_uf.setPlaceholderText("UF")
        lin.addWidget(self.ed_mun, 1)
        lin.addWidget(self.ed_uf)
        fl.addRow("Município:", lin)
        lin = QHBoxLayout()
        self.ed_saida = QLineEdit(PA.planos(pasta))
        lin.addWidget(self.ed_saida, 1)
        b = QPushButton("Escolher…")
        b.clicked.connect(self._escolher_saida)
        lin.addWidget(b)
        fl.addRow("Salvar os planos em:", lin)
        op = QHBoxLayout()
        self.ck_baixar = QCheckBox("Sem plano atual: baixar vias (OpenStreetMap) e limite (IBGE)")
        self.ck_frota = QCheckBox("Adequar frota e jornada (com histórico)")
        self.ck_corrigir = QCheckBox("Corrigir automaticamente")
        self.ck_validar = QCheckBox("Conferir com as regras do edital")
        self.ck_redigir = QCheckBox("Redigir o texto com o Claude")
        self.ck_redigir.setToolTip("O Claude escreve cada seção exigida a partir das páginas do "
                                   "edital (≈ 1 a 2 min por documento; usa a sua assinatura)")
        for ck in (self.ck_redigir, self.ck_baixar, self.ck_frota, self.ck_corrigir,
                   self.ck_validar):
            ck.setChecked(True)
            op.addWidget(ck)
        op.addStretch()
        fl.addRow("Etapas:", op)
        lay.addLayout(fl)

        self.barra_ia = BarraLeitura()
        lay.addWidget(self.barra_ia)
        self._janela_leitura = None
        rod = QHBoxLayout()
        self.lb_fim = QLabel()
        self.lb_fim.setWordWrap(True)
        self.lb_fim.setOpenExternalLinks(True)
        rod.addWidget(self.lb_fim, 1)
        self.bt_pasta = QPushButton("Abrir pasta dos planos")
        self.bt_pasta.setEnabled(False)
        self.bt_pasta.clicked.connect(lambda: _abrir(self.ed_saida.text()))
        rod.addWidget(self.bt_pasta)
        self.bt_criar = QPushButton("Criar")
        f = QFont()
        f.setBold(True)
        self.bt_criar.setFont(f)
        self.bt_criar.setMinimumHeight(32)
        self.bt_criar.clicked.connect(self._criar)
        rod.addWidget(self.bt_criar)
        b = QPushButton("Fechar")
        b.clicked.connect(self.reject)
        rod.addWidget(b)
        lay.addLayout(rod)

    # ---------------------------------------------------------------- análise
    def _progresso(self, titulo, n=0):
        from qgis.PyQt.QtWidgets import QProgressDialog
        pd = QProgressDialog(titulo, "Cancelar", 0, n, self)
        pd.setWindowTitle("Criar Todos")
        pd.setMinimumDuration(0)
        pd.setWindowModality(Qt.WindowModality.WindowModal)
        pd.setValue(0)
        return pd

    def analisar(self):
        pd = self._progresso("Lendo a pasta e os documentos (a 1ª vez demora ~1 min)…")

        def prog(txt, *_):
            pd.setLabelText(txt)
            QApplication.processEvents()

        try:
            self.A = CT.analisar(self.pasta, progresso=prog, cancelado=pd.wasCanceled)
        except Exception as e:
            pd.close()
            QMessageBox.warning(self.parent(), "Criar Todos", f"Não consegui ler a pasta: {e}")
            return False
        cancelado = pd.wasCanceled()
        pd.close()
        if cancelado:
            return False
        self._mostrar()
        return True

    def _mostrar(self):
        A = self.A
        n_docs = len(A["documentos"])
        n_gdb = sum(1 for b in A["leitura"]["bancos"] if b["circuitos"])
        self.lb_resumo.setText(
            f"<b>{A['edital'] or 'Edital ainda não lido'}</b> · {n_docs} documento(s) · "
            f"{n_gdb} plano(s) atual(is) na pasta"
            + (f"<br>Perfil: {A['perfil_origem']} · {len(A['servicos'])} serviço(s) · lotes "
               f"{', '.join(A['lotes'])} <small>(marcados pela {A['lotes_origem']})</small>"
               if A["perfil"] else ""))
        while self.lin_lotes.count():
            w = self.lin_lotes.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.cks_lote = {}
        for lote in A["lotes"] if A["perfil"] else []:
            ck = QCheckBox(f"Lote {lote}")
            ck.setChecked(lote in A.get("lotes_marcados", A["lotes"]))
            ck.toggled.connect(lambda v, l=lote: self._marcar_lote(l, v))
            self.lin_lotes.addWidget(ck)
            self.cks_lote[lote] = ck
        if not self.ed_mun.text():
            self.ed_mun.setText(A.get("municipio") or "")
        if not self.ed_uf.text():
            self.ed_uf.setText(A.get("uf") or "")

        a = self.arv_planos
        a.blockSignals(True)
        a.clear()
        codigos = {p["codigo"]: p for p in A["problemas"]}
        self.itens = {}
        for pl in A["planos"]:
            t = P.TIPO.get(pl["servico"])
            nome = f"{t['icone'] + '  ' if t else ''}{pl['servico']} {pl['nome']}"
            probs = " ".join(CT.ICONE[codigos[c]["nivel"]] for c in pl["problemas"]
                             if c in codigos)
            it = QTreeWidgetItem(a, [nome, str(pl["lote"]), pl["origem"]
                                     + (f" · {pl['circuitos']} circuitos" if pl["circuitos"]
                                        else ""), probs, ""])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Checked if pl.get("marcado", True)
                             else Qt.CheckState.Unchecked)
            it.setData(0, _PAPEL, pl["id"])
            it.setToolTip(0, "Arquivos: " + ", ".join(pl.get("arquivos") or []))
            it.setToolTip(3, "\n".join(f"{CT.ICONE[codigos[c]['nivel']]} {codigos[c]['titulo']}"
                                       for c in pl["problemas"] if c in codigos))
            if pl["plano_existente"]:
                f = it.font(0)
                f.setBold(True)
                it.setFont(0, f)
            self.itens[pl["id"]] = it
        a.blockSignals(False)

        p = self.arv_prob
        p.clear()
        for x in A["problemas"]:
            it = QTreeWidgetItem(p, [f"{CT.ICONE[x['nivel']]} {x['titulo']}", x["detalhe"],
                                     x["solucao"]])
            for c in range(3):
                it.setToolTip(c, it.text(c))
        if not A["problemas"]:
            QTreeWidgetItem(p, ["✅ Nenhum problema encontrado", "", ""])
        acoes = {x.get("acao") for x in A["problemas"]}
        self.bt_ia.setVisible(bool(A["documentos"]) and bool(self.abrir_planos))
        self.bt_ia.setStyleSheet("font-weight:bold" if "ler_ia" in acoes else "")
        self.bt_emp.setEnabled(bool(A["perfil"]))
        self.bt_ocr.setVisible(bool(A.get("escaneados")))
        self._contar()

    def _marcar_lote(self, lote, v):
        for pl in self.A["planos"]:
            if pl["lote"] == lote:
                self.itens[pl["id"]].setCheckState(0, Qt.CheckState.Checked if v
                                                   else Qt.CheckState.Unchecked)

    def _marcar_todos(self, v):
        for it in self.itens.values():
            it.setCheckState(0, Qt.CheckState.Checked if v else Qt.CheckState.Unchecked)

    def _marcados(self):
        return [pid for pid, it in self.itens.items()
                if it.checkState(0) == Qt.CheckState.Checked]

    def _contar(self, *_):
        n = len(self._marcados())
        self.bt_criar.setText(f"Criar {n} plano(s)")
        trava = CT.bloqueado(self.A) if self.A else True
        self.bt_criar.setEnabled(n > 0 and not trava)
        self.bt_criar.setToolTip("Resolva primeiro os problemas marcados com ⛔" if trava else "")

    def _escolher_saida(self):
        p = QFileDialog.getExistingDirectory(self, "Salvar os planos em", self.ed_saida.text())
        if p:
            self.ed_saida.setText(os.path.normpath(p))

    def _ler_ia(self):
        if not self.abrir_planos:
            return
        jan = self.abrir_planos(self.pasta, [d["caminho"] for d in self.A["documentos"]],
                                ler=True)
        self.lb_fim.setText("Confirme a leitura na janela Planos do Contrato. O andamento "
                            "aparece aqui; no fim a pasta é analisada de novo sozinha.")
        sinal = getattr(jan, "_sinal", None)
        if sinal is None:
            return
        self._desligar_leitura()
        self._janela_leitura = sinal
        sinal.leitura.connect(self.barra_ia.mostrar)
        sinal.leitura_fim.connect(self._fim_leitura_ia)

    def _desligar_leitura(self):
        s = self._janela_leitura
        if s is None:
            return
        for sig, fn in ((s.leitura, self.barra_ia.mostrar), (s.leitura_fim, self._fim_leitura_ia)):
            try:
                sig.disconnect(fn)
            except (TypeError, RuntimeError):
                pass
        self._janela_leitura = None

    def _fim_leitura_ia(self, ok, texto):
        self._desligar_leitura()
        self.barra_ia.concluir(ok, texto)
        if ok:
            self.lb_fim.setText("O Claude terminou de ler o edital. Analisando a pasta de novo…")
            self.analisar()
            self.lb_fim.setText("Edital lido e pasta analisada: confira os planos e os problemas.")
        else:
            self.lb_fim.setText("<span style='color:#c00'>A leitura do edital não terminou.</span> "
                                "Veja a mensagem na janela Planos do Contrato e tente de novo.")

    def done(self, r):
        self._desligar_leitura()
        super().done(r)

    def _ler_escaneados(self):
        pd = self._progresso("Lendo as páginas escaneadas com o Claude…")
        res = em_segundo_plano(lambda prog, canc: CT.ler_escaneados(self.A, prog, canc), pd)
        if res is None:
            return
        lidas = sum(r["paginas_lidas"] for r in res)
        faltaram = sum(len(r["faltaram"]) for r in res)
        self.analisar()
        self.lb_fim.setText(f"Claude leu {lidas} página(s) escaneada(s)"
                            + (f"; {faltaram} não deram certo (tente de novo)." if faltaram
                               else "."))

    def _planilha_empresa(self):
        """Monta a planilha da empresa com o que já está no edital (o Claude lê procedimentos,
        locais e responsáveis). No SLU, o modelo com a frota do Anexo R."""
        if self.A["slu"]:
            planos = [(x["servico"], x["lote"], x["sigla"]) for x in self.A["planos"]]
            arq = CT.EMP.criar_modelo(self.pasta, self.A["perfil"], planos)
            _abrir(arq)
            self.lb_fim.setText(f"Planilha da empresa: {os.path.basename(arq)}.")
            return
        pd = self._progresso("Montando a planilha da empresa com o edital…")
        info = em_segundo_plano(lambda prog, canc: CT.preparar_planilha(self.A, prog, canc), pd)
        if not info:
            return
        _abrir(info["arquivo"])
        partes = [f"{info['veiculos']} veículos", f"{info['pessoal']} linhas de pessoal",
                  f"{info['procedimentos']} procedimentos", f"{info['locais']} locais",
                  f"{info['responsaveis']} funções responsáveis"]
        msg = f"<b>Planilha montada com o edital</b> ({os.path.basename(info['arquivo'])}): " \
              + ", ".join(partes) + ". Complete os dados da empresa, nomes e o que está " \
              "[A DEFINIR], salve e crie os planos."
        if info["arquivo"].endswith("_sugerida.xlsx"):
            msg += " <i>A sua planilha já tinha dados seus: esta é uma sugestão ao lado, " \
                   "nada foi apagado.</i>"
        elif info.get("substituiu"):
            msg += " <i>A versão anterior ficou em App_Qgis\\Contrato.</i>"
        if info.get("claude") is False:
            msg += f" <span style='color:#c00'>O Claude não respondeu ({info['erro_claude'][:120]}); " \
                   "saiu só a frota e o pessoal.</span>"
        self.lb_fim.setText(msg)

    # ---------------------------------------------------------------- criar
    def _criar(self):
        ids = self._marcados()
        pd = self._progresso("Criando os planos…", len(ids))
        kw = dict(empresa=self.ed_empresa.text().strip(),
                  validar=self.ck_validar.isChecked(), corrigir=self.ck_corrigir.isChecked(),
                  frota=self.ck_frota.isChecked(), baixar=self.ck_baixar.isChecked(),
                  redigir=self.ck_redigir.isChecked(),
                  municipio=self.ed_mun.text().strip(), uf=self.ed_uf.text().strip().upper())
        saida = self.ed_saida.text().strip()
        R = em_segundo_plano(lambda prog, canc: CT.criar(self.A, ids, saida, progresso=prog,
                                                         cancelado=canc, **kw), pd)
        if R is None:
            return
        self.resultado = R
        for r in R["planos"]:
            it = self.itens[r["id"]]
            if r.get("ok"):
                v = r.get("validacao") or {}
                txt = "✅ criado"
                if v.get("erros") is not None:
                    txt += f" · conferência: {v['erros']} erros"
                fr = r.get("frota") or {}
                if fr.get("relatorio"):
                    txt += " · frota adequada"
                elif fr.get("falhou"):
                    txt += " · frota falhou"
                if r.get("redigido"):
                    txt += " · texto redigido pelo Claude"
                elif r.get("redigido") is False:
                    txt += " · Claude não redigiu"
                if r.get("pendentes"):
                    txt += f" · texto: {len(r['pendentes'])} seções a completar"
                if r.get("a_definir"):
                    txt += f" · {r['a_definir']} [A DEFINIR]"
                it.setData(4, _PAPEL, r["pasta"])
            else:
                txt = f"❌ {r.get('erro', '')}"
            it.setText(4, txt)
            it.setToolTip(4, txt)
        self._mostrar_problemas_depois()
        self.bt_pasta.setEnabled(True)
        self.lb_fim.setText(
            f"<b>{R['ok']} plano(s) criado(s)</b>"
            + (f", <span style='color:#c00'>{R['falhas']} com erro</span>" if R["falhas"] else "")
            + f". Relatório: <a href='{QUrl.fromLocalFile(R['relatorio']).toString()}'>"
            f"{os.path.basename(R['relatorio'])}</a> (clique duplo num plano abre a pasta dele)")

    def _mostrar_problemas_depois(self):
        p = self.arv_prob
        p.clear()
        for x in self.A["problemas"]:
            it = QTreeWidgetItem(p, [f"{CT.ICONE[x['nivel']]} {x['titulo']}", x["detalhe"],
                                     x["solucao"]])
            for c in range(3):
                it.setToolTip(c, it.text(c))

    def _abrir_resultado(self, it, _col):
        c = it.data(4, _PAPEL)
        if c and os.path.isdir(c):
            _abrir(c)
