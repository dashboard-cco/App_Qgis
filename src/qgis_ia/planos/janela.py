# -*- coding: utf-8 -*-
"""Janela "Planos do Contrato": documentos → requisitos → checklist → gerar → validar.

Tudo o que é demorado (ler PDF, chamar a IA) roda em QgsTask, sem travar o QGIS.
"""
import json
import os

from qgis.core import (QgsApplication, QgsProject, QgsProviderRegistry, QgsSettings, QgsTask,
                       QgsVectorLayer, QgsWkbTypes, QgsFeatureRequest)
from qgis.PyQt.QtCore import (QObject, QProcess, QProcessEnvironment, Qt, QTimer, QUrl,
                              pyqtSignal)
from qgis.PyQt.QtGui import QDesktopServices, QFont
from qgis.PyQt.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
                                 QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                                 QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem,
                                 QVBoxLayout, QWidget)

from . import checklist, config_ia, documentos, extracao, ferramentas, leitor_claude, perfil

ARQ_PERFIL = "contrato.json"
ARQ_ESTADO = "estado.json"
PASTA_TEXTOS = "textos"
CFG_PASTA = "qgis_ia/planos_pasta"
CFG_ADIADO = "qgis_ia/config_ia_adiada"

ICONE = {checklist.OK: "🟢", checklist.PARCIAL: "🟡", checklist.FALTA: "🔴",
         checklist.CONFIRMAR: "⚪", checklist.INFO: "📄"}
ROTULO = {checklist.OK: "tem", checklist.PARCIAL: "incompleto", checklist.FALTA: "falta",
          checklist.CONFIRMAR: "confirmar", checklist.INFO: ""}

_CHECK = Qt.ItemFlag.ItemIsUserCheckable
_MARCADO, _DESMARCADO = Qt.CheckState.Checked, Qt.CheckState.Unchecked


# ====================================================================== conta da IA
class ConfigIADialog(QDialog):
    """Primeiro uso: confere a conta Claude da máquina (Claude Code) ou pede uma chave de API."""

    def __init__(self, parent=None, primeira_vez=False):
        super().__init__(parent)
        self.setWindowTitle("Configurar IA")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        intro = ("<b>Bem-vindo!</b> O app usa o Claude para ler editais e especificações.<br><br>"
                 if primeira_vez else "")
        topo = QLabel(intro + "<b>1. Conta Claude desta máquina (recomendado)</b><br>"
                      "Usa a sua assinatura do Claude (claude.ai) pelo Claude Code, ligado ao "
                      "QGIS por MCP. Não precisa de chave nem de créditos da API.")
        topo.setWordWrap(True)
        lay.addWidget(topo)
        self.lb_claude = QLabel("Verificando…")
        self.lb_claude.setWordWrap(True)
        self.lb_claude.setOpenExternalLinks(True)
        lay.addWidget(self.lb_claude)
        linha = QHBoxLayout()
        self.bt_login = QPushButton("Fazer login no Claude")
        self.bt_login.clicked.connect(self._login)
        self.bt_verificar = QPushButton("Verificar de novo")
        self.bt_verificar.clicked.connect(self._verificar_claude)
        linha.addWidget(self.bt_login)
        linha.addWidget(self.bt_verificar)
        linha.addStretch()
        lay.addLayout(linha)

        info = QLabel("<br><b>2. Ou chave de API da Anthropic (alternativa)</b><br>"
                      "Crie em <a href='%s'>console.anthropic.com</a>, cole abaixo e clique em "
                      "<b>Testar e salvar</b>. Cobra por uso (um edital ≈ US$ 1 a 3) e precisa "
                      "de créditos na conta." % config_ia.URL_CONSOLE)
        info.setOpenExternalLinks(True)
        info.setWordWrap(True)
        lay.addWidget(info)
        self.campo = QLineEdit()
        self.campo.setEchoMode(QLineEdit.EchoMode.Password)
        self.campo.setPlaceholderText("sk-ant-...")
        atual = config_ia.chave()
        if atual:
            self.campo.setPlaceholderText(f"atual: {config_ia.mascarar(atual)} (deixe vazio para manter)")
        lay.addWidget(self.campo)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        bts = QHBoxLayout()
        bts.addStretch()
        self.bt_depois = QPushButton("Fechar")
        self.bt_ok = QPushButton("Testar e salvar chave")
        bts.addWidget(self.bt_depois)
        bts.addWidget(self.bt_ok)
        lay.addLayout(bts)
        self.bt_depois.clicked.connect(self._fechar)
        self.bt_ok.clicked.connect(self._salvar)
        QTimer.singleShot(50, self._verificar_claude)

    def _fechar(self):
        if config_ia.configurada():
            self.accept()
        else:
            self.reject()

    def _verificar_claude(self):
        self.lb_claude.setText("Verificando…")
        QApplicationProcess()
        c = config_ia.claude_code(atualizar=True)
        if c["ok"]:
            self.lb_claude.setText(f"<span style='color:#080'>✅ {c['mensagem']}</span>")
            self.bt_login.setVisible(False)
        elif c["exe"]:
            self.lb_claude.setText(f"<span style='color:#c60'>⚠ {c['mensagem']}</span> Clique em "
                                   "<b>Fazer login no Claude</b> e entre com a conta da empresa.")
            self.bt_login.setVisible(True)
        else:
            self.lb_claude.setText(
                "<span style='color:#c00'>✖ Claude Code não encontrado.</span> Instale em "
                "<a href='https://claude.com/claude-code'>claude.com/claude-code</a> "
                "(ou a extensão Claude Code do VS Code) e clique em Verificar de novo.")
            self.bt_login.setVisible(False)

    def _login(self):
        """Abre um terminal com 'claude auth login' (o login abre o navegador)."""
        import subprocess
        exe = config_ia.claude_code()["exe"]
        if not exe:
            return
        from .leitor_claude import ambiente
        if os.name == "nt":
            subprocess.Popen(["cmd", "/c", "start", "Login Claude", "cmd", "/k", exe, "auth", "login"],
                             env=ambiente())
        else:
            subprocess.Popen([exe, "auth", "login"], env=ambiente())
        QMessageBox.information(self, "Login no Claude",
                                "Conclua o login no terminal/navegador que abriu e depois clique "
                                "em Verificar de novo.")

    def _salvar(self):
        k = self.campo.text().strip() or config_ia.chave()
        if not k:
            self.status.setText("Cole a chave de API.")
            return
        self.status.setText("Testando...")
        QApplicationProcess()
        ok, msg = config_ia.testar(k)
        if not ok:
            self.status.setText(f"<span style='color:#c00'>{msg}</span>")
            return
        onde = config_ia.salvar(k)
        QgsSettings().remove(CFG_ADIADO)
        QMessageBox.information(self, "Configurar IA", f"{msg}\nChave salva nas {onde}.")
        self.accept()


def QApplicationProcess():
    from qgis.PyQt.QtWidgets import QApplication
    QApplication.processEvents()


def pedir_configuracao_inicial(parent):
    """Chamado ao abrir o QGIS: se não há conta configurada, abre o assistente uma vez."""
    if QgsSettings().value(CFG_ADIADO, False, type=bool) or config_ia.configurada():
        return
    dlg = ConfigIADialog(parent, primeira_vez=True)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        QgsSettings().setValue(CFG_ADIADO, True)


# ====================================================================== tarefas
class _Sinal(QObject):
    msg = pyqtSignal(str)


def camadas_do_projeto():
    """Camadas vetoriais do projeto no formato que o checklist usa."""
    out = []
    for lyr in QgsProject.instance().mapLayers().values():
        if not isinstance(lyr, QgsVectorLayer) or not lyr.isValid():
            continue
        tabela = ""
        try:
            partes = QgsProviderRegistry.instance().decodeUri(lyr.providerType(), lyr.source())
            tabela = partes.get("layerName") or os.path.splitext(
                os.path.basename(partes.get("path", "")))[0]
        except Exception:
            pass
        gt = QgsWkbTypes.geometryType(lyr.wkbType())
        geo = {QgsWkbTypes.GeometryType.PointGeometry: "ponto",
               QgsWkbTypes.GeometryType.LineGeometry: "linha",
               QgsWkbTypes.GeometryType.PolygonGeometry: "poligono"}.get(gt, "tabela")
        out.append({"id": lyr.id(), "nome": lyr.name(), "tabela": tabela, "geometria": geo,
                    "campos": [f.name() for f in lyr.fields()],
                    "feicoes": max(lyr.featureCount(), 0)})
    return out


def contar_preenchidos(id_camada, campos, limite=200_000):
    lyr = QgsProject.instance().mapLayer(id_camada)
    if not lyr or not campos:
        return {}
    idx = [lyr.fields().indexOf(c) for c in campos]
    req = QgsFeatureRequest().setFlags(QgsFeatureRequest.Flag.NoGeometry)
    req.setSubsetOfAttributes([i for i in idx if i >= 0])
    req.setLimit(limite)
    cont = {c: 0 for c in campos}
    for f in lyr.getFeatures(req):
        for c, i in zip(campos, idx):
            if i < 0:
                continue
            v = f.attribute(i)
            if v is not None and str(v).strip() not in ("", "NULL") and not (
                    hasattr(v, "isNull") and v.isNull()):
                cont[c] += 1
    return cont


# ====================================================================== janela
class JanelaPlanos(QDialog):
    def __init__(self, iface, servidor_mcp=None, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.servidor_mcp = servidor_mcp      # função que devolve o McpSocketServer do plugin
        self._processo = None
        self._arq_mcp = None
        self._buf = b""
        self._fim_info = None
        self.setWindowTitle("Planos do Contrato")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)
        self.resize(1000, 680)
        self.perfil = None
        self.estado = {"documentos": [], "servicos": [], "manuais": {}}
        self.docs_lidos = {}
        self._tarefa = None
        self._sinal = _Sinal()
        self._sinal.msg.connect(self._progresso)
        self._montar()
        self._abrir_pasta(self._pasta_inicial())
        ferramentas.JANELA = self
        self._timer_perfil = QTimer(self)
        self._timer_perfil.setSingleShot(True)
        self._timer_perfil.timeout.connect(self._recarregar_perfil_silencioso)
        QgsProject.instance().layersAdded.connect(self._agendar_checklist)
        QgsProject.instance().layersRemoved.connect(self._agendar_checklist)

    # ------------------------------------------------------------ montagem
    def _montar(self):
        lay = QVBoxLayout(self)
        topo = QHBoxLayout()
        topo.addWidget(QLabel("Pasta do contrato:"))
        self.ed_pasta = QLineEdit()
        self.ed_pasta.setReadOnly(True)
        topo.addWidget(self.ed_pasta, 1)
        bt = QPushButton("Escolher…")
        bt.clicked.connect(self._escolher_pasta)
        topo.addWidget(bt)
        self.lb_ia = QLabel()
        topo.addWidget(self.lb_ia)
        bt = QPushButton("Configurar IA")
        bt.clicked.connect(self._configurar_ia)
        topo.addWidget(bt)
        lay.addLayout(topo)

        self.abas = QTabWidget()
        lay.addWidget(self.abas, 1)
        self.abas.addTab(self._aba_documentos(), "1. Documentos")
        self.abas.addTab(self._aba_requisitos(), "2. Requisitos")
        self.abas.addTab(self._aba_checklist(), "3. O que falta")
        from .abas_plano import AbaPlano, AbaValidar
        self.aba_plano = AbaPlano(self)
        self.aba_validar = AbaValidar(self)
        from .abas_frota import AbaFrota
        from .abas_importar import AbaImportar
        self.aba_frota = AbaFrota(self)
        self.aba_importar = AbaImportar(self)
        self.abas.addTab(self.aba_plano, "4. Plano")
        self.abas.addTab(self.aba_importar, "5. Trazer dados")
        self.abas.addTab(self.aba_frota, "6. Frota e equipe")
        self.abas.addTab(self.aba_validar, "7. Validar")
        self.abas.currentChanged.connect(self._aba_mudou)

        rod = QHBoxLayout()
        self.lb_status = QLabel("")
        rod.addWidget(self.lb_status, 1)
        self.bt_cancelar = QPushButton("Cancelar")
        self.bt_cancelar.setVisible(False)
        self.bt_cancelar.clicked.connect(self._cancelar)
        rod.addWidget(self.bt_cancelar)
        lay.addLayout(rod)
        self._mostrar_ia()

    def _aba_documentos(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("Coloque o edital, os anexos e as especificações técnicas (PDF, DOCX "
                             "ou TXT). Se as especificações vierem dentro do edital, basta o edital."))
        self.lista_docs = QListWidget()
        lay.addWidget(self.lista_docs, 1)
        bts = QHBoxLayout()
        for txt, fn in (("Adicionar documentos…", self._adicionar_docs),
                        ("Remover", self._remover_doc)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            bts.addWidget(b)
        bts.addStretch()
        self.cb_pronto = QComboBox()
        self.cb_pronto.addItem("Usar perfil pronto…")
        self.cb_pronto.addItems(list(perfil.PERFIS_PRONTOS))
        self.cb_pronto.activated.connect(self._usar_pronto)
        bts.addWidget(self.cb_pronto)
        self.bt_ler = QPushButton("Ler com IA")
        f = QFont()
        f.setBold(True)
        self.bt_ler.setFont(f)
        self.bt_ler.clicked.connect(self._ler_com_ia)
        bts.addWidget(self.bt_ler)
        lay.addLayout(bts)
        return w

    def _aba_requisitos(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.lb_resumo = QLabel("Nenhum perfil ainda. Leia os documentos com a IA na aba 1.")
        self.lb_resumo.setWordWrap(True)
        lay.addWidget(self.lb_resumo)
        lay.addWidget(QLabel("<small>Marque os serviços que você vai planejar: o checklist "
                             "considera só eles.</small>"))
        self.arv_req = QTreeWidget()
        self.arv_req.setHeaderLabels(["Item", "Detalhe", "Fonte"])
        self.arv_req.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.arv_req.itemChanged.connect(self._servico_marcado)
        lay.addWidget(self.arv_req, 1)
        bts = QHBoxLayout()
        bts.addStretch()
        b = QPushButton("Abrir contrato.json")
        b.setToolTip("Para corrigir o perfil à mão. Depois clique em Recarregar.")
        b.clicked.connect(self._abrir_json)
        bts.addWidget(b)
        b = QPushButton("Recarregar")
        b.clicked.connect(self._recarregar_perfil)
        bts.addWidget(b)
        lay.addLayout(bts)
        return w

    def _aba_checklist(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.lb_placar = QLabel("")
        self.lb_placar.setWordWrap(True)
        lay.addWidget(self.lb_placar)
        self.arv_chk = QTreeWidget()
        self.arv_chk.setHeaderLabels(["Item", "Situação", "O que fazer", "Fonte"])
        self.arv_chk.setWordWrap(True)
        self.arv_chk.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.arv_chk.setColumnWidth(0, 340)
        self.arv_chk.setColumnWidth(1, 330)
        self.arv_chk.itemChanged.connect(self._manual_marcado)
        lay.addWidget(self.arv_chk, 1)
        bts = QHBoxLayout()
        lb = QLabel("<small>🟢 tem · 🟡 incompleto · 🔴 falta · ⚪ confirmar (marque a caixa "
                    "quando tiver) · 📄 será gerado</small>")
        bts.addWidget(lb, 1)
        b = QPushButton("Atualizar")
        b.clicked.connect(self._atualizar_checklist)
        bts.addWidget(b)
        lay.addLayout(bts)
        return w

    def _aba_mudou(self, i):
        if i == 2:
            self._atualizar_checklist()
        elif i == 3:
            self.aba_plano.atualizar()
        elif i == 4:
            self.aba_importar.atualizar()
        elif i == 5:
            self.aba_frota.atualizar()
        elif i == 6:
            self.aba_validar.atualizar()

    def _aba_futura(self, titulo, texto):
        w = QWidget()
        lay = QVBoxLayout(w)
        lb = QLabel(f"<h3>{titulo}</h3><p>{texto}</p>")
        lb.setWordWrap(True)
        lay.addWidget(lb)
        lay.addStretch()
        return w

    # ------------------------------------------------------------ pasta e estado
    def _pasta_inicial(self):
        prj = QgsProject.instance()
        p = prj.readEntry("qgis_ia", "pasta_contrato", "")[0]
        if p and os.path.isdir(p):
            return p
        p = QgsSettings().value(CFG_PASTA, "")
        if p and os.path.isdir(p):
            return p
        base = prj.homePath() or os.path.join(os.path.expanduser("~"), "Documents")
        return os.path.join(base, "Contrato")

    def _escolher_pasta(self):
        p = QFileDialog.getExistingDirectory(self, "Pasta do contrato", self.pasta)
        if p:
            self._abrir_pasta(p)

    def _abrir_pasta(self, p):
        self.pasta = os.path.normpath(p)
        self.ed_pasta.setText(self.pasta)
        QgsSettings().setValue(CFG_PASTA, self.pasta)
        QgsProject.instance().writeEntry("qgis_ia", "pasta_contrato", self.pasta)
        self.estado = {"documentos": [], "servicos": [], "manuais": {}, "planos": []}
        arq = os.path.join(self.pasta, ARQ_ESTADO)
        if os.path.exists(arq):
            try:
                with open(arq, encoding="utf-8") as f:
                    self.estado.update(json.load(f))
            except (OSError, ValueError):
                pass
        self.perfil = None
        arq = os.path.join(self.pasta, ARQ_PERFIL)
        if os.path.exists(arq):
            try:
                self.perfil = perfil.carregar(arq)
            except (OSError, ValueError) as e:
                self._status(f"contrato.json com erro: {e}")
        self.docs_lidos = {}
        self._mostrar_docs()
        self._ler_docs_em_segundo_plano()
        self._mostrar_perfil()
        self.aba_plano.atualizar()
        self.aba_validar.atualizar()
        self.aba_importar.info = None

    def _salvar_estado(self):
        os.makedirs(self.pasta, exist_ok=True)
        with open(os.path.join(self.pasta, ARQ_ESTADO), "w", encoding="utf-8") as f:
            json.dump(self.estado, f, ensure_ascii=False, indent=2)

    def _salvar_perfil(self):
        perfil.salvar(self.perfil, os.path.join(self.pasta, ARQ_PERFIL))

    # ------------------------------------------------------------ IA
    def _mostrar_ia(self, atualizar=False):
        m = config_ia.motor(atualizar)
        if m == "claude":
            self.lb_ia.setText("IA: <span style='color:#080'>conta Claude (MCP)</span>")
        elif m == "api":
            self.lb_ia.setText("IA: <span style='color:#080'>chave de API</span>")
        else:
            self.lb_ia.setText("IA: <span style='color:#c00'>não configurada</span>")

    def _configurar_ia(self):
        ConfigIADialog(self).exec()
        self._mostrar_ia(atualizar=True)

    # ------------------------------------------------------------ documentos
    def _mostrar_docs(self):
        self.lista_docs.clear()
        total = 0
        for c in self.estado["documentos"]:
            d = self.docs_lidos.get(c)
            if d:
                t = documentos.tokens_estimados([d])
                total += t
                txt = f"{os.path.basename(c)} — {len(d['paginas'])} páginas, ~{t // 1000} mil tokens"
                aviso = documentos.aviso_sem_texto(d)
                if aviso:
                    txt += "  ⚠ escaneado?"
            elif not os.path.exists(c):
                txt = f"{os.path.basename(c)} — ⚠ arquivo não encontrado"
            else:
                txt = f"{os.path.basename(c)} — lendo…"
            it = QListWidgetItem(txt)
            it.setData(Qt.ItemDataRole.UserRole, c)
            it.setToolTip(c)
            self.lista_docs.addItem(it)
        if self.estado["documentos"] and len(self.docs_lidos) == len(self.estado["documentos"]):
            _, custo = extracao.estimativa(list(self.docs_lidos.values()))
            self._status(f"{len(self.docs_lidos)} documento(s), ~{total // 1000} mil tokens. "
                         f"Leitura pela IA: cerca de US$ {custo:.2f}.")

    def _adicionar_docs(self):
        arqs, _ = QFileDialog.getOpenFileNames(
            self, "Documentos do contrato", self.pasta if os.path.isdir(self.pasta) else "",
            "Documentos (*.pdf *.docx *.txt)")
        novos = [os.path.normpath(a) for a in arqs
                 if os.path.normpath(a) not in self.estado["documentos"]]
        if not novos:
            return
        self.estado["documentos"] += novos
        self._salvar_estado()
        self._mostrar_docs()
        self._ler_docs_em_segundo_plano()

    def _remover_doc(self):
        it = self.lista_docs.currentItem()
        if not it:
            return
        c = it.data(Qt.ItemDataRole.UserRole)
        self.estado["documentos"].remove(c)
        self.docs_lidos.pop(c, None)
        self._salvar_estado()
        self._mostrar_docs()

    def _ler_docs_em_segundo_plano(self, depois=None):
        faltam = [c for c in self.estado["documentos"]
                  if c not in self.docs_lidos and os.path.exists(c)]
        if not faltam:
            if depois:
                depois()
            return
        cache = os.path.join(self.pasta, PASTA_TEXTOS)
        sinal = self._sinal

        def trabalho(task):
            lidos, erros = {}, []
            for i, c in enumerate(faltam):
                if task.isCanceled():
                    break
                sinal.msg.emit(f"Lendo {os.path.basename(c)} ({i + 1}/{len(faltam)})…")
                try:
                    lidos[c] = documentos.ler(c, cache)
                except Exception as e:
                    erros.append(f"{os.path.basename(c)}: {e}")
                task.setProgress(100 * (i + 1) / len(faltam))
            return lidos, erros

        def fim(exc, res=None):
            self._ocupado(False)
            if exc or not res:
                self._status(f"Erro ao ler documentos: {exc}")
                return
            lidos, erros = res
            self.docs_lidos.update(lidos)
            self._mostrar_docs()
            if erros:
                QMessageBox.warning(self, "Documentos", "\n".join(erros))
            avisos = [documentos.aviso_sem_texto(d) for d in lidos.values()]
            avisos = [a for a in avisos if a]
            if avisos:
                QMessageBox.warning(self, "Documentos", "\n\n".join(avisos))
            if depois:
                depois()

        self._rodar(QgsTask.fromFunction("Lendo documentos do contrato", trabalho, on_finished=fim))

    def _ler_com_ia(self):
        if not self.estado["documentos"]:
            QMessageBox.information(self, "Ler com IA", "Adicione o edital e as especificações primeiro.")
            return
        if not config_ia.configurada():
            self._configurar_ia()
            if not config_ia.configurada():
                return
        if len(self.docs_lidos) < len([c for c in self.estado["documentos"] if os.path.exists(c)]):
            self._ler_docs_em_segundo_plano(depois=self._ler_com_ia)
            return
        docs = [self.docs_lidos[c] for c in self.estado["documentos"] if c in self.docs_lidos]
        if config_ia.motor() == "claude":
            self._ler_com_claude(docs)
            return
        tokens, custo = extracao.estimativa(docs)
        aviso = ""
        if self.perfil:
            aviso = "\n\nO perfil atual (contrato.json) será substituído; uma cópia fica em contrato_anterior.json."
        r = QMessageBox.question(
            self, "Ler com IA",
            f"A IA vai ler {len(docs)} documento(s) (~{tokens // 1000} mil tokens).\n"
            f"Custo estimado: US$ {custo:.2f}. Leva de 2 a 10 minutos.{aviso}\n\nContinuar?")
        if r != QMessageBox.StandardButton.Yes:
            return
        k = config_ia.chave()
        sinal = self._sinal

        def trabalho(task):
            return extracao.extrair(docs, k, progresso=sinal.msg.emit,
                                    cancelado=task.isCanceled)

        def fim(exc, res=None):
            self._ocupado(False)
            if exc:
                QMessageBox.warning(self, "Ler com IA", str(exc))
                self._status(str(exc))
                return
            if not res:
                self._status("Leitura cancelada.")
                return
            novo, info = res
            arq = os.path.join(self.pasta, ARQ_PERFIL)
            if os.path.exists(arq):
                os.replace(arq, os.path.join(self.pasta, "contrato_anterior.json"))
            self.perfil = novo
            self.estado["servicos"] = []
            self._salvar_perfil()
            self._salvar_estado()
            self._mostrar_perfil()
            self.abas.setCurrentIndex(1)
            self._status(f"Perfil pronto: {perfil.resumo(novo)}. Custo: US$ {info['custo_usd']:.2f}.")

        self._rodar(QgsTask.fromFunction("Lendo o edital com IA", trabalho, on_finished=fim))

    # ------------------------------------------------------------ leitura pela conta Claude
    def _ler_com_claude(self, docs):
        tokens = documentos.tokens_estimados(docs)
        aviso = ("\n\nO perfil atual (contrato.json) será substituído; uma cópia fica em "
                 "contrato_anterior.json.") if self.perfil else ""
        r = QMessageBox.question(
            self, "Ler com IA",
            f"O Claude (sua conta claude.ai, pelo Claude Code) vai ler {len(docs)} documento(s) "
            f"(~{tokens // 1000} mil tokens) pelo MCP do QGIS e montar o perfil do contrato.\n"
            f"Usa o limite da sua assinatura, não créditos da API. Leva de 5 a 20 minutos.{aviso}"
            "\n\nContinuar?")
        if r != QMessageBox.StandardButton.Yes:
            return
        srv = self.servidor_mcp() if self.servidor_mcp else None
        if srv is None or not (srv.is_running() or srv.start()):
            QMessageBox.warning(self, "Ler com IA", "Não consegui iniciar o servidor MCP do QGIS_IA.")
            return
        if srv.read_only:
            QMessageBox.warning(self, "Ler com IA", "O servidor MCP está em modo somente leitura; "
                                "desligue esse modo no painel QGIS_IA para o Claude gravar o perfil.")
            return
        exe = config_ia.claude_code()["exe"]
        os.makedirs(self.pasta, exist_ok=True)
        self._arq_mcp = os.path.join(self.pasta, ".mcp_planos.json")
        with open(self._arq_mcp, "w", encoding="utf-8") as f:
            json.dump(leitor_claude.config_mcp(srv.python_path(), srv.bridge_path(), "127.0.0.1",
                                               srv.port, srv.token), f)
        proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            env.remove(k)
        proc.setProcessEnvironment(env)
        proc.setWorkingDirectory(self.pasta)
        proc.readyReadStandardOutput.connect(self._saida_claude)
        proc.finished.connect(self._fim_claude)
        proc.errorOccurred.connect(self._erro_claude)
        self._processo = proc
        self._buf = b""
        self._fim_info = None
        self._ocupado(True)
        self._status("Iniciando o Claude…")
        args = leitor_claude.argumentos(self._arq_mcp)
        if exe.lower().endswith((".cmd", ".bat")):      # instalação via npm
            exe, args = "cmd", ["/c", exe] + args
        proc.start(exe, args)

    def _saida_claude(self):
        if not self._processo:
            return
        self._buf += bytes(self._processo.readAllStandardOutput())
        while b"\n" in self._buf:
            linha, self._buf = self._buf.split(b"\n", 1)
            ev = leitor_claude.interpretar(linha.decode("utf-8", "replace"))
            if not ev:
                continue
            if ev["tipo"] == "passo":
                self._status("Claude: " + ev["texto"] + "…")
            else:
                self._fim_info = ev

    def _erro_claude(self, erro):
        if erro == QProcess.ProcessError.FailedToStart:
            self._fim_info = {"tipo": "fim", "ok": False,
                              "texto": "Não consegui abrir o Claude Code. Veja Configurar IA."}
            self._fim_claude()

    def _fim_claude(self, *_):
        if not self._processo:
            return
        self._saida_claude()
        erro = bytes(self._processo.readAllStandardError()).decode("utf-8", "replace").strip()
        self._processo = None
        self._ocupado(False)
        if self._arq_mcp and os.path.exists(self._arq_mcp):
            try:
                os.remove(self._arq_mcp)      # tem o token do servidor
            except OSError:
                pass
        info = self._fim_info or {"ok": False, "texto": erro[-600:] or "O Claude parou sem resposta."}
        self._recarregar_perfil_silencioso()
        if info.get("ok"):
            self.estado["servicos"] = []
            self._salvar_estado()
            self.abas.setCurrentIndex(1)
            self._status("Perfil montado pelo Claude: "
                         + (perfil.resumo(self.perfil) if self.perfil else ""))
            QMessageBox.information(self, "Ler com IA", info["texto"] or "Perfil montado.")
        else:
            self._status("A leitura não terminou.")
            QMessageBox.warning(self, "Ler com IA", info["texto"])

    def perfil_alterado_externamente(self):
        """O Claude gravou uma seção pelo MCP: atualiza a janela (agrupa gravações seguidas)."""
        self._timer_perfil.start(400)

    def _recarregar_perfil_silencioso(self):
        arq = os.path.join(self.pasta, ARQ_PERFIL)
        if os.path.exists(arq):
            try:
                self.perfil = perfil.carregar(arq)
            except (OSError, ValueError):
                return
            self._mostrar_perfil()
            if self.abas.currentIndex() == 2:
                self._atualizar_checklist()

    def _usar_pronto(self, i):
        if i <= 0:
            return
        nome = self.cb_pronto.itemText(i)
        self.cb_pronto.setCurrentIndex(0)
        if self.perfil and QMessageBox.question(
                self, "Perfil pronto", f"Substituir o perfil atual por '{nome}'?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.perfil = perfil.PERFIS_PRONTOS[nome]()
        self.estado["servicos"] = []
        self._salvar_perfil()
        self._salvar_estado()
        self._mostrar_perfil()
        self.abas.setCurrentIndex(1)
        self._status(f"Perfil '{nome}' carregado: {perfil.resumo(self.perfil)}.")

    # ------------------------------------------------------------ requisitos
    def _mostrar_perfil(self):
        a = self.arv_req
        a.blockSignals(True)
        a.clear()
        p = self.perfil
        if not p:
            self.lb_resumo.setText("Nenhum perfil ainda. Leia os documentos com a IA na aba 1 "
                                   "ou use um perfil pronto.")
            a.blockSignals(False)
            return
        c = p["contrato"]
        self.lb_resumo.setText(f"<b>{c.get('titulo') or 'Contrato'}</b> — {c.get('orgao', '')}<br>"
                               f"{c.get('objeto', '')}<br><small>{perfil.resumo(p)}</small>")

        def no(pai, texto, detalhe="", fonte=""):
            it = QTreeWidgetItem(pai, [texto, detalhe, fonte])
            it.setToolTip(1, detalhe)
            return it

        r = no(a, "Contrato")
        for k, v in c.items():
            if v:
                no(r, k.replace("_", " ").capitalize(), str(v))
        r.setExpanded(True)

        r = no(a, f"Documentos ({len(p['documentos'])})")
        for d in p["documentos"]:
            no(r, d["nome"], f"{d['tipo']} — {d['resumo']}"
               + (" · tem especificações" if d.get("contem_especificacoes") else ""))

        r = no(a, f"Lotes ({len(p['lotes'])})")
        for l in p["lotes"]:
            no(r, l["nome"] or l["codigo"], ", ".join(l["regioes"]), perfil.fonte_txt(l))

        sel = set(self.estado.get("servicos") or [])
        r = no(a, f"Serviços ({len(p['servicos'])})")
        for s in p["servicos"]:
            it = no(r, f"{s['codigo']} {s['nome']}",
                    " · ".join(x for x in (s.get("sigla"), s.get("frequencia"),
                                            "sob demanda" if s.get("sob_demanda") else "",
                                            ("lotes " + ", ".join(s["lotes"])) if s.get("lotes") else "")
                               if x),
                    perfil.fonte_txt(s))
            it.setFlags(it.flags() | _CHECK)
            it.setCheckState(0, _MARCADO if s["codigo"] in sel else _DESMARCADO)
            it.setData(0, Qt.ItemDataRole.UserRole, ("servico", s["codigo"]))
        r.setExpanded(True)

        r = no(a, f"Camadas do plano ({len(p['camadas'])})")
        for cam in p["camadas"]:
            it = no(r, cam["nome"], f"{cam['geometria']} · {len(cam['campos'])} campos"
                    + (f" · {', '.join(cam['servicos'])}" if cam.get("servicos") else "")
                    + (f" · {cam['descricao']}" if cam.get("descricao") else ""),
                    perfil.fonte_txt(cam))
            for f in cam["campos"]:
                det = f"{f['tipo']}{' · obrigatório' if f.get('obrigatorio') else ''}"
                if f.get("descricao"):
                    det += f" · {f['descricao']}"
                if f.get("valores_permitidos"):
                    vals = f["valores_permitidos"]
                    det += " · valores: " + "; ".join(vals[:6]) + ("…" if len(vals) > 6 else "")
                if str(f.get("valor_padrao") or "").strip():
                    det += f" · padrão (sem informação): {f['valor_padrao']}"
                no(it, f["nome"], det)

        for chave, titulo in (("entregaveis", "Entregáveis"), ("insumos", "Insumos"),
                              ("regras", "Regras")):
            r = no(a, f"{titulo} ({len(p[chave])})")
            for x in p[chave]:
                nome = x.get("nome") or x.get("descricao", "")
                det = x.get("descricao", "") if x.get("nome") else x.get("tipo", "")
                if chave == "entregaveis":
                    det = f"{x['formato']} · {x['descricao']}" + (f" · prazo {x['prazo']}" if x.get("prazo") else "")
                no(r, nome, det, perfil.fonte_txt(x))

        rec = p.get("recursos") or []
        r = no(a, f"Frota e pessoal do edital ({len(rec)})")
        grupos = {}
        for x in rec:
            chave = f"{x['servico']} · lote {x['lote'] or 'todos'}"
            g = grupos.get(chave) or no(r, chave, "")
            grupos[chave] = g
            ic = "🚛" if x["categoria"] == "equipamento" else "👷"
            no(g, f"{ic} {x['nome']}",
               f"diurno {x['diurno']} · noturno {x['noturno']}"
               + (" · domingo" if x.get("domingo") else "")
               + (f" · código no plano {x['codigo_no_plano']}" if x.get("codigo_no_plano") else ""),
               perfil.fonte_txt(x))
        eqs = p.get("equipes") or []
        r = no(a, f"Equipes padrão ({len(eqs)})")
        for x in eqs:
            no(r, f"{x['servico']} · {x['nome']}",
               f"{x['equipamento']}: " + ", ".join(f"{f['quantidade']} {f['funcao']}"
                                                   for f in x["funcoes"]),
               perfil.fonte_txt(x))
        r = no(a, f"Pendências ({len(p['pendencias'])})")
        for x in p["pendencias"]:
            no(r, x)
        r.setExpanded(True)
        a.blockSignals(False)

    def _servico_marcado(self, it, col):
        dado = it.data(0, Qt.ItemDataRole.UserRole)
        if not dado or dado[0] != "servico":
            return
        sel = set(self.estado.get("servicos") or [])
        if it.checkState(0) == _MARCADO:
            sel.add(dado[1])
        else:
            sel.discard(dado[1])
        ordem = [s["codigo"] for s in self.perfil["servicos"]]
        self.estado["servicos"] = [s for s in ordem if s in sel]
        self._salvar_estado()

    def _abrir_json(self):
        arq = os.path.join(self.pasta, ARQ_PERFIL)
        if os.path.exists(arq):
            QDesktopServices.openUrl(QUrl.fromLocalFile(arq))

    def _recarregar_perfil(self):
        arq = os.path.join(self.pasta, ARQ_PERFIL)
        if not os.path.exists(arq):
            return
        try:
            self.perfil = perfil.carregar(arq)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "contrato.json", f"Arquivo com erro: {e}")
            return
        self._mostrar_perfil()
        self._status("Perfil recarregado.")

    # ------------------------------------------------------------ checklist
    def _agendar_checklist(self, *_):
        if self.isVisible() and self.abas.currentIndex() == 2:
            QTimer.singleShot(300, self._atualizar_checklist)

    def _atualizar_checklist(self):
        a = self.arv_chk
        a.blockSignals(True)
        a.clear()
        if not self.perfil:
            self.lb_placar.setText("Sem perfil do contrato. Leia os documentos na aba 1.")
            a.blockSignals(False)
            return
        itens = checklist.gerar(self.perfil, camadas_do_projeto(), self.estado,
                                contar=contar_preenchidos)
        grupos = {}
        for i in itens:
            pai = grupos.get(i["grupo"])
            if pai is None:
                pai = grupos[i["grupo"]] = QTreeWidgetItem(a, [i["grupo"]])
                f = pai.font(0)
                f.setBold(True)
                pai.setFont(0, f)
                pai.setExpanded(True)
            rot = ROTULO[i["status"]]
            it = QTreeWidgetItem(pai, [f"{ICONE[i['status']]} {i['titulo']}",
                                       (f"{rot}: " if rot else "") + i["detalhe"], i["acao"],
                                       i["fonte"]])
            for col in range(4):
                it.setToolTip(col, it.text(col))
            chave = i["chave"]
            pode_marcar = (chave.startswith("insumo|") or chave.startswith("pendencia|")) and \
                i["status"] in (checklist.CONFIRMAR, checklist.FALTA) or \
                chave in self.estado.get("manuais", {})
            if pode_marcar:
                it.setFlags(it.flags() | _CHECK)
                it.setCheckState(0, _MARCADO if self.estado["manuais"].get(chave) else _DESMARCADO)
                it.setData(0, Qt.ItemDataRole.UserRole, chave)
        n = checklist.placar(itens)
        sel = self.estado.get("servicos") or []
        escopo = ("serviços " + ", ".join(sel)) if sel else "todos os serviços (marque na aba 2 para filtrar)"
        pronto = checklist.pronto(itens)
        self.lb_placar.setText(
            f"<b>{'✅ Pronto para gerar o plano' if pronto else '⛔ Ainda falta coisa para gerar o plano'}</b>"
            f" — {escopo}<br>🟢 {n['ok']} tem · 🟡 {n['parcial']} incompletos · 🔴 {n['falta']} faltam"
            f" · ⚪ {n['confirmar']} a confirmar")
        a.blockSignals(False)

    def _manual_marcado(self, it, col):
        chave = it.data(0, Qt.ItemDataRole.UserRole)
        if not chave:
            return
        if it.checkState(0) == _MARCADO:
            self.estado["manuais"][chave] = True
        else:
            self.estado["manuais"].pop(chave, None)
        self._salvar_estado()
        QTimer.singleShot(0, self._atualizar_checklist)

    # ------------------------------------------------------------ tarefas
    def _rodar(self, tarefa):
        self._tarefa = tarefa
        self._ocupado(True)
        QgsApplication.taskManager().addTask(tarefa)

    def _cancelar(self):
        if self._tarefa:
            self._tarefa.cancel()
            self._status("Cancelando…")
        if self._processo:
            self._fim_info = {"tipo": "fim", "ok": False, "texto": "Leitura cancelada."}
            self._processo.kill()

    def _ocupado(self, sim):
        self.bt_ler.setEnabled(not sim)
        self.bt_cancelar.setVisible(sim)
        if not sim:
            self._tarefa = None

    def _progresso(self, txt):
        self._status(txt)

    def _status(self, txt):
        self.lb_status.setText(txt)

    def desligar(self):
        """Chamado ao descarregar o plugin."""
        if ferramentas.JANELA is self:
            ferramentas.JANELA = None
        if self._processo:
            self._processo.kill()
        try:
            QgsProject.instance().layersAdded.disconnect(self._agendar_checklist)
            QgsProject.instance().layersRemoved.disconnect(self._agendar_checklist)
        except TypeError:
            pass
        if self._tarefa:
            self._tarefa.cancel()
