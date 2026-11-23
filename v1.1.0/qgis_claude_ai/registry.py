# -*- coding: utf-8 -*-
"""
Registro central de ações. Cada função decorada com @register vira
automaticamente (1) uma ação permitida no executor e (2) uma linha do catálogo
enviado à IA. Assim o prompt nunca fica dessincronizado da lista branca.

kind:
  info        - só lê dados; o resultado volta para a IA continuar o raciocínio
  create      - cria camadas/arquivos novos (seguro)
  view        - muda só a visualização (zoom, estilo, seleção, visibilidade)
  modify      - altera dados existentes  -> pede confirmação ao usuário
  destructive - remove dados             -> pede confirmação ao usuário
"""
import inspect

ACTIONS = {}
META = {}

CATEGORY_ORDER = []


def register(category, kind="create", name=None):
    def deco(fn):
        n = name or fn.__name__
        ACTIONS[n] = fn
        META[n] = {"category": category, "kind": kind}
        if category not in CATEGORY_ORDER:
            CATEGORY_ORDER.append(category)
        return fn
    return deco


def is_risky(action_name):
    return META.get(action_name, {}).get("kind") in ("modify", "destructive")


def is_info(action_name):
    return META.get(action_name, {}).get("kind") == "info"


def signature_of(name):
    fn = ACTIONS[name]
    parts = []
    for p in inspect.signature(fn).parameters.values():
        if p.default is inspect.Parameter.empty:
            parts.append(p.name)
        else:
            parts.append(f"{p.name}={p.default!r}")
    return f"{name}({', '.join(parts)})"


def build_catalog():
    """Texto com todas as ações agrupadas por categoria."""
    lines = []
    for cat in CATEGORY_ORDER:
        lines.append(f"\n## {cat}")
        for name in ACTIONS:
            if META[name]["category"] != cat:
                continue
            doc = (inspect.getdoc(ACTIONS[name]) or "").strip().splitlines()
            doc = doc[0] if doc else ""
            tag = {"info": " [consulta]", "modify": " [altera dados]",
                   "destructive": " [apaga]"}.get(META[name]["kind"], "")
            lines.append(f"- {signature_of(name)}{tag} — {doc}")
    return "\n".join(lines)
