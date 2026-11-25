# -*- coding: utf-8 -*-
"""Conta da IA.

Preferido: a conta Claude (claude.ai) já logada no Claude Code da máquina; o app chama o
Claude Code, que lê o edital pelas ferramentas MCP planos_* (sem chave de API).

Alternativa: chave de API da Anthropic. A chave vai para a variável de ambiente do usuário do Windows (ANTHROPIC_API_KEY), a mesma
que o chat do plugin já usa. Assim, ao instalar em outra máquina, basta configurar uma vez
na janela do app. Fora do Windows, fica nas configurações do QGIS.
"""
import os
import sys

VAR = "ANTHROPIC_API_KEY"
CHAVE_QGIS = "qgis_ia/anthropic_api_key"
URL_CONSOLE = "https://console.anthropic.com/settings/keys"


def _ler_registro():
    if sys.platform != "win32":
        return ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return winreg.QueryValueEx(k, VAR)[0] or ""
    except OSError:
        return ""


def _ler_qgis():
    try:
        from qgis.core import QgsSettings
        return QgsSettings().value(CHAVE_QGIS, "") or ""
    except Exception:
        return ""


def chave():
    """Chave configurada (variável do processo, do usuário do Windows ou do QGIS)."""
    return os.environ.get(VAR, "") or _ler_registro() or _ler_qgis()


def chave_configurada():
    return bool(chave().strip())


_CLAUDE = {}


def claude_code(atualizar=False):
    """{"exe", "ok", "metodo", "mensagem"} da conta Claude (Claude Code) desta máquina."""
    if atualizar or not _CLAUDE:
        from . import leitor_claude
        exe = leitor_claude.achar_claude()
        _CLAUDE.clear()
        _CLAUDE.update(leitor_claude.status_login(exe), exe=exe)
    return dict(_CLAUDE)


def motor(atualizar=False):
    """Como o app fala com a IA: "claude" (conta Claude via MCP, preferido), "api" (chave de
    API) ou "" (nenhum)."""
    if claude_code(atualizar)["ok"]:
        return "claude"
    if chave_configurada():
        return "api"
    return ""


def configurada(atualizar=False):
    return bool(motor(atualizar))


def mascarar(k):
    k = k or ""
    return k[:10] + "…" + k[-4:] if len(k) > 18 else ("•" * len(k))


def salvar(k):
    """Grava a chave para este e os próximos usos. Devolve onde gravou."""
    k = k.strip()
    os.environ[VAR] = k
    if sys.platform == "win32":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as h:
            winreg.SetValueEx(h, VAR, 0, winreg.REG_SZ, k)
        _avisar_windows()
        return "variáveis de ambiente do usuário do Windows"
    from qgis.core import QgsSettings
    QgsSettings().setValue(CHAVE_QGIS, k)
    return "configurações do QGIS"


def _avisar_windows():
    """Avisa os outros programas que as variáveis mudaram (sem isso só valem após reiniciar)."""
    try:
        import ctypes
        HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x1A, 0x2
        ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0,
                                                 "Environment", SMTO_ABORTIFHUNG, 2000, None)
    except Exception:
        pass


def testar(k):
    """(ok, mensagem). Confere a chave, o acesso ao modelo e se há crédito (uma chamada
    mínima, custo desprezível)."""
    try:
        import anthropic
    except ImportError:
        return False, "Biblioteca 'anthropic' não encontrada no Python do QGIS."
    from .extracao import MODELO, mensagem_erro
    try:
        cli = anthropic.Anthropic(api_key=k.strip(), max_retries=1, timeout=60)
        m = cli.models.retrieve(MODELO)
        cli.messages.create(model=MODELO, max_tokens=16, output_config={"effort": "low"},
                            messages=[{"role": "user", "content": "ok"}])
        return True, f"Conta ok — modelo {m.display_name} disponível e com crédito."
    except anthropic.AuthenticationError:
        return False, "Chave inválida."
    except anthropic.PermissionDeniedError:
        return False, "A chave não tem permissão para usar a API."
    except anthropic.NotFoundError:
        return False, f"A conta não tem acesso ao modelo {MODELO}."
    except anthropic.APIConnectionError:
        return False, "Sem conexão com a internet ou com a API."
    except anthropic.APIStatusError as e:
        return False, mensagem_erro(e)
