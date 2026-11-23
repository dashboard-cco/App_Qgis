# -*- coding: utf-8 -*-
"""Executor: valida o plano contra a lista branca (registry) e executa."""
import inspect
import difflib
import traceback

from . import actions  # noqa: F401  (registra as ações)
from .registry import ACTIONS, META, is_risky, is_info


def describe_step(step):
    p = step.get("params", {})
    txt = ", ".join(f"{k}={v!r}" for k, v in list(p.items())[:4])
    return f"{step.get('action')}({txt})"


def validate_plan(plan):
    """Retorna lista de erros (vazia se o plano é válido)."""
    errors = []
    for i, step in enumerate(plan.get("steps", []), 1):
        name = step.get("action")
        if name not in ACTIONS:
            sug = difflib.get_close_matches(str(name), list(ACTIONS), n=3)
            errors.append(f"Passo {i}: ação '{name}' não existe. Parecidas: {sug}")
            continue
        params = step.get("params", {})
        if not isinstance(params, dict):
            errors.append(f"Passo {i}: params deve ser um objeto")
            continue
        try:
            inspect.signature(ACTIONS[name]).bind(**params)
        except TypeError as e:
            from .registry import signature_of
            errors.append(f"Passo {i}: parâmetros inválidos ({e}). Assinatura: {signature_of(name)}")
    return errors


def risky_steps(plan):
    return [s for s in plan.get("steps", []) if is_risky(s.get("action"))]


def only_info(plan):
    steps = plan.get("steps", [])
    return bool(steps) and all(is_info(s.get("action")) for s in steps)


def execute_claude_plan(plan, confirm=None):
    """Executa os passos. Para no primeiro erro. Retorna lista de resultados."""
    errors = validate_plan(plan)
    if errors:
        return [{"action": None, "success": False, "error": " | ".join(errors) + " (nada foi executado)"}]

    risky = risky_steps(plan)
    if risky and confirm is not None and not confirm([describe_step(s) for s in risky]):
        return [{"action": None, "success": False, "error": "Cancelado pelo usuário (nada foi executado)."}]

    results = []
    for step in plan.get("steps", []):
        name = step["action"]
        try:
            res = ACTIONS[name](**step.get("params", {}))
            results.append({"action": name, "success": True, "result": res})
        except Exception as e:
            try:
                from qgis.core import QgsMessageLog
                QgsMessageLog.logMessage(traceback.format_exc(), "Claude AI")
            except Exception:
                pass
            results.append({"action": name, "success": False,
                            "error": f"{type(e).__name__}: {e}"})
            break
    return results
