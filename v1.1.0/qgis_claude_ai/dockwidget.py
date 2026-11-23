# -*- coding: utf-8 -*-
"""Painel de chat. A IA roda em thread; a execução no QGIS roda na thread principal
(o QGIS não é thread-safe). Loop de agente: plano -> execução -> resultados -> IA."""
import html
import json

from qgis.PyQt.QtWidgets import (
    QDockWidget, QVBoxLayout, QWidget, QTextEdit, QLineEdit, QPushButton,
    QHBoxLayout, QLabel, QComboBox, QMessageBox,
)
from qgis.PyQt.QtCore import Qt, pyqtSignal, QThread
from qgis.core import QgsProject

from .executor import execute_claude_plan, only_info
from .context import build_context

MAX_ROUNDS = 8       # rodadas IA<->QGIS por pedido
MAX_RETRIES = 3      # correções automáticas seguidas após erro
MAX_HISTORY = 16
MAX_RESULT_CHARS = 3500


class AskWorker(QThread):
    done = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, client, messages):
        super().__init__()
        self.client = client
        self.messages = messages

    def run(self):
        try:
            self.done.emit(self.client.ask(self.messages))
        except Exception:
            import traceback
            self.failed.emit(traceback.format_exc())


class ClaudeAIDockWidget(QDockWidget):
    closed = pyqtSignal()

    def __init__(self, iface, claude_client):
        super().__init__("Claude AI Assistant", iface.mainWindow())
        self.iface = iface
        self.claude_client = claude_client
        self.worker = None
        self.history = []
        self.rounds = 0
        self.retries = 0
        self.cancelled = False
        self.setup_ui()
        proj = QgsProject.instance()
        proj.layersAdded.connect(self.refresh_layers)
        proj.layersRemoved.connect(self.refresh_layers)

    # ------------------------------------------------------------------ UI
    def setup_ui(self):
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setMinimumWidth(380)
        w = QWidget()
        lay = QVBoxLayout(w)

        head = QHBoxLayout()
        head.addWidget(QLabel("<b>Claude no QGIS</b>"))
        head.addStretch()
        self.provider_label = QLabel(f"IA: {self.claude_client.get_provider()}")
        self.provider_label.setStyleSheet("color:#888;font-size:11px;")
        head.addWidget(self.provider_label)
        lay.addLayout(head)

        lay.addWidget(QLabel("Camada em foco (detalhes de campos vão para a IA):"))
        self.layer_combo = QComboBox()
        lay.addWidget(self.layer_combo)
        self.refresh_layers()

        self.chat_log = QTextEdit()
        self.chat_log.setReadOnly(True)
        self.chat_log.setStyleSheet(
            "QTextEdit{background:#1e1e1e;color:#d4d4d4;font-family:Consolas,monospace;font-size:12px;}")
        lay.addWidget(self.chat_log)

        row = QHBoxLayout()
        self.prompt_input = QLineEdit()
        self.prompt_input.setPlaceholderText("Ex: buffer de 100 m na camada vias, dissolvido")
        self.prompt_input.returnPressed.connect(self.send_prompt)
        row.addWidget(self.prompt_input)
        self.send_btn = QPushButton("Enviar")
        self.send_btn.clicked.connect(self.send_prompt)
        row.addWidget(self.send_btn)
        self.stop_btn = QPushButton("Parar")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        row.addWidget(self.stop_btn)
        self.clear_btn = QPushButton("Limpar")
        self.clear_btn.clicked.connect(self.clear_chat)
        row.addWidget(self.clear_btn)
        lay.addLayout(row)

        self.status_label = QLabel("Pronto.")
        self.status_label.setStyleSheet("color:#888;font-size:11px;")
        lay.addWidget(self.status_label)
        self.setWidget(w)

    def refresh_layers(self, *_):
        current = self.layer_combo.currentText() if self.layer_combo.count() else ""
        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()
        self.layer_combo.addItem("(nenhuma — resumo geral)")
        for l in QgsProject.instance().mapLayers().values():
            self.layer_combo.addItem(l.name())
        i = self.layer_combo.findText(current)
        self.layer_combo.setCurrentIndex(i if i >= 0 else 0)
        self.layer_combo.blockSignals(False)

    def append_chat(self, sender, text):
        safe = html.escape(str(text)).replace("\n", "<br>")
        self.chat_log.append(f"<b>{html.escape(sender)}</b> {safe}")
        sb = self.chat_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def set_busy(self, busy):
        self.send_btn.setEnabled(not busy)
        self.stop_btn.setEnabled(busy)

    # --------------------------------------------------------------- agente
    def clear_chat(self):
        self.chat_log.clear()
        self.history = []
        self.status_label.setText("Conversa limpa.")

    def stop(self):
        self.cancelled = True
        self.status_label.setText("Parando após o passo atual...")

    def send_prompt(self):
        prompt = self.prompt_input.text().strip()
        if not prompt or (self.worker and self.worker.isRunning()):
            return
        self.prompt_input.clear()
        self.append_chat("👤 Você:", prompt)
        focus = self.layer_combo.currentText() if self.layer_combo.currentIndex() > 0 else None
        ctx = build_context(focus)
        self.history.append({"role": "user",
                             "content": f"ESTADO DO PROJETO: {ctx}\n\nPEDIDO: {prompt}"})
        self.rounds = 0
        self.retries = 0
        self.cancelled = False
        self.set_busy(True)
        self._ask_ai()

    def _trimmed_history(self):
        h = self.history[-MAX_HISTORY:]
        while h and h[0]["role"] != "user":
            h = h[1:]
        return h

    def _ask_ai(self):
        self.status_label.setText("Consultando a IA...")
        self.worker = AskWorker(self.claude_client, self._trimmed_history())
        self.worker.done.connect(self.on_plan)
        self.worker.failed.connect(self.on_ai_error)
        self.worker.start()

    def on_ai_error(self, err):
        self.set_busy(False)
        self.append_chat("❌ Erro:", err)
        self.status_label.setText("Erro - veja o chat.")

    def _confirm(self, descriptions):
        txt = "A IA quer ALTERAR/APAGAR dados:\n\n" + "\n".join(f"• {d}" for d in descriptions) + \
              "\n\nContinuar? (edições em arquivos são gravadas direto)"
        return QMessageBox.question(self.iface.mainWindow(), "Claude AI — confirmar",
                                    txt) == QMessageBox.Yes

    def on_plan(self, plan):
        self.history.append({"role": "assistant", "content": json.dumps(plan, ensure_ascii=False)})
        steps = plan.get("steps", [])
        if plan.get("explanation"):
            self.append_chat("🤖 Claude:", plan["explanation"])
        if not steps or self.cancelled:
            return self._finish()

        for i, s in enumerate(steps, 1):
            self.append_chat("▶", f"{i}. {s.get('action')} {json.dumps(s.get('params', {}), ensure_ascii=False)[:300]}")
        self.status_label.setText("Executando no QGIS...")
        results = execute_claude_plan(plan, confirm=self._confirm)

        failed = False
        for i, r in enumerate(results, 1):
            if r.get("success"):
                self.append_chat("✅", f"{r.get('action')}: {json.dumps(r.get('result'), ensure_ascii=False, default=str)[:600]}")
            else:
                failed = True
                self.append_chat("❌", f"{r.get('action') or 'plano'}: {r.get('error')}")

        cancelled = any("Cancelado pelo usuário" in str(r.get("error")) for r in results)
        want_more = plan.get("continue") or only_info(plan) or failed
        if failed:
            self.retries += 1
        else:
            self.retries = 0
        if cancelled or self.cancelled or not want_more \
                or self.rounds >= MAX_ROUNDS or self.retries > MAX_RETRIES:
            if want_more and not cancelled and not self.cancelled:
                self.append_chat("⚠️", "Limite de rodadas/tentativas atingido.")
            return self._finish()

        payload = json.dumps(results, ensure_ascii=False, default=str)
        if len(payload) > MAX_RESULT_CHARS:
            payload = payload[:MAX_RESULT_CHARS] + "...(truncado)"
        self.history.append({"role": "user", "content": f"RESULTADOS DOS PASSOS: {payload}"})
        self.rounds += 1
        self._ask_ai()

    def _finish(self):
        self.set_busy(False)
        self.refresh_layers()
        self.iface.mapCanvas().refresh()
        self.status_label.setText("Concluído." if not self.cancelled else "Interrompido.")

    def closeEvent(self, event):
        self.cancelled = True
        if self.worker and self.worker.isRunning():
            self.worker.wait(2000)
        self.closed.emit()
        super().closeEvent(event)
