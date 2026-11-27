# -*- coding: utf-8 -*-
"""Aba "Frota e equipe": adequa o plano já feito à frota e ao pessoal do edital novo."""
import os

from qgis.core import QgsTask
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout,
                                 QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
                                 QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

try:
    from .. import pastas as PA
except ImportError:  # testes
    import pastas as PA
from . import frota, historico
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
        txt = QLabel("Compara os veículos e o pessoal que o plano usa com o que o edital dá "
                     "(seções <i>recursos</i>, <i>equipes</i> e <i>turnos</i> do perfil) e "
                     "propõe como ficar como o edital pede: horários dos turnos, mudar de turno "
                     "ou trocar o equipamento que o edital não tem, tirar circuitos (juntar a um "
                     "vizinho ou dividir entre vizinhos) e, com o histórico de operação, "
                     "respeitar a jornada (quem recebe tem de caber nela; circuitos acima dela "
                     "passam linhas a vizinhos com folga).")
        txt.setWordWrap(True)
        lay.addWidget(txt)
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
        linha.addWidget(QLabel("Histórico de operação (peso e tempo):"))
        self.lb_hist = QLabel("—")
        self.lb_hist.setWordWrap(True)
        linha.addWidget(self.lb_hist, 1)
        bt = QPushButton("Escolher…")
        bt.setToolTip("Planilha de RDs (ex.: TabelaPadrão.xlsx): Tempo Total, Tempo de Refeição, "
                      "Tempo Produtivo/Improdutivo e Setor N / Peso N por viagem.")
        bt.clicked.connect(self._escolher_hist)
        linha.addWidget(bt)
        self.bt_sem_hist = QPushButton("Sem histórico")
        self.bt_sem_hist.clicked.connect(lambda: self._definir_hist(""))
        linha.addWidget(self.bt_sem_hist)
        lay.addLayout(linha)
        self.lb_jornada = QLabel("")
        self.lb_jornada.setWordWrap(True)
        lay.addWidget(self.lb_jornada)

        linha = QHBoxLayout()
        self.ck_horarios = QCheckBox("horários do edital")
        self.ck_horarios.setChecked(True)
        self.ck_horarios.setToolTip("Põe em cada circuito o horário do turno que o edital pede "
                                    "(seção turnos do perfil).")
        linha.addWidget(self.ck_horarios)
        self.ck_turno = QCheckBox("mudar de turno quando o outro turno tem sobra")
        self.ck_turno.setChecked(True)
        self.ck_turno.setToolTip("Ex.: o edital não tem munk à noite, mas tem sobra de munk de "
                                 "dia -> o circuito passa para o diurno (08h00-16h20).")
        linha.addWidget(self.ck_turno)
        linha.addStretch()
        lay.addLayout(linha)

        linha = QHBoxLayout()
        linha.addWidget(QLabel("Passar para"))
        self.cb_equipar = QComboBox()
        linha.addWidget(self.cb_equipar)
        linha.addWidget(QLabel("os circuitos"))
        self.ed_equipar = QLineEdit()
        self.ed_equipar.setPlaceholderText("ex.: 182501, 182502")
        self.ed_equipar.setToolTip("Circuitos que passam para este equipamento antes de tudo (ex.: "
                                   "o munk da DL Sul faz o Noroeste, circuito misto).")
        linha.addWidget(self.ed_equipar, 1)
        lay.addLayout(linha)
        linha = QHBoxLayout()
        self.ck_desd = QCheckBox("Desdobrar com a sobra de")
        self.ck_desd.setToolTip(
            "Com o histórico: a sobra deste equipamento no edital vira circuitos NOVOS mistos que "
            "saem da base escolhida. Eles recebem circuitos inteiros do turno que falta (ex.: "
            "noturno -> dia) e a parte acima da jornada dos circuitos da base, até a jornada e só "
            "nos dias em que o veículo sobra.")
        linha.addWidget(self.ck_desd)
        self.cb_desd = QComboBox()
        linha.addWidget(self.cb_desd)
        linha.addWidget(QLabel("saindo da base (DL)"))
        self.ed_base = QLineEdit()
        self.ed_base.setPlaceholderText("ex.: Sobradinho")
        self.ed_base.setToolTip("Parte do nome da base/garagem (ou do local de pesagem) dos "
                                "circuitos, ex.: Sobradinho.")
        linha.addWidget(self.ed_base, 1)
        lay.addLayout(linha)
        self.ck_maximo = QCheckBox("Redimensionar ao máximo para caber no edital")
        self.ck_maximo.setChecked(True)
        self.ck_maximo.setToolTip(
            "Com o histórico: o que ainda passa do edital tira circuitos inteiros repartindo as "
            "linhas entre até 8 vizinhos a até 5 km, enchendo cada um até a jornada (primeiro no "
            "mesmo turno, depois no outro turno); os circuitos acima da jornada passam linhas do "
            "mesmo jeito. O que não couber vira 'Pontos para levar ao órgão'.")
        lay.addWidget(self.ck_maximo)
        linha = QHBoxLayout()
        self.ck_fechar = QCheckBox("Fechar a frota do edital com horas a mais, até")
        self.ck_fechar.setToolTip(
            "Com o histórico: o turno que ainda passa dos veículos do edital (ex.: noturno) "
            "fecha no número do edital — os circuitos tirados são repartidos entre os "
            "vizinhos, que trabalham até este limite (já com a 2ª viagem). As horas acima da "
            "jornada do edital ficam especificadas por circuito (falta de caminhões) e o "
            "horário de término real é gravado na cópia.")
        linha.addWidget(self.ck_fechar)
        from qgis.PyQt.QtCore import QTime
        from qgis.PyQt.QtWidgets import QTimeEdit
        self._QTime = QTime
        self.sp_jmax = QTimeEdit()
        self.sp_jmax.setDisplayFormat("H'h'mm")
        self.sp_jmax.setTimeRange(QTime(7, 0), QTime(14, 0))
        self.sp_jmax.setTime(QTime(8, 50))
        self.sp_jmax.setToolTip("Horas por circuito (jornada com as horas a mais).")
        linha.addWidget(self.sp_jmax)
        linha.addStretch()
        lay.addLayout(linha)

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
        self.sp_rec.setRange(2, 4)
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
                          "uma troca para não fazê-la. Jornada = tempo típico do histórico "
                          "(mediana dos dias, sem a refeição).</small>")
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
        self._mostrar_hist()
        self._carregar_opcoes()

    # ------------------------------------------------------------ equipar / desdobrar
    def _equipamentos(self):
        """[(código, nome)] dos equipamentos do edital (seção recursos do perfil)."""
        vistos = {}
        for r in (self.j.perfil or {}).get("recursos") or []:
            cod = str(r.get("codigo_no_plano") or "").strip()
            if r.get("categoria") != "pessoal" and cod and cod not in vistos:
                vistos[cod] = r["nome"]
        return list(vistos.items())

    def _carregar_opcoes(self):
        op = (self.j.estado or {}).get("frota_opcoes") or {}
        eqs = self._equipamentos()
        for cb, chave in ((self.cb_equipar, "equipar_equip"), (self.cb_desd, "desdobrar_equip")):
            cb.blockSignals(True)
            cb.clear()
            for cod, nome in eqs:
                cb.addItem(nome, cod)
            munk = next((i for i, (_, n) in enumerate(eqs) if "munk" in n.lower()), 0)
            i = cb.findData(op.get(chave)) if op.get(chave) is not None else munk
            cb.setCurrentIndex(i if i >= 0 else munk)
            cb.blockSignals(False)
        self.ed_equipar.setText(op.get("equipar", ""))
        self.ck_desd.setChecked(bool(op.get("desdobrar")))
        self.ed_base.setText(op.get("base", ""))
        self.ck_maximo.setChecked(op.get("maximo", True))
        self.ck_fechar.setChecked(bool(op.get("fechar")))
        jm = int(round(float(op.get("jornada_max") or 8 + 50 / 60) * 60))
        self.sp_jmax.setTime(self._QTime(jm // 60, jm % 60))

    def _opcoes(self):
        """Lê e salva no contrato: ({codigo: equip}, base para desdobrar ou '', equip)."""
        op = {"equipar": self.ed_equipar.text().strip(),
              "equipar_equip": self.cb_equipar.currentData(),
              "desdobrar": self.ck_desd.isChecked(), "base": self.ed_base.text().strip(),
              "desdobrar_equip": self.cb_desd.currentData(),
              "maximo": self.ck_maximo.isChecked(), "fechar": self.ck_fechar.isChecked(),
              "jornada_max": round(self.sp_jmax.time().hour()
                                   + self.sp_jmax.time().minute() / 60, 4)}
        if self.j.estado is not None and self.j.estado.get("frota_opcoes") != op:
            self.j.estado["frota_opcoes"] = op
            self.j._salvar_estado()
        import re
        cods = [c for c in re.split(r"[\s,;]+", op["equipar"]) if c]
        equipar = {c: op["equipar_equip"] for c in cods} if op["equipar_equip"] else {}
        base = op["base"] if op["desdobrar"] else ""
        return equipar, base, op["desdobrar_equip"], op["maximo"],             (op["jornada_max"] if op["fechar"] else None)

    # ------------------------------------------------------------ histórico e jornada
    def _hist_arquivo(self):
        arq = (self.j.estado or {}).get("historico_operacao") or ""
        return arq if arq and os.path.exists(arq) else ""

    def _hist_cache(self):
        return PA.arquivo(self.j.pasta, "historico_cache.json", criar=True) if self.j.pasta else None

    def _mostrar_hist(self):
        arq = self._hist_arquivo()
        if not arq:
            self.lb_hist.setText("<i>nenhum — sem histórico, a proposta conta só veículos "
                                 "(não confere a jornada)</i>")
        else:
            txt = os.path.basename(arq)
            cache = self._hist_cache()
            try:
                import json
                with open(cache, encoding="utf-8") as f:
                    d = json.load(f)
                if os.path.normcase(os.path.abspath(arq)) == d["_chave"]["arquivo"]:
                    txt += f" — {historico.resumo_txt(d)}"
            except Exception:
                pass
            self.lb_hist.setText(txt)
        self.bt_sem_hist.setEnabled(bool(arq))
        tur = frota.turnos_edital(self.j.perfil or {}, None)
        if tur:
            vistos = []
            for t in tur:
                s = f"{t['turno']} {frota._hm(t['ini'])}–{frota._hm(t['fim'])}" + \
                    (f" (só equip. {t['equip']})" if t["equip"] else "")
                if s not in vistos:
                    vistos.append(s)
            jor = next((t["jornada"] for t in tur if t["jornada"]), None)
            self.lb_jornada.setText(f"<small>Edital: jornada de <b>{historico.hhmm(jor)}</b> "
                                    f"por turno · {' · '.join(vistos)}</small>")
        else:
            self.lb_jornada.setText("<small>O perfil não tem os turnos do edital (seção "
                                    "<i>turnos</i>): jornada considerada 7h20 e horários do plano "
                                    "mantidos.</small>")

    def _escolher_hist(self):
        ini = self._hist_arquivo() or self.j.pasta or ""
        arq, _ = QFileDialog.getOpenFileName(self, "Histórico de operação (RDs)", ini,
                                             "Excel (*.xlsx *.xlsm)")
        if arq:
            self._definir_hist(arq)

    def _definir_hist(self, arq):
        self.j.estado["historico_operacao"] = os.path.normpath(arq) if arq else ""
        self.j._salvar_estado()
        self.proposta = None
        self.arv.clear()
        self._botoes()
        self._mostrar_hist()

    def _limpar(self, *_):
        self.proposta = None
        self.recusadas = set()
        self.tab.clear()
        self.arv.clear()
        self._botoes()

    def _botoes(self):
        tem = self.proposta is not None
        self.bt_xlsx.setEnabled(tem)
        self.bt_gravar.setEnabled(tem and bool(
            self.proposta["operacoes"] or any(t["para"] for t in self.proposta["trocas"])
            or self.proposta.get("horarios") or self.proposta.get("mudancas_turno")
            or self.proposta.get("equipados") or self.proposta.get("desdobramentos")))

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
        hor, mud = self.ck_horarios.isChecked(), self.ck_turno.isChecked()
        arq_hist, cache = self._hist_arquivo(), self._hist_cache()
        equipar, base, eq_desd, maximo, jmax = self._opcoes()
        if self.ck_desd.isChecked() and not base:
            QMessageBox.information(self, "Propor", "Diga de qual base (DL) saem os circuitos "
                                    "novos do desdobramento, ex.: Sobradinho.")
            return
        if base and not arq_hist:
            QMessageBox.information(self, "Propor", "O desdobramento precisa do histórico de "
                                    "operação (tempo de cada circuito). Escolha a planilha.")
            return

        def trabalho(task):
            hist = None
            if arq_hist:
                sinal.msg.emit("Lendo o histórico de operação…")
                hist = historico.ler(arq_hist, cache=cache, progresso=sinal.msg.emit)
            sinal.msg.emit("Montando a proposta (horários, turnos, circuitos e jornada)…")
            return frota.propor(prf, p, srv, metodo=metodo, distancia=dist,
                                max_receptores=rec, outra_regiao=outra, substituicoes=subst,
                                historico=hist, horarios=hor, mudar_turno=mud,
                                equipar=equipar, desdobrar=base, equip_desdobrar=eq_desd,
                                redimensionar=maximo and bool(hist),
                                fechar=bool(jmax) and bool(hist),
                                jornada_max=jmax or 8 + 50 / 60)

        def fim(exc, res=None):
            self.j._ocupado(False)
            self.bt_propor.setEnabled(True)
            if exc or not res:
                QMessageBox.warning(self, "Propor", f"Erro: {exc}")
                return
            self.proposta = res
            self._mostrar()
            self._mostrar_hist()

        self.bt_propor.setEnabled(False)
        self.j._rodar(QgsTask.fromFunction("Propondo adequação", trabalho, on_finished=fim))

    def _mostrar(self):
        r = self.proposta
        self._tabela(r["depois"])
        self.tab.headerItem().setText(2, "Plano depois")
        self.arv.blockSignals(True)
        self.arv.clear()
        hh = historico.hhmm
        if r.get("horarios"):
            n = sum(len(h["circuitos"]) for h in r["horarios"])
            g = QTreeWidgetItem(self.arv, [f"Horários do edital ({n} circuitos)",
                                           "horário de cada turno como o edital pede"])
            for h in r["horarios"]:
                it = QTreeWidgetItem(g, [f"{h['nome_equip']} · {h['turno']}",
                                         f"{h['de']} → {h['para']} · {len(h['circuitos'])} "
                                         "circuito(s)"])
                it.setData(0, _PAPEL, ("lista", h["circuitos"]))
        if r.get("mudancas_turno"):
            g = QTreeWidgetItem(self.arv, [f"Mudanças de turno ({len(r['mudancas_turno'])})",
                                           "o circuito passa para o outro turno"])
            g.setExpanded(True)
            for m in r["mudancas_turno"]:
                it = QTreeWidgetItem(g, [f"{m['circuito']} — {m['de']} → {m['para']} "
                                         f"{m['inicio']}–{m['fim']}",
                                         f"{m['nome_equip']} · {', '.join(m['dias'])}"
                                         + (f" · {hh(m['tempo'])}" if m.get("tempo") else "")
                                         + f" · {m['motivo']}"])
                it.setData(0, _PAPEL, ("lista", [m["circuito"]]))
        if r.get("equipados"):
            g = QTreeWidgetItem(self.arv, [f"Passam para outro equipamento "
                                           f"({len(r['equipados'])})", "escolha sua"])
            g.setExpanded(True)
            for e in r["equipados"]:
                it = QTreeWidgetItem(g, [f"{e['circuito']} — {e['nome_de']} → {e['nome_para']}",
                                         f"{e['turno']} {e.get('inicio', '')}–{e.get('fim', '')}"
                                         f" · {', '.join(e['dias'])}"
                                         + (f" · {hh(e['tempo'])}" if e.get("tempo") else "")
                                         + (f" · {e['base']}" if e["base"] else "")])
                it.setData(0, _PAPEL, ("lista", [e["circuito"]]))
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
        retirar = [op for op in r["operacoes"] if op["tipo"] != "aliviar"]
        aliviar = [op for op in r["operacoes"] if op["tipo"] == "aliviar"]
        for titulo, det, lista in (
                (f"Circuitos retirados ({len(retirar)})", "o que sai e para quem vai", retirar),
                (f"Circuitos aliviados ({len(aliviar)})",
                 "acima da jornada: passam linhas a vizinhos com folga", aliviar)):
            if not lista:
                continue
            g = QTreeWidgetItem(self.arv, [titulo, det])
            g.setExpanded(True)
            for op in lista:
                verbo = {"juntar": "juntar em", "aliviar": "passar linhas a"}.get(
                    op["tipo"], f"dividir em {len(op['recebem'])}")
                if op.get("redimensionar"):
                    verbo += " (máximo)"
                tempo = ""
                if op.get("tempo") is not None:
                    tempo = f" · {hh(op['tempo'])}" + (
                        f" → {hh(op['tempo_depois'])}" if op.get("tempo_depois") is not None
                        else "")
                it = QTreeWidgetItem(g, [f"{op['circuito']} — {verbo}"
                                         + (f" {len(op['recebem'])}" if op["tipo"] == "aliviar"
                                            else ""),
                                         f"{op['turno']} · {', '.join(op['dias'])} · "
                                         f"{op['carga']:.1f} km{tempo}"])
                it.setData(0, _PAPEL, ("op", op["circuito"],
                                       [x["codigo"] for x in op["recebem"]]))
                for x in op["recebem"]:
                    extra = []
                    if x["dias_a_mais"]:
                        extra.append("passa a ser atendido também " + ", ".join(x["dias_a_mais"]))
                    if x["outra_regiao"]:
                        extra.append("outra região")
                    if x.get("turno") and x["turno"] != op["turno"]:
                        extra.append(f"vai para o {x['turno'].lower()}")
                    t = ""
                    if x.get("tempo_depois") is not None:
                        t = f" · jornada {hh(x['tempo_antes'])} → {hh(x['tempo_depois'])}"
                    filho = QTreeWidgetItem(it, [f"→ {x['codigo']}",
                                                 f"+{x['km']:.1f} km (fica com "
                                                 f"{x['carga_depois']:.1f} km){t}" +
                                                 (" · ⚠ " + "; ".join(extra) if extra else "")])
                    filho.setData(0, _PAPEL, ("op", x["codigo"], []))
        if r.get("desdobramentos"):
            g = QTreeWidgetItem(self.arv, [f"Circuitos novos — desdobramento "
                                           f"({len(r['desdobramentos'])})",
                                           "a sobra do edital vira circuitos mistos"])
            g.setExpanded(True)
            for nv in r["desdobramentos"]:
                it = QTreeWidgetItem(g, [f"{nv['codigo']} — {nv['nome_servico']}",
                                         f"{nv['nome_equip']} · {nv['turno']} {nv['inicio']}–"
                                         f"{nv['fim']} · {', '.join(nv['dias'])} · "
                                         f"{hh(nv['tempo'])} · {nv['carga']:.1f} km · "
                                         f"sai de {nv['base']}"])
                it.setData(0, _PAPEL, ("lista", [o["circuito"] for o in nv["origens"]]))
                for o in nv["origens"]:
                    det = (f"circuito inteiro ({o['turno']}, {hh(o['tempo_antes'])}) — sai do "
                           f"plano" if o["inteiro"] else
                           f"parte: {o['km']:.1f} km · {o['circuito']} fica "
                           f"{hh(o['tempo_antes'])} → {hh(o['tempo_depois'])}")
                    filho = QTreeWidgetItem(it, [f"← {o['circuito']}", det])
                    filho.setData(0, _PAPEL, ("lista", [o["circuito"]]))
        if r.get("acima_jornada"):
            g = QTreeWidgetItem(self.arv, [f"⛔ Acima da jornada ({len(r['acima_jornada'])})",
                                           f"tempo típico (histórico) maior que "
                                           f"{hh(r['jornada'])}"])
            for a in r["acima_jornada"]:
                it = QTreeWidgetItem(g, [f"{a['circuito']} — {hh(a['tempo'])}",
                                         f"{a['nome_equip']} · {a['turno']} · "
                                         f"{', '.join(a['dias'])} · "
                                         f"+{hh(a['tempo'] - a['jornada'])}"])
                it.setData(0, _PAPEL, ("lista", [a["circuito"]]))
        if r.get("horas_depois"):
            neg = [h for h in r["horas_depois"] if h["saldo"] is not None and h["saldo"] < 0]
            g = QTreeWidgetItem(self.arv, ["Horas de trabalho por dia × edital",
                                           f"veículos do edital × {hh(r['jornada'])}"
                                           + (f" · {len(neg)} dia(s) com falta" if neg else "")])
            g.setExpanded(bool(neg))
            for h in r["horas_depois"]:
                ic = "🔴" if h["saldo"] is not None and h["saldo"] < 0 else "🟢"
                QTreeWidgetItem(g, [f"{ic} {h['nome']} · {h['turno']} · {h['dia']}",
                                    f"precisa {hh(h['horas'])} em {h['circuitos']} circuitos · "
                                    f"edital {hh(h['capacidade'])} · saldo {hh(h['saldo'])}"])
        if r.get("horas_a_mais"):
            ha = r["horas_a_mais"]
            g = QTreeWidgetItem(self.arv, [f"⏱ Horas a mais por falta de caminhões ({len(ha)})",
                                           f"turno fechado até {hh(r['jornada_max'])} · horas "
                                           f"acima de {hh(r['jornada'])} em cada circuito"])
            for a in ha:
                it = QTreeWidgetItem(g, [f"{a['circuito']} — {hh(a['tempo'])} "
                                         f"(+{hh(a['horas_a_mais'])})",
                                         f"{a['nome_equip']} · {a['turno']} {a['inicio']}–"
                                         f"{a['fim']} · {', '.join(a['dias'])} · "
                                         f"{a['viagens']} viagem(ns)"
                                         + (" · ⚠ acima do limite" if a["tempo"] > a["limite"]
                                            + 1e-6 else "")])
                it.setData(0, _PAPEL, ("lista", [a["circuito"]]))
        if r.get("pontos"):
            g = QTreeWidgetItem(self.arv, [f"📋 Pontos para levar ao órgão ({len(r['pontos'])})",
                                           "o que não coube no edital e o que precisa de aceite "
                                           "— para depois de ganhar a licitação"])
            g.setExpanded(True)
            for pt in r["pontos"]:
                it = QTreeWidgetItem(g, [pt["tema"], f"{pt['situacao']} → {pt['proposta']}"])
                it.setToolTip(1, f"{pt['situacao']}\n\nProposta: {pt['proposta']}")
                if pt["circuitos"]:
                    it.setData(0, _PAPEL, ("lista", pt["circuitos"]))
        for n in r["nao_coube"]:
            QTreeWidgetItem(self.arv, ["⛔ " + n.split(":")[0].split(" — ")[0],
                                       n.split(":", 1)[-1].strip() if ":" in n
                                       else n.split(" — ", 1)[-1]])
        if not (r["trocas"] or r["operacoes"] or r["nao_coube"] or r.get("horarios")
                or r.get("mudancas_turno") or r.get("equipados") or r.get("desdobramentos")):
            QTreeWidgetItem(self.arv, ["✅ O plano já está como o edital pede.", ""])
        self.arv.blockSignals(False)
        partes = []
        if r.get("horarios"):
            partes.append(f"{sum(len(h['circuitos']) for h in r['horarios'])} horário(s)")
        if r.get("mudancas_turno"):
            partes.append(f"{len(r['mudancas_turno'])} mudança(s) de turno")
        partes += [f"{len(r['trocas'])} troca(s)", f"{len(retirar)} circuito(s) retirado(s)"]
        if aliviar:
            partes.append(f"{len(aliviar)} aliviado(s)")
        if r.get("equipados"):
            partes.append(f"{len(r['equipados'])} para outro equipamento")
        if r.get("desdobramentos"):
            partes.append(f"{len(r['desdobramentos'])} circuito(s) novo(s)")
        if r.get("historico"):
            hi = r["historico"]
            partes.append(f"jornada {hh(r['jornada'])} pelo histórico ({hi['periodo'][0]} a "
                          f"{hi['periodo'][1]})")
        else:
            partes.append("sem histórico: jornada não conferida")
        self.lb.setText(f"<b>{'✅ Com a proposta, fica como o edital pede' if r['cabe'] else '⛔ Mesmo com a proposta, não cabe tudo'}</b>"
                        f" — {', '.join(partes)}. Nada foi gravado ainda.")
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
        if dado[0] == "op":
            codigos = [dado[1]] + list(dado[2])
        elif dado[0] == "lista":
            codigos = list(dado[1])
        else:
            codigos = list(dado[3])
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
            msg = (f"Gravado em:\n{res['saida']}\n\n{res['horarios']} horário(s) ajustado(s), "
                   f"{res['mudancas_turno']} mudança(s) de turno, {res['trocas']} circuito(s) "
                   f"com equipamento trocado, {res['operacoes']} operação(ões) em circuitos "
                   f"(retirar/aliviar), {res.get('novos', 0)} circuito(s) novo(s).\n\n" +
                   "\n".join(res["avisos"]) + "\n\nAbrir no QGIS?")
            if QMessageBox.question(self, "Gravar", msg) == QMessageBox.StandardButton.Yes:
                m = r["mapa"]
                for cam in [m["camada"]] + [c for c, _ in m["linhas"] + m["pontos"]]:
                    carregar_camada(res["saida"], cam)
            self.j._status("Cópia adequada gravada.")

        self.bt_gravar.setEnabled(False)
        self.j._rodar(QgsTask.fromFunction("Gravando cópia adequada", trabalho, on_finished=fim))
