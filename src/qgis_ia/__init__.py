# -*- coding: utf-8 -*-
"""
Plugin principal: QGIS_IA para QGIS
"""
import os
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsApplication, QgsMessageLog

from .dockwidget import QgisIaDockWidget
from .ai_client import ClaudeClient
from .mcp_socket import McpSocketServer


MENU = "&App_Qgis"


class QgisIaPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.dockwidget = None
        self.claude_client = None
        self.mcp_server = None
        self.plugin_dir = os.path.dirname(__file__)

    def initGui(self):
        """Cria ação no menu Plugins e toolbar."""
        icon_path = os.path.join(self.plugin_dir, "icon.svg")
        if not os.path.exists(icon_path):
            # Ícone padrão do QGIS se não houver customizado
            icon_path = ":images/themes/default/mIconConsole.svg"

        # Janela inicial: Coleta Convencional, Coleta Seletiva, Varrição Manual e Mecanizada
        self.janela_inicio = None
        self.action_inicio = QAction(QIcon(icon_path), "App_Qgis", self.iface.mainWindow())
        self.action_inicio.setToolTip("App_Qgis: planos de coleta e varrição")
        self.action_inicio.triggered.connect(self.abrir_inicio)
        self.iface.addPluginToMenu(MENU, self.action_inicio)
        self.iface.addToolBarIcon(self.action_inicio)

        # Assistente por mensagens (painel lateral): só pelo menu e pela janela inicial
        self.action = QAction(
            QIcon(":images/themes/default/mIconConsole.svg"),
            "Assistente IA (chat)",
            self.iface.mainWindow()
        )
        self.action.setCheckable(True)
        self.action.triggered.connect(self.toggle_dockwidget)
        self.iface.addPluginToMenu(MENU, self.action)

        # App "Planos do Contrato" (janela própria)
        self.janela_planos = None
        self.action_planos = QAction(
            QIcon(":images/themes/default/mActionFileOpen.svg"),
            "Planos do Contrato",
            self.iface.mainWindow()
        )
        self.action_planos.setToolTip("Planos do Contrato: edital → o que falta → plano")
        self.action_planos.triggered.connect(lambda: self.abrir_planos())
        self.iface.addPluginToMenu(MENU, self.action_planos)

        # Primeiro uso numa máquina nova: configura a conta da IA
        from qgis.PyQt.QtCore import QTimer
        from .planos.janela import pedir_configuracao_inicial
        QTimer.singleShot(2000, lambda: pedir_configuracao_inicial(self.iface.mainWindow()))

        # Inicializa cliente Claude (lazy - só quando abrir)
        self.claude_client = None

    def unload(self):
        """Remove menu/toolbar ao desativar plugin."""
        self.iface.removePluginMenu(MENU, self.action_inicio)
        self.iface.removeToolBarIcon(self.action_inicio)
        self.iface.removePluginMenu(MENU, self.action)
        self.iface.removePluginMenu(MENU, self.action_planos)
        if self.janela_inicio:
            self.janela_inicio.close()
            self.janela_inicio.deleteLater()
            self.janela_inicio = None
        if self.janela_planos:
            self.janela_planos.desligar()
            self.janela_planos.close()
            self.janela_planos.deleteLater()
            self.janela_planos = None
        if self.mcp_server:
            self.mcp_server.stop()
            self.mcp_server.deleteLater()
            self.mcp_server = None
        if self.dockwidget:
            self.dockwidget.close()
            self.dockwidget.deleteLater()

    def abrir_inicio(self):
        from .inicio import JanelaInicio
        if self.janela_inicio is None:
            self.janela_inicio = JanelaInicio(self.iface, abrir_chat=self.show_dockwidget,
                                              abrir_planos=self.abrir_planos)
        self.janela_inicio.show()
        self.janela_inicio.raise_()
        self.janela_inicio.activateWindow()

    def abrir_planos(self, pasta=None, documentos=None, ler=False):
        """Planos do Contrato; vindo de um projeto, já abre a pasta e os documentos dele.
        ler=True: o Claude já começa a ler o edital (Criar Todos sem perfil)."""
        from qgis.PyQt.QtCore import QTimer
        from .planos.janela import JanelaPlanos
        if self.janela_planos is None:
            self.janela_planos = JanelaPlanos(self.iface, self.get_mcp_server)
        if pasta:
            self.janela_planos.abrir_projeto(pasta, documentos or [])
        self.janela_planos.show()
        if ler:
            self.janela_planos.abas.setCurrentIndex(0)
            QTimer.singleShot(300, self.janela_planos._ler_com_ia)
        self.janela_planos.raise_()
        self.janela_planos.activateWindow()

    def toggle_dockwidget(self, checked):
        if checked:
            self.show_dockwidget()
        else:
            self.hide_dockwidget()

    def show_dockwidget(self):
        if not self.dockwidget:
            self.dockwidget = QgisIaDockWidget(
                self.iface, self.get_claude_client(), self.get_mcp_server()
            )
            self.dockwidget.closed.connect(self.on_dockwidget_closed)
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dockwidget)
        self.dockwidget.show()
        self.dockwidget.raise_()
        self.action.setChecked(True)

    def hide_dockwidget(self):
        if self.dockwidget:
            self.dockwidget.hide()
        self.action.setChecked(False)

    def on_dockwidget_closed(self):
        self.action.setChecked(False)

    def get_mcp_server(self):
        """Servidor MCP vive no plugin (não no painel): continua ativo se o painel for fechado."""
        if self.mcp_server is None:
            self.mcp_server = McpSocketServer(self.iface.mainWindow())
        return self.mcp_server

    def get_claude_client(self):
        """Lazy init do cliente de IA (Anthropic -> OpenRouter -> Mock)."""
        if self.claude_client is None:
            has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY", ""))
            has_openrouter = bool(os.environ.get("OPENROUTER_API_KEY", ""))
            if not has_anthropic and not has_openrouter:
                from .planos import config_ia
                from .planos.janela import ConfigIADialog
                if not config_ia.chave_configurada():
                    ConfigIADialog(self.iface.mainWindow(), primeira_vez=True).exec()
                else:
                    os.environ["ANTHROPIC_API_KEY"] = config_ia.chave()
                has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY", ""))
            if not has_anthropic and not has_openrouter:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "QGIS_IA",
                    "Nenhuma chave de API encontrada.\n"
                    "Defina a variável de ambiente ANTHROPIC_API_KEY e/ou "
                    "OPENROUTER_API_KEY (variáveis de ambiente do Windows) "
                    "para habilitar respostas reais da IA.\n"
                    "Sem nenhuma das duas, o plugin funciona em modo mock "
                    "(respostas simuladas, só para teste)."
                )
            self.claude_client = ClaudeClient()
        return self.claude_client


def classFactory(iface):
    """Chamado pelo QGIS para instanciar o plugin."""
    return QgisIaPlugin(iface)