# -*- coding: utf-8 -*-
"""Aba "Trazer dados" (2.2): liga uma camada sua (shapefile, GeoPackage, .gdb, GeoJSON, KML,
CSV…) a uma camada do plano e copia as feições, convertendo valores e reprojetando."""
import os

from qgis.core import QgsProject, QgsProviderRegistry, QgsTask, QgsVectorLayer
from qgis.PyQt.QtCore import QProcess, QProcessEnvironment, Qt, QTimer
from qgis.PyQt.QtGui import QGuiApplication
from qgis.PyQt.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog,
                                 QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPlainTextEdit,
                                 QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                                 QVBoxLayout, QWidget)

from . import config_ia, estrutura, importacao as I
from .abas_plano import _escolher_plano, carregar_camada

_PAPEL = Qt.ItemDataRole.UserRole
_COMO = {"nome": "✓ pelo nome", "parecido": "≈ nome parecido", "ia": "🤖 Claude",
         "manual": "✋ você"}
_TEMPO_IA = 240_000   # ms


def _fontes_do_projeto():
    """(rótulo, caminho, camada) das camadas vetoriais de arquivo abertas no projeto."""
    out = []
    for lyr in QgsProject.instance().mapLayers().values():
        if not isinstance(lyr, QgsVectorLayer) or lyr.providerType() != "ogr":
            continue
        try:
            partes = QgsProviderRegistry.instance().decodeUri("ogr", lyr.source())
        except Exception:
            continue
        caminho = partes.get("path") or ""
        if not caminho or not os.path.exists(caminho):
            continue
        camada = partes.get("layerName") or os.path.splitext(os.path.basename(caminho))[0]
        out.append((f"{lyr.name()}  (projeto: {os.path.basename(caminho)})", os.path.normpath(caminho),
                    camada))
    return sorted(out)


def chave_fonte(caminho, camada):
    """Dado do item da lista de origens (texto: o Qt não compara tuplas em findData)."""
    return f"{os.path.normpath(caminho)}|{camada}"


class AbaImportar(QWidget):
    def __init__(self, janela):
        super().__init__()
        self.j = janela
        self.info = None
        self._proc = None
        self._carregando = False
        lay = QVBoxLayout(self)
        lb = QLabel("Traga os seus dados (plano atual em outro formato, levantamentos) para uma "
                    "camada do plano. Os campos são ligados pelo nome; o Claude sugere o resto. "
                    "Na cópia, os valores são convertidos para os códigos do contrato e a "
                    "geometria é reprojetada.")
        lb.setWordWrap(True)
        lay.addWidget(lb)

        linha = QHBoxLayout()
        linha.addWidget(QLabel("De:"))
        self.cb_origem = QComboBox()
        self.cb_origem.currentIndexChanged.connect(self._montar)
        linha.addWidget(self.cb_origem, 1)
        b = QPushButton("Arquivo…")
        b.setToolTip("Shapefile, GeoPackage, File Geodatabase, GeoJSON, KML, CSV…")
        b.clicked.connect(self._arquivo)
        linha.addWidget(b)
        lay.addLayout(linha)

        linha = QHBoxLayout()
        linha.addWidget(QLabel("Para:"))
        self.cb_plano = QComboBox()
        self.cb_plano.currentIndexChanged.connect(self._plano_mudou)
        linha.addWidget(self.cb_plano, 1)
        b = QPushButton("Plano novo…")
        b.setToolTip("Cria um plano vazio (.gdb ou .gpkg) com as camadas e campos do perfil.")
        b.clicked.connect(self._plano_novo)
        linha.addWidget(b)
        linha.addWidget(QLabel("camada:"))
        self.cb_destino = QComboBox()
        self.cb_destino.currentIndexChanged.connect(self._destino_mudou)
        linha.addWidget(self.cb_destino, 1)
        lay.addLayout(linha)

        div = QSplitter(Qt.Orientation.Vertical)
        self.tab = QTableWidget(0, 5)
        self.tab.setHorizontalHeaderLabels(["Campo do plano", "Descrição", "Vem de (seus dados)",
                                            "Valor fixo", "Situação"])
        h = self.tab.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.tab.setColumnWidth(2, 200)
        self.tab.setColumnWidth(3, 150)
        self.tab.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tab.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tab.verticalHeader().setVisible(False)
        self.tab.itemSelectionChanged.connect(self._mostrar_valores)
        div.addWidget(self.tab)

        baixo = QWidget()
        lb2 = QVBoxLayout(baixo)
        lb2.setContentsMargins(0, 0, 0, 0)
        self.lb_valores = QLabel("<small>Selecione um campo com valores permitidos para ligar "
                                 "os valores.</small>")
        lb2.addWidget(self.lb_valores)
        self.tab_val = QTableWidget(0, 3)
        self.tab_val.setHorizontalHeaderLabels(["Valor nos seus dados", "Registros", "Vai para"])
        hv = self.tab_val.horizontalHeader()
        hv.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hv.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hv.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tab_val.verticalHeader().setVisible(False)
        lb2.addWidget(self.tab_val)
        div.addWidget(baixo)
        self.txt = QPlainTextEdit()
        self.txt.setReadOnly(True)
        self.txt.setPlaceholderText("Resultado da prévia e da importação.")
        div.addWidget(self.txt)
        div.setSizes([300, 150, 120])
        lay.addWidget(div, 1)

        linha = QHBoxLayout()
        self.ck_subst = QCheckBox("Substituir o que já está na camada")
        self.ck_subst.setToolTip("Desmarcado: as feições são acrescentadas às que já existem.")
        self.ck_subst.toggled.connect(self._subst)
        linha.addWidget(self.ck_subst)
        linha.addStretch()
        self.bt_ia = QPushButton("Sugerir com Claude")
        self.bt_ia.clicked.connect(self._sugerir)
        linha.addWidget(self.bt_ia)
        self.bt_previa = QPushButton("Prévia")
        self.bt_previa.clicked.connect(lambda: self._executar(False))
        linha.addWidget(self.bt_previa)
        self.bt_importar = QPushButton("Importar")
        self.bt_importar.clicked.connect(lambda: self._executar(True))
        linha.addWidget(self.bt_importar)
        lay.addLayout(linha)
        self._botoes()

    # ------------------------------------------------------------ listas
    def atualizar(self):
        self._carregando = True
        atual_o = self.cb_origem.currentData(_PAPEL)
        self.cb_origem.clear()
        self.cb_origem.addItem("Escolha os seus dados…", None)
        vistos = set()
        fontes = []
        for caminho, camada in [tuple(x) for x in self.j.estado.get("fontes_importacao", [])]:
            if os.path.exists(caminho):
                fontes.append((f"{camada}  ({os.path.basename(caminho)})", caminho, camada))
        for rot, caminho, camada in fontes + _fontes_do_projeto():
            k = (os.path.normcase(caminho), camada)
            if k in vistos or any(I._mesma(caminho, p) for p in self.j.aba_plano.planos()):
                continue
            vistos.add(k)
            self.cb_origem.addItem(rot, chave_fonte(caminho, camada))
        if atual_o:
            i = self.cb_origem.findData(atual_o, _PAPEL)
            if i >= 0:
                self.cb_origem.setCurrentIndex(i)
        atual_p = self.cb_plano.currentText()
        self.cb_plano.clear()
        self.cb_plano.addItems(self.j.aba_plano.planos())
        if atual_p:
            self.cb_plano.setCurrentText(atual_p)
        self._carregando = False
        if self.info and self.cb_origem.currentData(_PAPEL) == atual_o and                 self.cb_plano.currentText() == atual_p:
            return       # mesma origem e plano: mantém a tabela como está
        self._plano_mudou()

    def _arquivo(self):
        caixa = QMessageBox(self)
        caixa.setWindowTitle("Seus dados")
        caixa.setText("Onde estão os dados?")
        b_gdb = caixa.addButton("File Geodatabase (.gdb)", QMessageBox.ButtonRole.AcceptRole)
        b_arq = caixa.addButton("Arquivo (shp, gpkg, geojson, kml, csv…)",
                                QMessageBox.ButtonRole.AcceptRole)
        caixa.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        caixa.exec()
        if caixa.clickedButton() is b_gdb:
            p = QFileDialog.getExistingDirectory(self, "Seus dados (.gdb)", self.j.pasta)
        elif caixa.clickedButton() is b_arq:
            p, _ = QFileDialog.getOpenFileName(
                self, "Seus dados", self.j.pasta,
                "Dados (*.shp *.gpkg *.geojson *.json *.kml *.kmz *.csv *.xlsx *.dxf *.tab *.gml);;"
                "Todos (*.*)")
        else:
            return
        if not p:
            return
        p = os.path.normpath(p)
        try:
            cams = I.camadas(p)
        except Exception as e:
            QMessageBox.warning(self, "Seus dados", f"Não consegui ler {p}:\n{e}")
            return
        if not cams:
            QMessageBox.information(self, "Seus dados", "O arquivo não tem camadas.")
            return
        lista = self.j.estado.setdefault("fontes_importacao", [])
        for c in cams:
            if [p, c["nome"]] not in lista:
                lista.append([p, c["nome"]])
        self.j._salvar_estado()
        self.atualizar()
        i = self.cb_origem.findData(chave_fonte(p, cams[0]["nome"]), _PAPEL)
        if i >= 0:
            self.cb_origem.setCurrentIndex(i)

    def _plano_mudou(self, *_):
        if self._carregando:
            return
        self._carregando = True
        self.cb_destino.clear()
        plano = self.cb_plano.currentText()
        if plano and os.path.exists(plano):
            try:
                for c in estrutura.ler(plano)["camadas"]:
                    self.cb_destino.addItem(f"{c['nome']}  ({c['geometria']}, {c['feicoes']} feições)",
                                            c["nome"])
            except Exception as e:
                self.j._status(f"Não consegui ler o plano: {e}")
        self.cb_destino.setCurrentIndex(-1)
        self._carregando = False
        self._montar()

    def _destino_mudou(self, *_):
        if not self._carregando:
            self._montar(camada_destino=self.cb_destino.currentData(_PAPEL))

    def _plano_novo(self):
        if not self.j.perfil:
            QMessageBox.information(self, "Plano novo", "Monte o perfil do contrato primeiro (aba 1).")
            return
        p, filtro = QFileDialog.getSaveFileName(
            self, "Plano novo", self.j.pasta, "File Geodatabase (*.gdb);;GeoPackage (*.gpkg)")
        if not p:
            return
        if not p.lower().endswith((".gdb", ".gpkg")):
            p += ".gdb" if "gdb" in filtro else ".gpkg"
        p = os.path.normpath(p)
        srv = estrutura.servicos_do_arquivo(self.j.perfil, p) or list(self.j.estado.get("servicos") or [])
        try:
            rel = I.criar_plano(self.j.perfil, p, srv)
        except Exception as e:
            QMessageBox.warning(self, "Plano novo", f"Não foi possível: {e}")
            return
        self.j.estado.setdefault("planos", []).append(p)
        self.j._salvar_estado()
        self.j.aba_plano.atualizar()
        self.atualizar()
        self.cb_plano.setCurrentText(p)
        QMessageBox.information(self, "Plano novo",
                                f"Plano criado com {len(rel['camadas_criadas'])} camada(s) "
                                f"(serviços: {', '.join(srv) or 'todos'}):\n"
                                + "\n".join(rel["camadas_criadas"]))

    # ------------------------------------------------------------ ligação
    def _servicos(self):
        plano = self.cb_plano.currentText()
        return self.j.aba_plano.servicos(plano) if plano else []

    def _montar(self, *_, camada_destino=None):
        if self._carregando:
            return
        self.info = None
        self.tab.setRowCount(0)
        self.tab_val.setRowCount(0)
        orig = self.cb_origem.currentData(_PAPEL)
        plano = self.cb_plano.currentText()
        if not orig or not plano or not os.path.exists(plano):
            self._botoes()
            return
        caminho, camada = orig.rsplit("|", 1)
        ant = I.anterior(self.j.estado, caminho, camada, plano, camada_destino)
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.info = I.montar_ligacao(self.j.perfil, caminho, camada, plano,
                                         camada_destino or (ant or {}).get("camada_destino"),
                                         self._servicos(), anterior=ant)
        except Exception as e:
            self.txt.setPlainText(f"⚠ {e}")
            self._botoes()
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        lig = self.info["ligacao"]
        self._carregando = True
        i = self.cb_destino.findData(lig["camada_destino"], _PAPEL)
        self.cb_destino.setCurrentIndex(i)
        self.ck_subst.setChecked(bool(lig.get("substituir")))
        self._carregando = False
        o = self.info["origem"]
        self.txt.setPlainText(f"{o['feicoes']} feição(ões) em {lig['camada_origem']} "
                              f"({o['geometria']}, EPSG:{o['epsg'] or '?'}) → {lig['camada_destino']} "
                              f"({self.info['destino']['geometria']}, "
                              f"EPSG:{self.info['destino']['epsg'] or '?'}).")
        self._preencher()

    def _preencher(self):
        dest = self.info["destino"]["campos"]
        nomes_o = [f["nome"] for f in self.info["origem"]["campos"]]
        self.tab.setRowCount(len(dest))
        for r, f in enumerate(dest):
            spec = self.info["ligacao"]["campos"][f["nome"]]
            it = QTableWidgetItem(f["nome"] + (" *" if f["obrigatorio"] else ""))
            it.setData(_PAPEL, f["nome"])
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if f["obrigatorio"]:
                it.setToolTip("Obrigatório no contrato")
            self.tab.setItem(r, 0, it)
            desc = f["descricao"] or ""
            if f["valores_permitidos"]:
                desc += f"  [{len(f['valores_permitidos'])} valores permitidos]"
            it = QTableWidgetItem(desc)
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            it.setToolTip(f"{f['tipo']}" + (f", até {f['tamanho']}" if f["tamanho"] else ""))
            self.tab.setItem(r, 1, it)

            cb = QComboBox()
            cb.addItem("")
            for n in nomes_o:
                am = self.info["amostras"].get(n, {})
                ex = ", ".join(v for v, _ in am.get("valores", [])[:3])
                cb.addItem(n)
                cb.setItemData(cb.count() - 1, f"ex.: {ex}" if ex else "(vazio)",
                               Qt.ItemDataRole.ToolTipRole)
            cb.setCurrentText(spec.get("origem", ""))
            cb.currentTextChanged.connect(lambda t, nome=f["nome"]: self._origem_mudou(nome, t))
            self.tab.setCellWidget(r, 2, cb)

            fx = QComboBox()
            fx.setEditable(True)
            fx.addItem("")
            fx.addItems(f["valores_permitidos"])
            atual = spec.get("fixo", "")
            if atual and f["valores_permitidos"]:
                k = next((v for v in f["valores_permitidos"] if I.codigo_valor(v) == atual), atual)
                fx.setCurrentText(k)
            else:
                fx.setCurrentText(atual)
            fx.setToolTip("Valor para todos os registros (usado quando não vem dos seus dados).")
            fx.currentTextChanged.connect(lambda t, nome=f["nome"]: self._fixo_mudou(nome, t))
            self.tab.setCellWidget(r, 3, fx)
            self._situacao(r)
        self._botoes()

    def _campo(self, nome):
        return next(f for f in self.info["destino"]["campos"] if f["nome"] == nome)

    def _linha(self, nome):
        for r in range(self.tab.rowCount()):
            if self.tab.item(r, 0).data(_PAPEL) == nome:
                return r
        return -1

    def _situacao(self, r):
        nome = self.tab.item(r, 0).data(_PAPEL)
        f = self._campo(nome)
        spec = self.info["ligacao"]["campos"][nome]
        if spec.get("origem"):
            txt = _COMO.get(spec.get("como"), "✋ você")
            if f["valores_permitidos"]:
                am = self.info["amostras"].get(spec["origem"], {})
                vals = [v for v, _ in am.get("valores", [])]
                perm = {I._chave(I.codigo_valor(v)) for v in f["valores_permitidos"]}
                ok = sum(1 for v in vals if spec["valores"].get(v) or I._chave(v) in perm)
                txt += f" · {ok}/{len(vals)} valores" + (" ⚠" if ok < len(vals) else "")
        elif spec.get("fixo"):
            txt = "valor fixo"
        elif f["valor_padrao"]:
            txt = f"padrão do perfil ({f['valor_padrao']})"
        elif f["obrigatorio"]:
            txt = "⚠ obrigatório sem origem"
        else:
            txt = "—"
        it = QTableWidgetItem(txt)
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.tab.setItem(r, 4, it)

    def _origem_mudou(self, nome, texto):
        spec = self.info["ligacao"]["campos"][nome]
        if spec.get("origem", "") == texto:
            return
        spec.update({"origem": texto, "valores": {}, "como": "manual"})
        I.completar_valores(spec, self._campo(nome), self.info["amostras"])
        self._situacao(self._linha(nome))
        self._mostrar_valores()
        self._guardar()

    def _fixo_mudou(self, nome, texto):
        f = self._campo(nome)
        self.info["ligacao"]["campos"][nome]["fixo"] = \
            I.codigo_valor(texto) if (texto and f["valores_permitidos"]) else texto.strip()
        self._situacao(self._linha(nome))
        self._guardar()

    def _subst(self, sim):
        if self.info and not self._carregando:
            self.info["ligacao"]["substituir"] = bool(sim)
            self._guardar()

    def _mostrar_valores(self):
        self.tab_val.setRowCount(0)
        linhas = self.tab.selectionModel().selectedRows() if self.info else []
        if not linhas:
            return
        nome = self.tab.item(linhas[0].row(), 0).data(_PAPEL)
        f = self._campo(nome)
        spec = self.info["ligacao"]["campos"][nome]
        if not f["valores_permitidos"] or not spec.get("origem"):
            self.lb_valores.setText(f"<small>{nome}: " + (
                "sem valores permitidos (o valor é copiado como está)." if not f["valores_permitidos"]
                else "escolha de onde vem para ligar os valores.") + "</small>")
            return
        am = self.info["amostras"].get(spec["origem"], {})
        vals = am.get("valores", [])
        extra = f" (mostrando os {len(vals)} mais comuns de {am.get('total')})" \
            if am.get("total", 0) > len(vals) else ""
        self.lb_valores.setText(f"<small><b>{nome}</b> ← {spec['origem']}: ligue cada valor ao "
                                f"código do contrato{extra}.</small>")
        perm = f["valores_permitidos"]
        self.tab_val.setRowCount(len(vals))
        for r, (v, n) in enumerate(vals):
            self.tab_val.setItem(r, 0, QTableWidgetItem(v))
            self.tab_val.setItem(r, 1, QTableWidgetItem(str(n)))
            cb = QComboBox()
            cb.addItem("(como está)")
            cb.addItems(perm)
            cod = spec["valores"].get(v, "")
            if cod:
                k = next((p for p in perm if I.codigo_valor(p) == cod), None)
                if k:
                    cb.setCurrentText(k)
            cb.currentIndexChanged.connect(
                lambda i, valor=v, nome=nome, cb=cb: self._valor_mudou(nome, valor, cb))
            self.tab_val.setCellWidget(r, 2, cb)

    def _valor_mudou(self, nome, valor, cb):
        spec = self.info["ligacao"]["campos"][nome]
        if cb.currentIndex() <= 0:
            spec["valores"].pop(valor, None)
        else:
            spec["valores"][valor] = I.codigo_valor(cb.currentText())
        self._situacao(self._linha(nome))
        self._guardar()

    def _guardar(self):
        """Guarda a ligação no estado.json (volta igual ao reabrir a aba ou a janela)."""
        if self.info:
            I.guardar(self.j.estado, self.info["ligacao"])
            self.j._salvar_estado()

    def _botoes(self, ocupado=False):
        tem = self.info is not None
        for b in (self.bt_ia, self.bt_previa, self.bt_importar):
            b.setEnabled(tem and not ocupado)

    # ------------------------------------------------------------ Claude
    def _sugerir(self):
        if not self.info:
            return
        motor = config_ia.motor()
        if motor not in ("claude", "api"):
            self.j._configurar_ia()
            motor = config_ia.motor()
            if motor not in ("claude", "api"):
                return
        dados = I.dados_ia(self.info)
        self._botoes(ocupado=True)
        self.j._status("Claude: ligando os campos…")
        if motor == "api":
            chave = config_ia.chave()
            info = self.info

            def trabalho(task):
                return I.sugerir_api(dados, chave)

            def fim(exc, texto=None):
                self._botoes()
                if exc:
                    self._erro_ia(str(exc))
                else:
                    self._aplicar_ia(texto, info)
            self._tarefa = QgsTask.fromFunction("Sugestão de ligação", trabalho, on_finished=fim)
            from qgis.core import QgsApplication
            QgsApplication.taskManager().addTask(self._tarefa)
            return
        exe = config_ia.claude_code()["exe"]
        proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            env.remove(k)
        proc.setProcessEnvironment(env)
        proc.setWorkingDirectory(self.j.pasta if os.path.isdir(self.j.pasta) else os.path.expanduser("~"))
        args = I.argumentos_claude()
        if exe.lower().endswith((".cmd", ".bat")):
            exe, args = "cmd", ["/c", exe] + args
        info = self.info
        proc.finished.connect(lambda *_: self._fim_claude(proc, info))
        proc.errorOccurred.connect(lambda e: e == QProcess.ProcessError.FailedToStart and
                                   self._fim_claude(proc, info, "Não consegui abrir o Claude Code."))
        self._proc = proc
        QTimer.singleShot(_TEMPO_IA, lambda: self._proc is proc and proc.kill())
        proc.start(exe, args)
        proc.write(dados.encode("utf-8"))
        proc.closeWriteChannel()

    def _fim_claude(self, proc, info, erro=None):
        if self._proc is not proc:
            return
        self._proc = None
        self._botoes()
        if erro:
            self._erro_ia(erro)
            return
        saida = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
        ok, texto = I.texto_resposta_claude(saida)
        if not ok:
            err = bytes(proc.readAllStandardError()).decode("utf-8", "replace").strip()
            self._erro_ia(texto or err[-600:] or "O Claude parou sem resposta.")
            return
        self._aplicar_ia(texto, info)

    def _erro_ia(self, msg):
        self.j._status("Sugestão do Claude não veio.")
        QMessageBox.warning(self, "Sugerir com Claude", msg)

    def _aplicar_ia(self, texto, info):
        if info is not self.info:
            return       # o usuário trocou de origem/destino no meio
        try:
            lig, obs, n = I.ler_resposta_ia(texto, info)
        except Exception as e:
            self._erro_ia(str(e))
            return
        self.info["ligacao"] = lig
        self._guardar()
        self._preencher()
        self._mostrar_valores()
        self.j._status(f"Claude sugeriu {n} ligação(ões).")
        self.txt.setPlainText(f"🤖 Claude: {n} ligação(ões) sugerida(s). Confira na tabela "
                              f"(coluna Situação).\n{obs}")

    # ------------------------------------------------------------ prévia / importar
    def _executar(self, gravar):
        if not self.info:
            return
        lig = self.info["ligacao"]
        self._guardar()
        if gravar:
            modo = "SUBSTITUIR as feições que já estão em" if lig.get("substituir") else "acrescentar a"
            if QMessageBox.question(
                    self, "Importar",
                    f"Copiar {self.info['origem']['feicoes']} feição(ões) de {lig['camada_origem']} e "
                    f"{modo} {lig['camada_destino']} em\n{lig['plano']}?\n\n"
                    "Antes é feita uma cópia de segurança do plano.") != QMessageBox.StandardButton.Yes:
                return
            aberto = any(I._mesma(l.source().split("|")[0], lig["plano"])
                         for l in QgsProject.instance().mapLayers().values())
            if aberto and lig["plano"].lower().rstrip("/\\").endswith(".gdb"):
                QMessageBox.information(self, "Importar",
                                        "O plano está aberto no QGIS. Se der erro de arquivo em uso, "
                                        "remova as camadas dele do projeto e tente de novo.")
        p, srv, sinal = self.j.perfil, self._servicos(), self.j._sinal
        lig = dict(lig)

        def trabalho(task):
            return I.executar(lig, p, srv, gravar=gravar, progresso=sinal.msg.emit,
                              cancelado=task.isCanceled)

        def fim(exc, rel=None):
            self.j._ocupado(False)
            self._botoes()
            if exc:
                self.txt.setPlainText(f"⚠ {exc}")
                self.j._status("Não foi possível.")
                return
            if not rel:
                return
            cab = "✅ Importado." if gravar and not rel["cancelado"] else (
                "Importação cancelada." if rel["cancelado"] else "Prévia (nada foi gravado):")
            self.txt.setPlainText("\n".join([cab] + I.resumo(rel)))
            self.j._status(cab)
            if gravar and rel["gravadas"]:
                self._depois_de_gravar(lig)

        self._botoes(ocupado=True)
        self.j._rodar(QgsTask.fromFunction("Importando" if gravar else "Prévia da importação",
                                           trabalho, on_finished=fim))

    def _depois_de_gravar(self, lig):
        for lyr in QgsProject.instance().mapLayers().values():
            if isinstance(lyr, QgsVectorLayer) and I._mesma(lyr.source().split("|")[0], lig["plano"]):
                lyr.dataProvider().reloadData()
                lyr.triggerRepaint()
        if QMessageBox.question(self, "Importar", "Abrir a camada do plano no QGIS?") \
                == QMessageBox.StandardButton.Yes:
            lyr = carregar_camada(lig["plano"], lig["camada_destino"])
            if lyr:
                self.j.iface.setActiveLayer(lyr)
                self.j.iface.zoomToActiveLayer()
        resultado = self.txt.toPlainText()
        self._plano_mudou()          # atualiza a contagem de feições das camadas do plano
        self.txt.setPlainText(resultado)
        self.j.aba_plano.atualizar()
