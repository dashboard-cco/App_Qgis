# -*- coding: utf-8 -*-
"""Leitura do edital pela conta Claude da máquina (Claude Code), via MCP.

O app chama o Claude Code em modo não interativo (`claude -p`), ligado só ao servidor MCP
do QGIS e só às ferramentas planos_*. O Claude lê os documentos por essas ferramentas e
grava o perfil com planos_salvar_secao. Usa a assinatura claude.ai já logada no Claude Code
(não precisa de chave de API nem de créditos da API).

Sem QGIS: aqui só montamos o comando e interpretamos a saída; quem roda é a janela (QProcess).
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys

from .extracao import SISTEMA

NOME_MCP = "qgis-planos"
MODELO = "opus"

PEDIDO = """Monte o perfil do contrato aberto no app "Planos do Contrato" do QGIS, usando só as \
ferramentas MCP planos_*.

1. planos_situacao: veja os documentos e o tamanho de cada um.
2. planos_iniciar_perfil: comece um perfil vazio.
3. planos_esquema: veja o formato de cada seção.
4. Leia os documentos. Comece por planos_indice de cada um. Leia por completo (planos_ler_paginas, \
até 30 páginas por vez) os anexos e as especificações técnicas que tratam do plano. No edital e no \
termo de referência, use planos_buscar (ex.: "plano de servi", "plano de trabalho", "especifica", \
"camada|feicao|atributo", "geodatabase|shapefile|gdb|kml", "sirgas|sistema de refer", "prazo", \
"lote", "frota|veiculo", "frequencia|turno", "equipe padr|guarni|motorista|coletor", \
"quantidade de m.o de obra|tabela de quantidades") e leia as páginas relevantes.
5. Grave cada seção com planos_salvar_secao assim que tiver os dados: contrato, documentos, lotes, \
servicos, camadas, entregaveis, insumos, regras, recursos (frota e mão de obra por serviço, lote e \
turno), equipes (equipe padrão de cada veículo), pendencias. Se voltar com erros, corrija e grave \
de novo. Camadas com muitos campos podem ser gravadas em partes com acrescentar=true.
6. No fim, responda em até 3 frases o que montou e as principais pendências."""


# ------------------------------------------------------------------ achar o Claude Code
def _versao(caminho):
    m = re.search(r"claude-code-(\d+)\.(\d+)\.(\d+)", caminho)
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def achar_claude():
    """Caminho do executável do Claude Code, ou "" se não houver."""
    achado = shutil.which("claude")
    if achado:
        return achado
    casa = os.path.expanduser("~")
    candidatos = [os.path.join(casa, ".local", "bin", "claude.exe"),
                  os.path.join(casa, ".local", "bin", "claude"),
                  os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.cmd")]
    for c in candidatos:
        if os.path.isfile(c):
            return c
    # extensão do VS Code / Cursor traz o executável junto
    exts = []
    for base in (".vscode", ".vscode-insiders", ".cursor", ".windsurf"):
        exts += glob.glob(os.path.join(casa, base, "extensions", "anthropic.claude-code-*",
                                       "resources", "native-binary", "claude*"))
    exts = [e for e in exts if os.path.isfile(e)]
    if exts:
        return max(exts, key=_versao)
    return ""


def ambiente(base=None):
    """Ambiente para o Claude Code usar a conta claude.ai (sem a chave de API, que tem
    prioridade e pode estar sem crédito)."""
    env = dict(base if base is not None else os.environ)
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(k, None)
    return env


def status_login(exe, timeout=30):
    """{"ok": bool, "metodo": "claude.ai"|..., "mensagem": str}"""
    if not exe:
        return {"ok": False, "metodo": "", "mensagem": "Claude Code não encontrado nesta máquina."}
    try:
        flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
        r = subprocess.run([exe, "auth", "status", "--json"], capture_output=True, text=True,
                           timeout=timeout, env=ambiente(), creationflags=flags,
                           encoding="utf-8", errors="replace")
        d = json.loads(r.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return {"ok": False, "metodo": "", "mensagem": f"Não consegui consultar o Claude Code: {e}"}
    if d.get("loggedIn"):
        metodo = d.get("authMethod", "")
        conta = d.get("email") or d.get("account") or ""
        return {"ok": True, "metodo": metodo,
                "mensagem": f"Claude Code logado ({metodo}{', ' + conta if conta else ''})."}
    return {"ok": False, "metodo": "", "mensagem": "Claude Code instalado, mas sem login."}


# ------------------------------------------------------------------ comando
def config_mcp(python, ponte, host, porta, token):
    return {"mcpServers": {NOME_MCP: {
        "type": "stdio", "command": python, "args": [ponte],
        "env": {"QGIS_IA_HOST": str(host), "QGIS_IA_PORT": str(porta),
                "QGIS_IA_TOKEN": str(token), "QGIS_IA_FERRAMENTAS": "planos_"}}}}


def argumentos(arq_mcp, pedido=PEDIDO, sistema=SISTEMA, modelo=MODELO):
    return ["-p", pedido,
            "--model", modelo,
            "--effort", "high",
            "--mcp-config", arq_mcp,
            "--strict-mcp-config",
            "--tools", "",
            "--allowedTools", f"mcp__{NOME_MCP}",
            "--append-system-prompt", sistema,
            "--output-format", "stream-json", "--verbose"]


# ------------------------------------------------------------------ saída
_ROTULOS = {
    "planos_situacao": lambda a: "Vendo os documentos do contrato",
    "planos_indice": lambda a: f"Lendo o índice de {a.get('documento', '')[:40]}",
    "planos_ler_paginas": lambda a: f"Lendo {a.get('documento', '')[:40]}, p. {a.get('de')}-{a.get('ate')}",
    "planos_buscar": lambda a: f"Procurando \"{a.get('termos', '')[:50]}\"",
    "planos_esquema": lambda a: "Vendo o formato do perfil",
    "planos_ler_perfil": lambda a: "Conferindo o perfil",
    "planos_iniciar_perfil": lambda a: "Começando o perfil",
    "planos_salvar_secao": lambda a: f"Gravando {a.get('secao', '')}",
    "planos_checklist": lambda a: "Montando o checklist",
}


def interpretar(linha):
    """Uma linha do stream-json do Claude Code -> evento simples:
       {"tipo": "passo", "texto"} | {"tipo": "fim", "ok", "texto", "custo"} | None"""
    try:
        ev = json.loads(linha)
    except ValueError:
        return None
    t = ev.get("type")
    if t == "assistant":
        for b in (ev.get("message") or {}).get("content") or []:
            if b.get("type") == "tool_use":
                nome = b.get("name", "").split("__")[-1]
                rot = _ROTULOS.get(nome)
                return {"tipo": "passo", "texto": rot(b.get("input") or {}) if rot else nome}
    elif t == "result":
        texto = ev.get("result") or ""
        ok = not ev.get("is_error") and ev.get("subtype", "success") == "success"
        if not ok and not texto:
            texto = ev.get("subtype", "erro")
        return {"tipo": "fim", "ok": ok, "texto": texto, "custo": ev.get("total_cost_usd"),
                "turnos": ev.get("num_turns")}
    elif t == "system" and ev.get("subtype") == "init":
        servs = ev.get("mcp_servers") or []
        falhos = [s.get("name") for s in servs if s.get("status") not in ("connected", None)]
        if falhos:
            return {"tipo": "fim", "ok": False,
                    "texto": "O Claude não conseguiu ligar ao QGIS (MCP). Verifique se o "
                             "servidor do QGIS_IA está ativo."}
        return {"tipo": "passo", "texto": "Claude conectado ao QGIS"}
    return None
