# -*- coding: utf-8 -*-
"""Testes da alocação de veículos da planilha de soltura.

    "C:\\Program Files\\QGIS 3.44.15\\bin\\python-qgis-ltr.bat" tests\\test_soltura.py
"""
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "src", "qgis_ia"))
sys.path.insert(0, os.path.join(AQUI, "..", "src", "qgis_ia", "actions"))
import soltura as S  # noqa: E402

FALHAS = []


def check(cond, msg):
    if not cond:
        FALHAS.append(msg)
        print("FALHOU:", msg)


def circ(cod, dias, ini, fim, turno, equip=0):
    return {"codigo": cod, "dias": dias, "ini": ini, "fim": fim, "turno": turno, "equip": equip}


SQS = [1, 0, 1, 0, 1, 0, 0]
TQS = [0, 1, 0, 1, 0, 1, 0]
DIA = [1, 1, 1, 1, 1, 1, 0]
D = (7 * 60, 15 * 60 + 20)
N = (19 * 60, 3 * 60 + 20)

# dias alternados no mesmo horário: 1 veículo
v = S._alocar([circ(1, SQS, *D, "Diurno"), circ(2, TQS, *D, "Diurno")], 60, True)
check(len(v) == 1, "SQS + TQS dividem o veículo")
# mesmo dia e horário: 2 veículos
v = S._alocar([circ(1, SQS, *D, "Diurno"), circ(2, SQS, *D, "Diurno")], 60, True)
check(len(v) == 2, "mesmo dia e horário não dividem")
# diurno + noturno no mesmo veículo só se permitido
c = [circ(1, DIA, *D, "Diurno"), circ(2, DIA, *N, "Noturno")]
check(len(S._alocar(c, 60, True)) == 1, "diurno + noturno no mesmo veículo")
check(len(S._alocar(c, 60, False)) == 2, "um turno por veículo")
# noturno que passa da meia-noite conflita com diurno que começa cedo demais
c = [circ(1, DIA, *N, "Noturno"), circ(2, DIA, 3 * 60 + 30, 11 * 60, "Diurno")]
check(len(S._alocar(c, 60, True)) == 2, "respeita folga após a meia-noite")
# tipos de equipamento diferentes não dividem
v = S._alocar([circ(1, SQS, *D, "Diurno", 0), circ(2, TQS, *D, "Diurno", 1)], 60, True)
check(len(v) == 2, "equipamentos diferentes")
# domingo à noite invade a segunda de manhã
dom = [0, 0, 0, 0, 0, 0, 1]
seg = [1, 0, 0, 0, 0, 0, 0]
c = [circ(1, dom, 22 * 60, 6 * 60, "Noturno"), circ(2, seg, 6 * 60 + 30, 12 * 60, "Diurno")]
check(len(S._alocar(c, 60, True)) == 2, "virada da semana")

print("OK" if not FALHAS else f"{len(FALHAS)} FALHA(S)")
sys.exit(1 if FALHAS else 0)
