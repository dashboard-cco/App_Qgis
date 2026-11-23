# -*- coding: utf-8 -*-
"""
Cliente IA multi-provider: Anthropic -> OpenRouter (modelos :free) -> Mock.
Trabalha com histórico de mensagens (loop de agente) e gera o prompt de sistema
automaticamente a partir do registro de ações.
"""
import json
import os
import re

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

try:
    import openai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

MAX_TOKENS = 4000

PROMPT_HEAD = """Você é um agente que controla o QGIS executando ações predefinidas. NÃO escreva código Python.
Responda SEMPRE e SOMENTE com um objeto JSON:

{"steps": [{"action": "nome", "params": {...}}, ...],
 "explanation": "texto curto para o usuário (em português)",
 "continue": false}

Como trabalhar:
- Cada mensagem do usuário traz o ESTADO DO PROJETO (camadas, CRS, campos). Use os nomes EXATOS.
- Depois de executar seus passos, o sistema devolve os resultados. Se "continue": true, você recebe os
  resultados e pode planejar o próximo lote; use isso para consultar antes de agir
  (list_algorithms -> describe_algorithm -> run_algorithm). Com "continue": false você encerra e
  "explanation" é mostrada ao usuário como resposta final (resuma o que foi feito).
- Se um passo falhar, leia o erro, corrija os parâmetros e tente de novo (continue: true).
- Para pedidos que não têm ação dedicada, NUNCA diga que é impossível: use list_algorithms para achar
  o algoritmo, describe_algorithm para ver os parâmetros EXATOS e run_algorithm para executar.
  Funciona com native:*, gdal:*, qgis:*, grass:* instalados.
- Prefira ações dedicadas quando existirem. Para saídas, dê output_name descritivo; resultados vão
  para camadas temporárias a menos que o usuário peça um arquivo (output_path / export_layer).
- Pergunta ou conversa sem ação: steps vazio e resposta em "explanation".
- Falte um dado essencial (ex.: qual camada, qual distância)? steps vazio e pergunte em "explanation".
- Distâncias seguem a unidade do CRS da camada (metros se projetado, graus se geográfico);
  se a camada estiver em graus e o usuário falar em metros, reprojete antes (ex.: EPSG:31983 para SP).
- Expressões usam a sintaxe de expressões do QGIS ("campo" > 10, $area, etc.).
- Caminhos no Windows: use / ou \\\\ no JSON.
- Rotas: native:shortestpathpointtopoint / native:shortestpathlayertopoint / native:serviceareafrompoint
  (rede = camada de linhas; STRATEGY 0=mais curto, 1=mais rápido). Veja com describe_algorithm.

AÇÕES DISPONÍVEIS ([consulta] = só lê e normalmente exige continue:true; [altera dados]/[apaga] pedem
confirmação do usuário):
"""


def build_system_prompt():
    from .registry import build_catalog
    from . import actions  # noqa: F401
    return PROMPT_HEAD + build_catalog()


def extract_json(content):
    """Extrai o objeto JSON da resposta (tolera ```json e texto em volta)."""
    text = content.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    else:
        a, b = text.find("{"), text.rfind("}")
        if a != -1 and b > a:
            text = text[a:b + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"steps": [], "explanation": content.strip()[:1500], "continue": False}
    if not isinstance(data, dict):
        return {"steps": [], "explanation": str(data)[:500], "continue": False}
    if not isinstance(data.get("steps"), list):
        data["steps"] = []
    return data


class AIClient:
    """Anthropic -> OpenRouter -> Mock."""

    def __init__(self, api_key=None):
        self.anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self.openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
        self.model = os.environ.get("QGIS_AI_MODEL", "claude-sonnet-5")
        self.anthropic_client = None
        self.openrouter_client = None
        if HAS_ANTHROPIC and self.anthropic_key:
            self.anthropic_client = anthropic.Anthropic(api_key=self.anthropic_key)
        if HAS_OPENAI and self.openrouter_key:
            self.openrouter_client = openai.OpenAI(api_key=self.openrouter_key,
                                                   base_url="https://openrouter.ai/api/v1")
        self.current_provider = ("anthropic" if self.anthropic_client else
                                 "openrouter" if self.openrouter_client else "mock")
        self._openrouter_free_models = None
        self._system = None
        self.last_provider_used = None

    @property
    def system_prompt(self):
        if self._system is None:
            self._system = build_system_prompt()
        return self._system

    # ---- API principal: recebe histórico [{"role","content"}], devolve plano
    def ask(self, messages):
        if self.anthropic_client:
            try:
                plan = self._ask_anthropic(messages)
                self.last_provider_used = "anthropic"
                return plan
            except Exception as e:
                print(f"[AIClient] Anthropic falhou: {e} — tentando OpenRouter...")
        if self.openrouter_client:
            try:
                plan = self._ask_openrouter(messages)
                self.last_provider_used = "openrouter"
                return plan
            except Exception as e:
                print(f"[AIClient] OpenRouter falhou: {e} — usando mock...")
        self.last_provider_used = "mock"
        return self._mock_plan(messages[0]["content"] if messages else "")

    def ask_claude(self, prompt, context_layers):
        """Compatibilidade com a versão 1.0 (chamada única, sem histórico)."""
        return self.ask([{"role": "user",
                          "content": f"Camadas: {', '.join(context_layers)}\n\n{prompt}"}])

    def _ask_anthropic(self, messages):
        resp = self.anthropic_client.messages.create(
            model=self.model, max_tokens=MAX_TOKENS, system=self.system_prompt, messages=messages)
        return extract_json(resp.content[0].text)

    def _discover_free_openrouter_models(self):
        if self._openrouter_free_models:
            return self._openrouter_free_models
        preferred = ["meta-llama/llama-3.3-70b-instruct:free", "deepseek/deepseek-chat-v3-0324:free",
                     "qwen/qwen-2.5-72b-instruct:free", "google/gemini-2.0-flash-exp:free",
                     "deepseek/deepseek-chat:free", "nvidia/nemotron-3.5-lightning:free"]
        live = []
        try:
            live = [m.id for m in self.openrouter_client.models.list().data if m.id.endswith(":free")]
        except Exception as e:
            print(f"[AIClient] Não consegui listar modelos da OpenRouter: {e}")
        if live:
            ordered = [m for m in preferred if m in live] + [m for m in live if m not in preferred]
        else:
            ordered = preferred
        self._openrouter_free_models = ordered
        return ordered

    def _ask_openrouter(self, messages):
        models = self._discover_free_openrouter_models()
        if not models:
            raise RuntimeError("Nenhum modelo gratuito na OpenRouter.")
        last = None
        for model in models:
            try:
                resp = self.openrouter_client.chat.completions.create(
                    model=model, max_tokens=MAX_TOKENS, temperature=0.1,
                    messages=[{"role": "system", "content": self.system_prompt}] + messages)
                return extract_json(resp.choices[0].message.content)
            except Exception as e:
                last = e
                print(f"[AIClient] OpenRouter '{model}' falhou: {e} — próximo...")
        raise last or RuntimeError("Todos os modelos gratuitos falharam.")

    def _mock_plan(self, prompt):
        p = prompt.lower()
        if "camada" in p or "list" in p:
            return {"steps": [{"action": "list_layers", "params": {}}], "continue": False}
        return {"steps": [], "continue": False,
                "explanation": "Modo mock (sem chave de API). Defina ANTHROPIC_API_KEY ou "
                               "OPENROUTER_API_KEY para usar a IA de verdade."}

    def get_provider(self):
        return self.current_provider


ClaudeClient = AIClient
