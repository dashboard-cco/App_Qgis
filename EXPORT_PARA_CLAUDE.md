# Export de contexto — Projeto "Claude AI Assistant" para QGIS

> **O que é este arquivo**: um resumo completo do projeto e de tudo que já foi feito
> nele, para colar/anexar em uma conversa nova com outro Claude e ele continuar o
> trabalho sem perder contexto. Inclui o código-fonte completo e atual de cada
> arquivo do plugin.
>
> **Exportado em**: 2026-11-19
> **Status**: v1.0.0 pronta, empacotada e com repositório git local já commitado e
> taggeado (ver seção "Status de publicação no GitHub").

---

## 1. O que é o projeto

Plugin para o QGIS (3.40+) chamado **"Claude AI Assistant"** que adiciona um painel
de chat lateral onde o usuário pede, em português, para uma IA executar ações de
geoprocessamento no projeto QGIS aberto — criar buffer, interseção, dissolver,
reprojetar, filtrar camadas, exportar mapas, rodar qualquer algoritmo da caixa
**Processing** do QGIS, etc.

A IA **nunca** executa código Python livre: ela só devolve um plano em JSON
(`{"steps": [{"action": "...", "params": {...}}]}`), e um executor valida cada ação
contra uma lista branca fixa antes de rodar a função Python correspondente.

Ambiente de desenvolvimento/uso: Windows 11, QGIS Desktop 3.44.15, pasta do plugin em
`C:\Users\User\qgis_claude_ai\` (cópia "mestre"), espelhada para dentro do perfil do
QGIS em:
- `C:\Users\User\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\qgis_claude_ai\`
- `C:\Users\User\AppData\Roaming\QGIS\QGIS3\profiles\default\python\qgis_claude_ai\`

As três cópias devem ficar sempre idênticas — isso já causou bugs no passado (ver
seção 3).

---

## 2. Arquitetura

```
qgis_claude_ai/
├── __init__.py         # Ponto de entrada do plugin (classFactory, menu, toolbar)
├── dockwidget.py        # Painel de chat (UI) + worker thread assíncrono
├── ai_client.py         # Cliente de IA multi-provider (Anthropic → OpenRouter → Mock)
├── executor.py          # Lista branca de ações + executor do plano JSON
├── actions/
│   ├── layers.py         # Ações sobre camadas
│   ├── processing.py     # Geoprocessamento + acesso genérico a qualquer algoritmo
│   ├── layout.py         # Exportação de layouts/mapas (PDF, imagem)
│   └── expressions.py    # Cálculo de campos e filtros por expressão
├── metadata.txt          # Metadados do plugin QGIS
├── requirements.txt       # Dependências Python (anthropic, openai)
└── icon.svg
```

**Fluxo de uma mensagem do usuário:**
1. `dockwidget.py` captura o texto e as camadas de contexto selecionadas.
2. Um `ClaudeWorker` (QThread) chama `ai_client.AIClient.ask_claude(prompt, camadas)`
   para não travar a interface do QGIS.
3. `ai_client.py` tenta os provedores em ordem — **Anthropic → OpenRouter (modelo
   gratuito descoberto dinamicamente) → Mock** — e devolve o JSON do plano.
4. `executor.execute_claude_plan(plan)` valida cada ação contra `ACTIONS` e chama a
   função Python correspondente com `**params`.
5. Resultado de cada passo aparece no chat.

**Provedores de IA, em ordem de tentativa:**
1. Anthropic (Claude, modelo `claude-sonnet-5`) — se `ANTHROPIC_API_KEY` definida.
2. OpenRouter — se `OPENROUTER_API_KEY` definida. Busca ao vivo na API da OpenRouter
   quais modelos terminam em `:free` e tenta em sequência até um responder (não
   depende mais de um nome de modelo fixo).
3. Mock — respostas simuladas por palavra-chave, só para testar sem nenhuma chave.

**29 ações registradas** em `executor.ACTIONS`, cobrindo camadas, geoprocessamento
vetorial (buffer, interseção, diferença, união, dissolve, clip, merge, reprojetar,
centroides, convex hull, simplify, spatial join), layout/exportação, expressões, e
um acesso **genérico** (`list_algorithms` / `run_algorithm`) a qualquer algoritmo do
Processing do QGIS via `QgsApplication.processingRegistry()`.


---

## 3. Histórico completo do projeto (em ordem)

### 3.1 Origem: migração de Anthropic para Gemini
O plugin começou usando a API da Anthropic direto, depois passou por uma migração
para a API Gemini do Google, que teve vários problemas de disponibilidade de modelo
(`gemini-flash-latest` → 404; `gemini-2.5-flash` → descontinuado para novos
usuários; `gemini-3.8-flash` → 503 sobrecarregado repetidas vezes; `gemini-3.5-flash`
→ funcionou). Essa migração para Gemini foi **depois substituída** pela arquitetura
multi-provider atual — hoje o Gemini não é mais usado pelo plugin.

### 3.2 Pedido do usuário: fallback automático
> "tem como colocar outra api pra ficar de segunda quando a do google ficar
> sobrecarregado?"

Decisão: usar OpenRouter como provedor secundário. Entre sessões, a arquitetura foi
reorganizada para o formato atual: **Anthropic (primário) → OpenRouter (fallback) →
Mock (sem chave nenhuma)**, implementada numa classe única `AIClient` em
`ai_client.py` (com alias `ClaudeClient = AIClient` por compatibilidade).

### 3.3 Pedido do usuário: expandir lista de comandos
> "a lista de comandos que o plugin aceita é muito pequena, teria como colocar os
> comandos mais usados do qgis ou todos os comandos?"

Diagnóstico: o `SYSTEM_PROMPT` já descrevia várias ações que existiam como função
Python mas não estavam registradas em `executor.ACTIONS` (causava "Ação não
permitida"). Solução: `ACTIONS` expandido de 7 para 29 entradas; adicionadas funções
novas em `actions/layers.py` (`add_vector_layer`, `add_raster_layer`,
`remove_layer`, `zoom_to_layer`, `export_layer`, `rename_layer`) e
`actions/processing.py` (`run_clip`, `run_merge_layers`, `run_reproject`,
`run_centroids`, `run_convex_hull`, `run_simplify`, `run_spatial_join`); e criado o
acesso genérico `run_algorithm`/`list_algorithms` que cobre **qualquer** algoritmo
de Processing instalado no QGIS, não só uma lista fixa.

### 3.4 Bugs encontrados e corrigidos
1. **`AttributeError: 'AIClient' object has no attribute 'ask_claude'`** —
   `dockwidget.py` chamava `.ask_claude(...)` mas a classe só tinha `.ask(...)`.
   Corrigido renomeando o método em `ai_client.py`. *(A cópia "mestre" do
   `dockwidget.py` ficou desatualizada em relação às cópias instaladas até a
   preparação da v1.0.0, quando foi sincronizada também.)*
2. **Modelo Anthropic desatualizado + parâmetro incompatível** — `model="claude-3-5-sonnet-20241022"`
   e `temperature=0.1` incompatíveis com o SDK atual. Corrigido para
   `model="claude-sonnet-5"`, `temperature` removido.
3. **Mock mascarando o problema real** — comandos diferentes retornavam a mesma
   resposta porque o pipeline caía silenciosamente até o mock. Causa raiz: pacote
   `openai` não instalado no Python embutido do QGIS + `OPENROUTER_API_KEY` não
   definida (e Anthropic sem crédito).
4. **`__init__.py` com resquício do Gemini** — `get_claude_client()` ainda lia
   `GEMINI_API_KEY`/`GOOGLE_API_KEY`. Corrigido para checar
   `ANTHROPIC_API_KEY`/`OPENROUTER_API_KEY` e explicar o modo mock no aviso.
5. **Variável de ambiente criada com nome errado** — usuário criou `OPENROUD_QGIS`
   em vez de `OPENROUTER_API_KEY`. Corrigido lendo o valor direto do registro do
   Windows (sem nunca expor o valor) e regravando sob o nome certo.
6. **QGIS não enxergava variável de ambiente nova mesmo após "reiniciar"** —
   abrir o QGIS por automação (fora do Explorer do Windows) herda um ambiente de
   processo desatualizado, que `setx` e broadcast de `WM_SETTINGCHANGE` não
   corrigem. Solução: o usuário fechar e reabrir o QGIS manualmente clicando no
   ícone (passa pelo Explorer, que reflete o ambiente atualizado).
7. **Modelo gratuito da OpenRouter hardcoded** — um único nome fixo
   (`nvidia/nemotron-3.5-lightning:free`) pode sair do ar. Adicionado
   `_discover_free_openrouter_models()` em `ai_client.py`: consulta a lista de
   modelos da OpenRouter ao vivo, filtra os `:free`, prioriza alguns conhecidos e
   tenta em sequência até um funcionar.

### 3.5 Teste de ponta a ponta confirmado
Com tudo corrigido, pedir "liste as camadas do projeto" no painel mostrou:
```
[AIClient] Anthropic falhou: Error code: 400 — Your credit balance is too low...
  — tentando OpenRouter...
Claude: Plano: { "steps": [ { "action": "list_layers", "params": {} } ] }
✅ Passo 1: []
```
Ou seja: Anthropic falhou (sem crédito), fallback para OpenRouter com modelo
gratuito funcionou automaticamente, plano executado com sucesso.

### 3.6 Preparação da versão v1.0.0 para o GitHub
- Corrigidas as inconsistências residuais entre a cópia "mestre" (`C:\Users\User\qgis_claude_ai\`)
  e as cópias instaladas no perfil do QGIS (itens 1 e 4 da seção 3.4, que só tinham
  sido corrigidos nas cópias instaladas, não na mestre).
- Criados `README.md`, `DOCUMENTACAO.md`, `CHANGELOG.md`, `LICENSE` (MIT), `.gitignore`.
- Repositório git local inicializado, commit único "Versão 1.0.0", tag `v1.0.0`.
- Empacotado em `qgis-claude-ai-v1.0.0.zip` e entregue ao usuário (no chat e salvo em
  `C:\Users\User\qgis_claude_ai\qgis-claude-ai-v1.0.0.zip`).
- **Pendente**: o usuário ainda precisa criar o repositório no GitHub e rodar
  `git remote add origin ...` + `git push -u origin master --tags` — não há acesso
  à conta do GitHub do usuário nesta sessão. Também pendente: editar
  `metadata.txt` com nome/e-mail/URL reais (hoje tem placeholders genéricos).


---

## 4. Código-fonte completo e atual

### `metadata.txt`
```ini
[general]
name=Claude AI Assistant
description=Assistente de IA (Claude) integrado ao QGIS via PyQGIS. Executa ações seguras no projeto via chat.
version=1.0.0
qgisMinimumVersion=3.40
author=Seu Nome
email=seu@email.com
repository=https://github.com/seu-usuario/qgis-claude-ai
icon=icon.svg
tags=ia,claude,anthropic,automacao,pyqgis
category=Processing
plugin_type=processing
hasProcessingProvider=false
```

### `requirements.txt`
```
anthropic>=0.25.0
openai>=1.0.0
```

### `__init__.py`
```python
# -*- coding: utf-8 -*-
"""
Plugin principal: Claude AI Assistant para QGIS
"""
import os
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsApplication, QgsMessageLog

from .dockwidget import ClaudeAIDockWidget
from .ai_client import ClaudeClient


class ClaudeAIPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.dockwidget = None
        self.claude_client = None
        self.plugin_dir = os.path.dirname(__file__)

    def initGui(self):
        """Cria ação no menu Plugins e toolbar."""
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        if not os.path.exists(icon_path):
            # Ícone padrão do QGIS se não houver customizado
            icon_path = ":images/themes/default/mIconConsole.svg"

        self.action = QAction(
            QIcon(icon_path),
            "Claude AI Assistant",
            self.iface.mainWindow()
        )
        self.action.setCheckable(True)
        self.action.triggered.connect(self.toggle_dockwidget)

        self.iface.addPluginToMenu("&Claude AI", self.action)
        self.iface.addToolBarIcon(self.action)

        # Inicializa cliente Claude (lazy - só quando abrir)
        self.claude_client = None

    def unload(self):
        """Remove menu/toolbar ao desativar plugin."""
        self.iface.removePluginMenu("&Claude AI", self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.dockwidget:
            self.dockwidget.close()
            self.dockwidget.deleteLater()

    def toggle_dockwidget(self, checked):
        if checked:
            self.show_dockwidget()
        else:
            self.hide_dockwidget()

    def show_dockwidget(self):
        if not self.dockwidget:
            self.dockwidget = ClaudeAIDockWidget(self.iface, self.get_claude_client())
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

    def get_claude_client(self):
        """Lazy init do cliente de IA (Anthropic -> OpenRouter -> Mock)."""
        if self.claude_client is None:
            has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY", ""))
            has_openrouter = bool(os.environ.get("OPENROUTER_API_KEY", ""))
            if not has_anthropic and not has_openrouter:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Claude AI",
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
    return ClaudeAIPlugin(iface)
```

### `dockwidget.py`
```python
# -*- coding: utf-8 -*-
"""
Dock Widget principal - Interface de chat
"""
import json
from qgis.PyQt.QtWidgets import (
    QDockWidget, QVBoxLayout, QWidget, QTextEdit, QLineEdit,
    QPushButton, QHBoxLayout, QLabel, QComboBox, QMessageBox
)
from qgis.PyQt.QtCore import Qt, pyqtSignal, QThread, QObject
from qgis.core import QgsProject, QgsMessageLog

from .executor import execute_claude_plan


class WorkerSignals(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)


class ClaudeWorker(QThread):
    """Thread para não travar a UI do QGIS."""
    def __init__(self, claude_client, prompt, context_layers):
        super().__init__()
        self.claude_client = claude_client
        self.prompt = prompt
        self.context_layers = context_layers
        self.signals = WorkerSignals()

    def run(self):
        try:
            # 1. Pede plano à IA (Anthropic → OpenRouter → Mock)
            plan = self.claude_client.ask_claude(self.prompt, self.context_layers)
            self.signals.progress.emit(f"Plano recebido: {len(plan.get('steps', []))} passo(s)")

            # 2. Executa plano no QGIS
            results = execute_claude_plan(plan)
            self.signals.finished.emit({"plan": plan, "results": results})
        except Exception as e:
            import traceback
            self.signals.error.emit(traceback.format_exc())


class ClaudeAIDockWidget(QDockWidget):
    closed = pyqtSignal()

    def __init__(self, iface, claude_client):
        super().__init__("Claude AI Assistant", iface.mainWindow())
        self.iface = iface
        self.claude_client = claude_client
        self.worker = None
        self.setup_ui()

    def setup_ui(self):
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setMinimumWidth(380)

        main_widget = QWidget()
        layout = QVBoxLayout(main_widget)

        # Header
        header = QHBoxLayout()
        header.addWidget(QLabel("🤖"))
        header.addWidget(QLabel("<b>Claude no QGIS</b>"))
        header.addStretch()
        layout.addLayout(header)

        # Lista de camadas (contexto)
        self.layer_combo = QComboBox()
        self.layer_combo.addItem("Todas as camadas")
        self.refresh_layers()
        layout.addWidget(QLabel("Contexto:"))
        layout.addWidget(self.layer_combo)

        # Chat area
        self.chat_log = QTextEdit()
        self.chat_log.setReadOnly(True)
        self.chat_log.setStyleSheet("""
            QTextEdit { background: #1e1e1e; color: #d4d4d4; font-family: Consolas, monospace; font-size: 12px; }
        """)
        layout.addWidget(self.chat_log)

        # Input area
        input_layout = QHBoxLayout()
        self.prompt_input = QLineEdit()
        self.prompt_input.setPlaceholderText("Ex: 'Crie buffer de 100m na camada vias e salve como buffer_vias'")
        self.prompt_input.returnPressed.connect(self.send_prompt)
        input_layout.addWidget(self.prompt_input)

        self.send_btn = QPushButton("Enviar")
        self.send_btn.clicked.connect(self.send_prompt)
        input_layout.addWidget(self.send_btn)
        layout.addLayout(input_layout)

        # Status
        self.status_label = QLabel("Pronto. Digite um comando acima.")
        self.status_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self.status_label)

        self.setWidget(main_widget)

    def refresh_layers(self):
        self.layer_combo.clear()
        self.layer_combo.addItem("Todas as camadas")
        for layer in QgsProject.instance().mapLayers().values():
            self.layer_combo.addItem(layer.name(), layer.id())

    def get_context_layers(self):
        if self.layer_combo.currentIndex() == 0:
            return [l.name() for l in QgsProject.instance().mapLayers().values()]
        return [self.layer_combo.currentText()]

    def send_prompt(self):
        prompt = self.prompt_input.text().strip()
        if not prompt:
            return

        self.prompt_input.clear()
        self.append_chat("👤 Você", prompt)
        self.status_label.setText("Enviando para Claude...")
        self.send_btn.setEnabled(False)

        # Inicia worker
        self.worker = ClaudeWorker(self.claude_client, prompt, self.get_context_layers())
        self.worker.signals.finished.connect(self.on_worker_finished)
        self.worker.signals.error.connect(self.on_worker_error)
        self.worker.signals.progress.connect(self.on_worker_progress)
        self.worker.start()

    def on_worker_progress(self, msg):
        self.status_label.setText(msg)

    def on_worker_finished(self, data):
        self.send_btn.setEnabled(True)
        plan = data["plan"]
        results = data["results"]

        self.append_chat("🤖 Claude", f"Plano: {json.dumps(plan, ensure_ascii=False, indent=2)}")

        for i, res in enumerate(results):
            if res.get("success"):
                self.append_chat("✅", f"Passo {i+1}: {res.get('result', 'OK')}")
            else:
                self.append_chat("❌", f"Passo {i+1} FALHOU: {res.get('error')}")

        self.status_label.setText("Concluído.")

    def on_worker_error(self, err):
        self.send_btn.setEnabled(True)
        self.append_chat("❌ Erro", err)
        self.status_label.setText("Erro - veja log.")

    def append_chat(self, sender, text):
        self.chat_log.append(f"<b>{sender}:</b> {text}")
        # Auto-scroll
        self.chat_log.verticalScrollBar().setValue(
            self.chat_log.verticalScrollBar().maximum()
        )

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait()
        self.closed.emit()
        super().closeEvent(event)
```

### `ai_client.py`
```python
# -*- coding: utf-8 -*-
"""
Cliente IA Multi-Provider para QGIS
Suporta: Anthropic (primário) → OpenRouter (fallback) → Mock (sem keys)
"""
import json
import os

# Anthropic
try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

# OpenRouter (OpenAI-compatible)
try:
    import openai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


SYSTEM_PROMPT = """Você é um agente que controla o QGIS via ações JSON predefinidas.
NÃO escreva código Python arbitrário. Retorne APENAS um JSON válido com esta estrutura:

{
  "steps": [
    {"action": "nome_da_acao", "params": {...}},
    {"action": "outra_acao", "params": {...}}
  ]
}

AÇÕES DISPONÍVEIS (use exatamente estes nomes):

--- CAMADAS ---

1. list_layers
   params: {}
   Retorna: lista de nomes de camadas no projeto

2. select_by_expression
   params: {"layer_name": "nome_exato", "expression": "\"campo\" = 'valor'"}
   Retorna: {"selected_count": N}

3. create_memory_layer
   params: {
     "name": "nome_layer",
     "geometry_type": "Point|LineString|Polygon",
     "fields": [{"name": "campo1", "type": "String"}],
     "features": [{"geom": "POINT(-46 -23)", "attrs": ["valor1"]}]
   }
   Retorna: {"layer_id": "id"}

4. add_vector_layer
   params: {"file_path": "C:/dados/lotes.shp", "layer_name": "lotes"}
   Retorna: {"layer_name": "nome", "feature_count": N}

5. add_raster_layer
   params: {"file_path": "C:/dados/imagem.tif", "layer_name": "imagem"}
   Retorna: {"layer_name": "nome"}

6. remove_layer
   params: {"layer_name": "nome"}
   Retorna: {"success": true}

7. zoom_to_layer
   params: {"layer_name": "nome"}
   Retorna: {"success": true}

8. export_layer
   params: {"layer_name": "nome", "output_path": "C:/temp/saida.gpkg", "format": "GPKG"}
   format pode ser: GPKG, ESRI Shapefile, CSV, GeoJSON, etc.
   Retorna: {"success": true, "output_path": "..."}

9. rename_layer
   params: {"layer_name": "nome_atual", "new_name": "nome_novo"}
   Retorna: {"success": true}

--- GEOPROCESSAMENTO (VETOR) ---

10. run_buffer
    params: {"input_layer": "nome", "distance": 100, "segments": 5, "output_name": "buffer_result"}
    Retorna: {"output_layer": "nome"}

11. run_intersection
    params: {"input_layer": "camada_a", "overlay_layer": "camada_b", "output_name": "intersecao"}
    Retorna: {"output_layer": "nome"}

12. run_difference
    params: {"input_layer": "camada_a", "overlay_layer": "camada_b", "output_name": "diferenca"}
    Retorna: {"output_layer": "nome"}

13. run_union
    params: {"input_layer": "camada_a", "overlay_layer": "camada_b", "output_name": "uniao"}
    Retorna: {"output_layer": "nome"}

14. run_dissolve
    params: {"input_layer": "nome", "field": "campo_agrupamento", "output_name": "dissolvido"}
    Retorna: {"output_layer": "nome"}

15. run_clip
    params: {"input_layer": "nome", "overlay_layer": "limite", "output_name": "recorte"}
    Retorna: {"output_layer": "nome"}

16. run_merge_layers
    params: {"input_layers": ["camada_a", "camada_b"], "output_name": "mesclado"}
    Retorna: {"output_layer": "nome"}

17. run_reproject
    params: {"input_layer": "nome", "target_crs": "EPSG:31983", "output_name": "reprojetado"}
    Retorna: {"output_layer": "nome"}

18. run_centroids
    params: {"input_layer": "nome", "output_name": "centroides"}
    Retorna: {"output_layer": "nome"}

19. run_convex_hull
    params: {"input_layer": "nome", "output_name": "fecho_convexo"}
    Retorna: {"output_layer": "nome"}

20. run_simplify
    params: {"input_layer": "nome", "tolerance": 1.0, "output_name": "simplificado"}
    Retorna: {"output_layer": "nome"}

21. run_spatial_join
    params: {"input_layer": "nome", "join_layer": "outra", "output_name": "join_result"}
    Retorna: {"output_layer": "nome"}

--- ACESSO GENÉRICO (QUALQUER algoritmo do QGIS Processing) ---

22. list_algorithms
    params: {"search_text": "raster"}  (opcional; vazio lista até 200)
    Retorna: lista de {"id": "provedor:algoritmo", "name": "Nome exibido"}
    Use isto quando o usuário pedir algo que NÃO está nas ações acima
    (ex: estatísticas de raster, recorte de raster, interpolação, grade,
    conversão de formato, etc) para descobrir o algorithm_id certo.

23. run_algorithm
    params: {
      "algorithm_id": "native:extractbyattribute",
      "params": {"INPUT": "nome_camada", "FIELD": "campo", "OPERATOR": 0, "VALUE": "x"},
      "output_name": "resultado"  (opcional, só se o algoritmo gerar uma camada)
    }
    Executa qualquer algoritmo de processing do QGIS (native:*, qgis:*, gdal:*, grass:*).
    Nomes de camada dentro de "params" são resolvidos automaticamente para a
    camada do projeto. Use os nomes de parâmetro EXATOS do algoritmo (maiúsculos,
    como aparecem na caixa de ferramentas de Processing do QGIS).
    Use esta ação como fallback universal para qualquer operação de geoprocessamento
    que não tenha uma ação dedicada acima.

--- LAYOUT / EXPORTAÇÃO DE MAPA ---

24. export_layout_pdf
    params: {"layout_name": "Layout 1", "output_path": "C:/temp/mapa.pdf"}
    Retorna: {"success": true}

25. export_layout_image
    params: {"layout_name": "Layout 1", "output_path": "C:/temp/mapa.png", "dpi": 300}
    Retorna: {"success": true}

26. list_layouts
    params: {}
    Retorna: lista de nomes de layouts/composições de impressão do projeto

--- EXPRESSÕES / ATRIBUTOS ---

27. calculate_field
    params: {"layer_name": "nome", "field_name": "novo_campo", "expression": "$area / 10000", "field_type": "Double"}
    Retorna: {"updated_features": N}

28. filter_layer
    params: {"layer_name": "nome", "expression": "\"campo\" > 100"}
    Retorna: {"success": true, "feature_count": N}

29. clear_filter
    params: {"layer_name": "nome"}
    Retorna: {"success": true, "feature_count": N}

REGRAS:
- Prefira as ações dedicadas (1-21, 24-29) quando existir uma para a tarefa.
- Se a tarefa pedida não corresponder a nenhuma ação dedicada, use list_algorithms
  para encontrar o algoritmo certo e depois run_algorithm para executá-lo — NUNCA
  diga que algo "não é possível" sem antes tentar essa rota genérica.
- Nomes de camadas devem ser EXATOS (case-sensitive)
- Distâncias em metros (assume CRS métrico) ou graus (geográfico)
- Expressões: sintaxe QGIS (ex: $area, $length, "campo" > 10)
- Se precisar de múltiplos passos, encadeie no array "steps"
- Se mesmo assim não souber como fazer, retorne steps vazio e explique no campo "explanation"
"""


class AIClient:
    """Cliente unificado: Anthropic → OpenRouter → Mock"""

    def __init__(self, api_key=None):
        # Variáveis de ambiente (definidas no OSGeo4W Shell ou Windows)
        self.anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self.openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")

        self.anthropic_client = None
        self.openrouter_client = None

        # Inicializa Anthropic (primário)
        if HAS_ANTHROPIC and self.anthropic_key:
            self.anthropic_client = anthropic.Anthropic(api_key=self.anthropic_key)

        # Inicializa OpenRouter (fallback) - OpenAI-compatible
        if HAS_OPENAI and self.openrouter_key:
            self.openrouter_client = openai.OpenAI(
                api_key=self.openrouter_key,
                base_url="https://openrouter.ai/api/v1"
            )

        self.current_provider = "mock"
        if self.anthropic_client:
            self.current_provider = "anthropic"
        elif self.openrouter_client:
            self.current_provider = "openrouter"

        # Cache de modelos gratuitos da OpenRouter (preenchido sob demanda)
        self._openrouter_free_models = None

    def ask_claude(self, prompt, context_layers):
        """Tenta provedores em ordem: Anthropic → OpenRouter → Mock
        (nome mantido por compatibilidade com dockwidget.py)"""
        layers_ctx = ", ".join(context_layers) if context_layers else "nenhuma"
        full_prompt = f"""Camadas disponíveis no projeto: {layers_ctx}

Solicitação do usuário: {prompt}

Retorne APENAS o JSON do plano."""

        # 1. Tenta Anthropic
        if self.anthropic_client:
            try:
                return self._ask_anthropic(full_prompt)
            except Exception as e:
                print(f"[AIClient] Anthropic falhou: {e} — tentando OpenRouter...")

        # 2. Tenta OpenRouter (fallback)
        if self.openrouter_client:
            try:
                return self._ask_openrouter(full_prompt)
            except Exception as e:
                print(f"[AIClient] OpenRouter falhou: {e} — usando mock...")

        # 3. Mock
        return self._mock_plan(prompt)

    def _ask_anthropic(self, prompt):
        resp = self.anthropic_client.messages.create(
            model="claude-sonnet-5",
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}]
        )
        content = resp.content[0].text.strip()
        return self._parse_json(content, "anthropic")

    def _discover_free_openrouter_models(self):
        """Busca na OpenRouter quais modelos estão disponíveis gratuitamente
        (id termina em ':free'). Resultado fica em cache na instância para não
        repetir a consulta a cada pergunta."""
        if self._openrouter_free_models:
            return self._openrouter_free_models

        # Lista de preferência: tenta estes primeiro, se estiverem disponíveis,
        # pois costumam ser mais estáveis para retornar JSON bem formado.
        preferred = [
            "nvidia/nemotron-3.5-lightning:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "google/gemini-2.0-flash-exp:free",
            "deepseek/deepseek-chat:free",
            "deepseek/deepseek-chat-v3-0324:free",
            "mistralai/mistral-7b-instruct:free",
            "qwen/qwen-2.5-72b-instruct:free",
        ]

        live_free_models = []
        try:
            resp = self.openrouter_client.models.list()
            all_ids = [m.id for m in resp.data]
            live_free_models = [m for m in all_ids if m.endswith(":free")]
        except Exception as e:
            print(f"[AIClient] Não consegui listar modelos da OpenRouter: {e}")

        if live_free_models:
            # Prioriza os conhecidos bons (se realmente existirem agora),
            # depois completa com os demais gratuitos encontrados.
            ordered = [m for m in preferred if m in live_free_models]
            ordered += [m for m in live_free_models if m not in ordered]
        else:
            # Não deu pra consultar a lista ao vivo: tenta os conhecidos mesmo assim.
            ordered = preferred

        self._openrouter_free_models = ordered
        return ordered

    def _ask_openrouter(self, prompt):
        """OpenRouter usa formato OpenAI chat.completions.
        Busca um modelo gratuito disponível e tenta a lista em ordem até um
        funcionar (modelos free da OpenRouter mudam/saem do ar com frequência)."""
        models_to_try = self._discover_free_openrouter_models()
        if not models_to_try:
            raise RuntimeError("Nenhum modelo gratuito encontrado na OpenRouter.")

        last_error = None
        for model in models_to_try:
            try:
                resp = self.openrouter_client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=2000,
                    temperature=0.1,
                )
                content = resp.choices[0].message.content.strip()
                return self._parse_json(content, f"openrouter:{model}")
            except Exception as e:
                last_error = e
                print(f"[AIClient] OpenRouter modelo '{model}' falhou: {e} — tentando próximo modelo gratuito...")
                continue

        raise last_error if last_error else RuntimeError("Todos os modelos gratuitos da OpenRouter falharam.")

    def _parse_json(self, content, provider):
        # Remove markdown code fences se vier
        if content.startswith("```"):
            parts = content.split("```")
            if len(parts) >= 2:
                content = parts[1]
                if content.startswith("json"):
                    content = content[4:]
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError as e:
            return {"steps": [], "explanation": f"Erro parse JSON ({provider}): {e}. Resposta: {content[:200]}"}

    def _mock_plan(self, prompt):
        """Plano simulado para testar sem API key."""
        prompt_lower = prompt.lower()
        if "buffer" in prompt_lower:
            return {
                "steps": [
                    {"action": "run_buffer", "params": {
                        "input_layer": "vias",
                        "distance": 100,
                        "output_name": "buffer_vias"
                    }}
                ]
            }
        if "list" in prompt_lower or "camada" in prompt_lower:
            return {"steps": [{"action": "list_layers", "params": {}}]}
        if "intersec" in prompt_lower:
            return {
                "steps": [
                    {"action": "run_intersection", "params": {
                        "input_layer": "vias",
                        "overlay_layer": "lotes",
                        "output_name": "vias_lotes"
                    }}
                ]
            }
        return {"steps": [], "explanation": "Comando não reconhecido (mock). Configure ANTHROPIC_API_KEY ou OPENROUTER_API_KEY."}

    def get_provider(self):
        return self.current_provider


# Alias para compatibilidade com código existente (dockwidget.py, __init__.py)
ClaudeClient = AIClient

```

### `executor.py`
```python
# -*- coding: utf-8 -*-
"""
Executor - Executa planos JSON no QGIS (sandbox seguro)
"""
import traceback
from .actions import layers, processing, layout, expressions


ACTIONS = {
    # Camadas
    "list_layers": layers.list_layers,
    "select_by_expression": layers.select_by_expression,
    "create_memory_layer": layers.create_memory_layer,
    "add_vector_layer": layers.add_vector_layer,
    "add_raster_layer": layers.add_raster_layer,
    "remove_layer": layers.remove_layer,
    "zoom_to_layer": layers.zoom_to_layer,
    "export_layer": layers.export_layer,
    "rename_layer": layers.rename_layer,

    # Geoprocessamento (vetor)
    "run_buffer": processing.run_buffer,
    "run_intersection": processing.run_intersection,
    "run_difference": processing.run_difference,
    "run_union": processing.run_union,
    "run_dissolve": processing.run_dissolve,
    "run_clip": processing.run_clip,
    "run_merge_layers": processing.run_merge_layers,
    "run_reproject": processing.run_reproject,
    "run_centroids": processing.run_centroids,
    "run_convex_hull": processing.run_convex_hull,
    "run_simplify": processing.run_simplify,
    "run_spatial_join": processing.run_spatial_join,

    # Acesso genérico a QUALQUER algoritmo de Processing do QGIS
    "run_algorithm": processing.run_algorithm,
    "list_algorithms": processing.list_algorithms,

    # Layout / exportação
    "export_layout_pdf": layout.export_pdf,
    "export_layout_image": layout.export_image,
    "list_layouts": layout.list_layouts,

    # Expressões / atributos
    "calculate_field": expressions.calculate_field,
    "filter_layer": expressions.filter_layer,
    "clear_filter": expressions.clear_filter,
}


def execute_claude_plan(plan):
    """Executa lista de passos do plano. Retorna lista de resultados."""
    results = []
    for step in plan.get("steps", []):
        action_name = step.get("action")
        params = step.get("params", {})

        if action_name not in ACTIONS:
            results.append({
                "success": False,
                "error": f"Ação não permitida: {action_name}. Disponíveis: {list(ACTIONS.keys())}"
            })
            break

        try:
            func = ACTIONS[action_name]
            result = func(**params)
            results.append({"success": True, "result": result})
        except Exception as e:
            results.append({
                "success": False,
                "error": traceback.format_exc()
            })
            break
    return results
```

### `actions/__init__.py`
```python
# -*- coding: utf-8 -*-
"""
Actions package - Whitelist de ações seguras para o Claude executar
"""
from . import layers, processing, layout, expressions

__all__ = ["layers", "processing", "layout", "expressions"]
```

### `actions/layers.py`
```python
# -*- coding: utf-8 -*-
"""
Actions: layers - Operações com camadas
"""
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsRasterLayer, QgsFeature, QgsGeometry,
    QgsField, QgsWkbTypes, QgsCoordinateReferenceSystem,
    QgsVectorFileWriter
)
from qgis.PyQt.QtCore import QVariant


def _get_layer(layer_name):
    layers = QgsProject.instance().mapLayersByName(layer_name)
    if not layers:
        raise ValueError(f"Camada não encontrada: {layer_name}")
    return layers[0]


def list_layers():
    """Lista todas as camadas do projeto."""
    return [l.name() for l in QgsProject.instance().mapLayers().values()]


def add_vector_layer(file_path, layer_name=None):
    """Carrega uma camada vetorial de um arquivo (shapefile, geopackage, etc)."""
    name = layer_name or file_path.split("/")[-1].split("\\")[-1]
    layer = QgsVectorLayer(file_path, name, "ogr")
    if not layer.isValid():
        raise RuntimeError(f"Falha ao carregar camada vetorial: {file_path}")
    QgsProject.instance().addMapLayer(layer)
    return {"layer_name": layer.name(), "feature_count": layer.featureCount()}


def add_raster_layer(file_path, layer_name=None):
    """Carrega uma camada raster de um arquivo (GeoTIFF, etc)."""
    name = layer_name or file_path.split("/")[-1].split("\\")[-1]
    layer = QgsRasterLayer(file_path, name)
    if not layer.isValid():
        raise RuntimeError(f"Falha ao carregar camada raster: {file_path}")
    QgsProject.instance().addMapLayer(layer)
    return {"layer_name": layer.name()}


def remove_layer(layer_name):
    """Remove uma camada do projeto pelo nome."""
    layer = _get_layer(layer_name)
    QgsProject.instance().removeMapLayer(layer.id())
    return {"success": True, "removed": layer_name}


def zoom_to_layer(layer_name):
    """Centraliza/ajusta o mapa na extensão de uma camada."""
    from qgis.utils import iface
    layer = _get_layer(layer_name)
    iface.mapCanvas().setExtent(layer.extent())
    iface.mapCanvas().refresh()
    return {"success": True, "layer": layer_name}


def export_layer(layer_name, output_path, format="GPKG"):
    """
    Exporta/salva uma camada vetorial para arquivo.
    format: 'GPKG' (GeoPackage), 'ESRI Shapefile', 'CSV', 'GeoJSON', etc.
    """
    layer = _get_layer(layer_name)
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = format
    error = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, output_path, QgsProject.instance().transformContext(), options
    )
    if error[0] != QgsVectorFileWriter.NoError:
        raise RuntimeError(f"Falha ao exportar camada: {error}")
    return {"success": True, "output_path": output_path}


def rename_layer(layer_name, new_name):
    """Renomeia uma camada."""
    layer = _get_layer(layer_name)
    layer.setName(new_name)
    return {"success": True, "new_name": new_name}


def select_by_expression(layer_name, expression):
    """Seleciona feições por expressão QGIS."""
    layers = QgsProject.instance().mapLayersByName(layer_name)
    if not layers:
        raise ValueError(f"Camada não encontrada: {layer_name}")
    layer = layers[0]
    layer.selectByExpression(expression)
    return {"selected_count": layer.selectedFeatureCount()}


def create_memory_layer(name, geometry_type="Point", fields=None, features=None):
    """Cria layer temporário em memória."""
    # Mapeia tipo string para QgsWkbTypes
    type_map = {
        "Point": QgsWkbTypes.Point,
        "LineString": QgsWkbTypes.LineString,
        "Polygon": QgsWkbTypes.Polygon,
        "MultiPoint": QgsWkbTypes.MultiPoint,
        "MultiLineString": QgsWkbTypes.MultiLineString,
        "MultiPolygon": QgsWkbTypes.MultiPolygon,
    }
    wkb_type = type_map.get(geometry_type, QgsWkbTypes.Point)

    uri = f"{geometry_type}?crs=epsg:4326"
    layer = QgsVectorLayer(uri, name, "memory")
    if not layer.isValid():
        raise RuntimeError("Falha ao criar layer em memória")

    prov = layer.dataProvider()

    # Campos
    if fields:
        qgs_fields = []
        for f in fields:
            fname = f.get("name", "campo")
            ftype_str = f.get("type", "String").lower()
            type_map_field = {
                "string": QVariant.String,
                "int": QVariant.Int,
                "integer": QVariant.Int,
                "double": QVariant.Double,
                "float": QVariant.Double,
                "bool": QVariant.Bool,
                "boolean": QVariant.Bool,
                "date": QVariant.Date,
            }
            qvar_type = type_map_field.get(ftype_str, QVariant.String)
            qgs_fields.append(QgsField(fname, qvar_type))
        prov.addAttributes(qgs_fields)
        layer.updateFields()

    # Feições
    if features:
        feats = []
        for f in features:
            feat = QgsFeature(layer.fields())
            geom_wkt = f.get("geom")
            if geom_wkt:
                geom = QgsGeometry.fromWkt(geom_wkt)
                if geom.isNull():
                    raise ValueError(f"Geometria WKT inválida: {geom_wkt}")
                feat.setGeometry(geom)
            attrs = f.get("attrs", [])
            feat.setAttributes(attrs)
            feats.append(feat)
        prov.addFeatures(feats)
        layer.updateExtents()

    QgsProject.instance().addMapLayer(layer)
    return {"layer_id": layer.id(), "feature_count": layer.featureCount()}
```

### `actions/processing.py`
```python
# -*- coding: utf-8 -*-
"""
Actions: processing - Algoritmos de processamento (buffer, intersecção, etc)
"""
from qgis.core import QgsProject, QgsProcessingFeedback, QgsProcessingContext
import processing


def _get_layer(layer_name):
    layers = QgsProject.instance().mapLayersByName(layer_name)
    if not layers:
        raise ValueError(f"Camada não encontrada: {layer_name}")
    return layers[0]


def run_buffer(input_layer, distance, segments=5, end_cap_style=0, join_style=0, miter_limit=2, output_name="buffer_result"):
    """Buffer via processing (nativo QGIS)."""
    layer = _get_layer(input_layer)

    params = {
        "INPUT": layer,
        "DISTANCE": distance,
        "SEGMENTS": segments,
        "END_CAP_STYLE": end_cap_style,  # 0=Round, 1=Flat, 2=Square
        "JOIN_STYLE": join_style,        # 0=Round, 1=Miter, 2=Bevel
        "MITER_LIMIT": miter_limit,
        "DISSOLVE": False,
        "OUTPUT": "memory:" + output_name
    }

    feedback = QgsProcessingFeedback()
    context = QgsProcessingContext()
    result = processing.run("native:buffer", params, context=context, feedback=feedback)

    out_layer = result["OUTPUT"]
    out_layer.setName(output_name)
    QgsProject.instance().addMapLayer(out_layer)
    return {"output_layer": output_name, "feature_count": out_layer.featureCount()}


def run_intersection(input_layer, overlay_layer, output_name="intersecao", input_fields=None, overlay_fields=None, overlay_fields_prefix=""):
    """Intersecção entre duas camadas."""
    in_layer = _get_layer(input_layer)
    ov_layer = _get_layer(overlay_layer)

    params = {
        "INPUT": in_layer,
        "OVERLAY": ov_layer,
        "INPUT_FIELDS": input_fields or [],
        "OVERLAY_FIELDS": overlay_fields or [],
        "OVERLAY_FIELDS_PREFIX": overlay_fields_prefix,
        "OUTPUT": "memory:" + output_name
    }

    feedback = QgsProcessingFeedback()
    context = QgsProcessingContext()
    result = processing.run("native:intersection", params, context=context, feedback=feedback)

    out_layer = result["OUTPUT"]
    out_layer.setName(output_name)
    QgsProject.instance().addMapLayer(out_layer)
    return {"output_layer": output_name, "feature_count": out_layer.featureCount()}


def run_difference(input_layer, overlay_layer, output_name="diferenca"):
    """Diferença (A - B)."""
    in_layer = _get_layer(input_layer)
    ov_layer = _get_layer(overlay_layer)

    params = {
        "INPUT": in_layer,
        "OVERLAY": ov_layer,
        "OUTPUT": "memory:" + output_name
    }

    feedback = QgsProcessingFeedback()
    context = QgsProcessingContext()
    result = processing.run("native:difference", params, context=context, feedback=feedback)

    out_layer = result["OUTPUT"]
    out_layer.setName(output_name)
    QgsProject.instance().addMapLayer(out_layer)
    return {"output_layer": output_name, "feature_count": out_layer.featureCount()}


def run_union(input_layer, overlay_layer, output_name="uniao"):
    """União de duas camadas."""
    in_layer = _get_layer(input_layer)
    ov_layer = _get_layer(overlay_layer)

    params = {
        "INPUT": in_layer,
        "OVERLAY": ov_layer,
        "OUTPUT": "memory:" + output_name
    }

    feedback = QgsProcessingFeedback()
    context = QgsProcessingContext()
    result = processing.run("native:union", params, context=context, feedback=feedback)

    out_layer = result["OUTPUT"]
    out_layer.setName(output_name)
    QgsProject.instance().addMapLayer(out_layer)
    return {"output_layer": output_name, "feature_count": out_layer.featureCount()}


def run_dissolve(input_layer, field=None, output_name="dissolvido"):
    """Dissolve (agrega feições)."""
    layer = _get_layer(input_layer)

    params = {
        "INPUT": layer,
        "FIELD": field or [],
        "OUTPUT": "memory:" + output_name
    }

    feedback = QgsProcessingFeedback()
    context = QgsProcessingContext()
    result = processing.run("native:dissolve", params, context=context, feedback=feedback)

    out_layer = result["OUTPUT"]
    out_layer.setName(output_name)
    QgsProject.instance().addMapLayer(out_layer)
    return {"output_layer": output_name, "feature_count": out_layer.featureCount()}


def run_clip(input_layer, overlay_layer, output_name="clip_result"):
    """Recorta uma camada pelos limites de outra (native:clip)."""
    in_layer = _get_layer(input_layer)
    ov_layer = _get_layer(overlay_layer)

    params = {
        "INPUT": in_layer,
        "OVERLAY": ov_layer,
        "OUTPUT": "memory:" + output_name
    }
    feedback = QgsProcessingFeedback()
    context = QgsProcessingContext()
    result = processing.run("native:clip", params, context=context, feedback=feedback)

    out_layer = result["OUTPUT"]
    out_layer.setName(output_name)
    QgsProject.instance().addMapLayer(out_layer)
    return {"output_layer": output_name, "feature_count": out_layer.featureCount()}


def run_merge_layers(input_layers, output_name="merge_result"):
    """Mescla (une) várias camadas vetoriais em uma só (native:mergevectorlayers)."""
    layers_objs = [_get_layer(n) for n in input_layers]

    params = {
        "LAYERS": layers_objs,
        "OUTPUT": "memory:" + output_name
    }
    feedback = QgsProcessingFeedback()
    context = QgsProcessingContext()
    result = processing.run("native:mergevectorlayers", params, context=context, feedback=feedback)

    out_layer = result["OUTPUT"]
    out_layer.setName(output_name)
    QgsProject.instance().addMapLayer(out_layer)
    return {"output_layer": output_name, "feature_count": out_layer.featureCount()}


def run_reproject(input_layer, target_crs, output_name="reprojetado"):
    """Reprojeta uma camada para outro CRS (native:reprojectlayer). target_crs ex: 'EPSG:31983'."""
    layer = _get_layer(input_layer)

    params = {
        "INPUT": layer,
        "TARGET_CRS": target_crs,
        "OUTPUT": "memory:" + output_name
    }
    feedback = QgsProcessingFeedback()
    context = QgsProcessingContext()
    result = processing.run("native:reprojectlayer", params, context=context, feedback=feedback)

    out_layer = result["OUTPUT"]
    out_layer.setName(output_name)
    QgsProject.instance().addMapLayer(out_layer)
    return {"output_layer": output_name, "feature_count": out_layer.featureCount()}


def run_centroids(input_layer, output_name="centroides"):
    """Gera pontos de centroide das feições (native:centroids)."""
    layer = _get_layer(input_layer)
    params = {"INPUT": layer, "OUTPUT": "memory:" + output_name}
    feedback = QgsProcessingFeedback()
    context = QgsProcessingContext()
    result = processing.run("native:centroids", params, context=context, feedback=feedback)
    out_layer = result["OUTPUT"]
    out_layer.setName(output_name)
    QgsProject.instance().addMapLayer(out_layer)
    return {"output_layer": output_name, "feature_count": out_layer.featureCount()}


def run_convex_hull(input_layer, output_name="convex_hull"):
    """Gera o fecho convexo das feições (native:convexhull)."""
    layer = _get_layer(input_layer)
    params = {"INPUT": layer, "OUTPUT": "memory:" + output_name}
    feedback = QgsProcessingFeedback()
    context = QgsProcessingContext()
    result = processing.run("native:convexhull", params, context=context, feedback=feedback)
    out_layer = result["OUTPUT"]
    out_layer.setName(output_name)
    QgsProject.instance().addMapLayer(out_layer)
    return {"output_layer": output_name, "feature_count": out_layer.featureCount()}


def run_simplify(input_layer, tolerance=1.0, output_name="simplificado"):
    """Simplifica geometrias (native:simplifygeometries)."""
    layer = _get_layer(input_layer)
    params = {
        "INPUT": layer,
        "METHOD": 0,
        "TOLERANCE": tolerance,
        "OUTPUT": "memory:" + output_name
    }
    feedback = QgsProcessingFeedback()
    context = QgsProcessingContext()
    result = processing.run("native:simplifygeometries", params, context=context, feedback=feedback)
    out_layer = result["OUTPUT"]
    out_layer.setName(output_name)
    QgsProject.instance().addMapLayer(out_layer)
    return {"output_layer": output_name, "feature_count": out_layer.featureCount()}


def run_spatial_join(input_layer, join_layer, output_name="join_result", join_type="one-to-many"):
    """Junta atributos por localização espacial (native:joinattributesbylocation)."""
    in_layer = _get_layer(input_layer)
    jn_layer = _get_layer(join_layer)
    discard = 1 if join_type == "one-to-one" else 0
    params = {
        "INPUT": in_layer,
        "JOIN": jn_layer,
        "PREDICATE": [0],  # intersects
        "JOIN_FIELDS": [],
        "METHOD": discard,
        "DISCARD_NONMATCHING": False,
        "OUTPUT": "memory:" + output_name
    }
    feedback = QgsProcessingFeedback()
    context = QgsProcessingContext()
    result = processing.run("native:joinattributesbylocation", params, context=context, feedback=feedback)
    out_layer = result["OUTPUT"]
    out_layer.setName(output_name)
    QgsProject.instance().addMapLayer(out_layer)
    return {"output_layer": output_name, "feature_count": out_layer.featureCount()}


def run_algorithm(algorithm_id, params, output_name=None):
    """
    Executa QUALQUER algoritmo de Processing do QGIS pelo seu ID
    (ex: "native:extractbyattribute", "qgis:fieldcalculator", "gdal:cliprasterbymasklayer").
    Use list_algorithms para descobrir IDs e use_layer_name=True em params
    onde o algoritmo pede uma camada (o nome exato da camada no projeto).

    params: dict no formato esperado pelo algoritmo (chaves maiúsculas, como na
            caixa de ferramentas do QGIS). Nomes de camada em params são resolvidos
            automaticamente para o objeto de camada do projeto.
    output_name: se informado, o resultado em params['OUTPUT'] (ou primeira saída
                 encontrada) é adicionado ao projeto com este nome.
    """
    resolved_params = {}
    for key, value in (params or {}).items():
        if isinstance(value, str):
            matches = QgsProject.instance().mapLayersByName(value)
            resolved_params[key] = matches[0] if matches else value
        else:
            resolved_params[key] = value

    if "OUTPUT" not in resolved_params and output_name:
        resolved_params["OUTPUT"] = "memory:" + output_name

    feedback = QgsProcessingFeedback()
    context = QgsProcessingContext()
    result = processing.run(algorithm_id, resolved_params, context=context, feedback=feedback)

    if output_name and "OUTPUT" in result:
        out_layer = result["OUTPUT"]
        if hasattr(out_layer, "setName"):
            out_layer.setName(output_name)
            QgsProject.instance().addMapLayer(out_layer)
            return {"output_layer": output_name, "feature_count": out_layer.featureCount()}

    # Resultado não é uma camada (ex: estatísticas, arquivo exportado) - retorna bruto
    safe_result = {}
    for k, v in result.items():
        safe_result[k] = v if isinstance(v, (str, int, float, bool, type(None))) else str(v)
    return safe_result


def list_algorithms(search_text=""):
    """
    Lista IDs de algoritmos de Processing disponíveis no QGIS, opcionalmente
    filtrando por texto (ex: 'buffer', 'clip', 'raster'). Use para descobrir
    o algorithm_id certo antes de chamar run_algorithm.
    """
    from qgis.core import QgsApplication
    registry = QgsApplication.processingRegistry()
    search_lower = (search_text or "").lower()
    results = []
    for alg in registry.algorithms():
        alg_id = alg.id()
        alg_name = alg.displayName()
        if search_lower and search_lower not in alg_id.lower() and search_lower not in alg_name.lower():
            continue
        results.append({"id": alg_id, "name": alg_name})
    return results[:200]
```

### `actions/layout.py`
```python
# -*- coding: utf-8 -*-
"""
Actions: layout - Exportação de layouts/mapás
"""
from qgis.core import QgsProject, QgsLayoutExporter


def export_pdf(layout_name, output_path):
    """Exporta layout de impressão para PDF."""
    project = QgsProject.instance()
    manager = project.layoutManager()
    layout = manager.layoutByName(layout_name)

    if not layout:
        layouts = [l.name() for l in manager.layouts()]
        raise ValueError(f"Layout '{layout_name}' não encontrado. Disponíveis: {layouts}")

    exporter = QgsLayoutExporter(layout)
    settings = QgsLayoutExporter.PdfExportSettings()
    result = exporter.exportToPdf(output_path, settings)

    if result != QgsLayoutExporter.Success:
        raise RuntimeError(f"Falha ao exportar PDF: código {result}")

    return {"success": True, "output_path": output_path}


def export_image(layout_name, output_path, dpi=300):
    """Exporta layout para imagem (PNG/JPG)."""
    project = QgsProject.instance()
    manager = project.layoutManager()
    layout = manager.layoutByName(layout_name)

    if not layout:
        raise ValueError(f"Layout '{layout_name}' não encontrado")

    exporter = QgsLayoutExporter(layout)
    settings = QgsLayoutExporter.ImageExportSettings()
    settings.dpi = dpi
    result = exporter.exportToImage(output_path, settings)

    if result != QgsLayoutExporter.Success:
        raise RuntimeError(f"Falha ao exportar imagem: código {result}")

    return {"success": True, "output_path": output_path}


def list_layouts():
    """Lista todos os layouts do projeto."""
    return [l.name() for l in QgsProject.instance().layoutManager().layouts()]
```

### `actions/expressions.py`
```python
# -*- coding: utf-8 -*-
"""
Actions: expressions - Calculadora de campos, filtros
"""
from qgis.core import QgsProject, QgsExpression, QgsExpressionContext, QgsExpressionContextUtils
from qgis.PyQt.QtCore import QVariant


def _get_layer(layer_name):
    layers = QgsProject.instance().mapLayersByName(layer_name)
    if not layers:
        raise ValueError(f"Camada não encontrada: {layer_name}")
    return layers[0]


def calculate_field(layer_name, field_name, expression, field_type="String", field_length=255, field_precision=0, only_selected=False):
    """Calcula/atualiza campo via expressão QGIS."""
    layer = _get_layer(layer_name)

    # Tipos suportados
    type_map = {
        "String": QVariant.String,
        "Int": QVariant.Int,
        "Integer": QVariant.Int,
        "Double": QVariant.Double,
        "Float": QVariant.Double,
        "Bool": QVariant.Bool,
        "Boolean": QVariant.Bool,
        "Date": QVariant.Date,
    }
    qvar_type = type_map.get(field_type, QVariant.String)

    # Adiciona campo se não existe
    if field_name not in [f.name() for f in layer.fields()]:
        from qgis.core import QgsField
        layer.dataProvider().addAttributes([QgsField(field_name, qvar_type, len=field_length, prec=field_precision)])
        layer.updateFields()

    # Prepara contexto de expressão
    context = QgsExpressionContext()
    context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))

    expr = QgsExpression(expression)
    if expr.hasParserError():
        raise ValueError(f"Erro na expressão: {expr.parserErrorString()}")

    # Edita
    layer.startEditing()
    try:
        features = layer.selectedFeatures() if only_selected else layer.getFeatures()
        count = 0
        for feat in features:
            context.setFeature(feat)
            value = expr.evaluate(context)
            if expr.hasEvalError():
                raise RuntimeError(f"Erro ao avaliar: {expr.evalErrorString()}")
            layer.changeAttributeValue(feat.id(), layer.fields().indexOf(field_name), value)
            count += 1
        layer.commitChanges()
    except Exception:
        layer.rollBack()
        raise

    return {"updated_features": count, "field_name": field_name}


def filter_layer(layer_name, expression):
    """Aplica filtro (subset string) na camada."""
    layer = _get_layer(layer_name)
    layer.setSubsetString(expression)
    return {"success": True, "filter": expression, "feature_count": layer.featureCount()}


def clear_filter(layer_name):
    """Remove filtro da camada."""
    layer = _get_layer(layer_name)
    layer.setSubsetString("")
    return {"success": True, "feature_count": layer.featureCount()}
```

---

## 5. Pendências / próximos passos sugeridos

- [ ] Publicar o repositório no GitHub (ver seção 3.6) — rodar `git remote add
      origin` + `git push -u origin master --tags` dentro da pasta extraída do
      `qgis-claude-ai-v1.0.0.zip`.
- [ ] Editar `metadata.txt`: `author`, `email`, `repository` (hoje são placeholders
      genéricos, de propósito, para não publicar dados sem confirmação).
- [ ] Página de configurações no próprio plugin para digitar as chaves de API sem
      mexer em variáveis de ambiente do sistema operacional.
- [ ] Considerar reativar o Gemini como mais um fallback (depois do Anthropic e do
      OpenRouter), já que a arquitetura de `ai_client.py` foi desenhada para
      suportar múltiplos provedores em cadeia.
- [ ] Histórico de conversas persistente entre sessões do QGIS (hoje o chat limpa
      quando o painel é recriado).
- [ ] Testes automatizados para as funções em `actions/`.

## 6. Notas de ambiente para quem for continuar

- Sistema: Windows 11, `desktop-rga61di`, QGIS Desktop 3.44.15.
- Chaves de API ficam em variáveis de ambiente de **usuário** do Windows
  (`ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`) — nunca em arquivo versionado.
- **Cuidado**: se o QGIS for aberto por automação (não clicando no ícone), ele pode
  herdar um ambiente de processo desatualizado e não enxergar uma variável de
  ambiente recém-criada, mesmo depois de "reiniciado" por automação. A solução
  confiável é o usuário fechar e reabrir o QGIS manualmente.
- As 3 pastas do plugin (`C:\Users\User\qgis_claude_ai\` e as duas dentro do perfil
  do QGIS) precisam ser mantidas idênticas manualmente — não há symlink nem
  sincronização automática entre elas.
- Para recarregar o código sem fechar o QGIS, dá pra usar `importlib.reload(modulo)`
  no Console Python do QGIS (Complementos → Console Python, ou Ctrl+Alt+P), mas
  instâncias já criadas de classes antigas não pegam a mudança — é preciso recriar o
  objeto (ex.: reabrir o painel do plugin) depois do reload.

---

*Fim do export. Este arquivo foi gerado automaticamente a partir do estado real dos
arquivos no computador do usuário em 2026-11-19.*
