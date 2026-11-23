# -*- coding: utf-8 -*-
"""Toda ferramenta descrita em tool_specs existe no servidor e no chat (as do SLU).

Rodar com o Python do QGIS:
    "C:\\Program Files\\QGIS 3.44.15\\bin\\python-qgis-ltr.bat" tests\\test_registro.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import qgis  # noqa: E402  (o plugin 'processing' fica em <qgis>/python/plugins)
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(qgis.__file__)), "plugins"))

from qgis_ia import tool_specs, protocol  # noqa: E402
from qgis_ia.mcp_socket import build_funcs  # noqa: E402
from qgis_ia.executor import ACTIONS  # noqa: E402

funcs = build_funcs()
faltando = sorted(set(tool_specs.TOOLS) - set(funcs))
sem_spec = sorted(set(funcs) - set(tool_specs.TOOLS))
slu_fora_chat = sorted(n for n in tool_specs.TOOLS if n.startswith("slu_") and n not in ACTIONS)
mut_desconhecida = sorted(protocol.MUTATING - set(funcs))
print("ferramentas:", len(funcs))
ok = not (faltando or sem_spec or slu_fora_chat or mut_desconhecida)
for rot, lst in (("spec sem função", faltando), ("função sem spec", sem_spec),
                 ("slu fora do chat", slu_fora_chat), ("MUTATING desconhecida", mut_desconhecida)):
    if lst:
        print(rot, lst)
print("OK" if ok else "FALHOU")
sys.exit(0 if ok else 1)
