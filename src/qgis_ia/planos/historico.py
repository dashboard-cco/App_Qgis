# -*- coding: utf-8 -*-
"""Histórico de operação: o que cada circuito pesa e quanto tempo leva, a partir das
planilhas de RD (relatório diário de cada veículo) que a operação já tem.

Formato esperado (ex.: TabelaPadrão.xlsx, abas P1, P2…), uma linha por RD:
    Tempo Total RD, Tempo de Refeição, Tempo Produtivo, Tempo Improdutivo,
    Peso 1 / Setor 1 … Peso N / Setor N   (setor = código do circuito; uma dupla por viagem)
ou, mais simples, uma coluna Circuito/Setor e uma de Peso.

ler(caminho) -> {"arquivo", "periodo", "rds", "cap_viagem", "circuitos": {código: {...}}}
por circuito (mediana dos dias): n, trab (h trabalhadas = total - refeição), prod, improd,
peso (t), viagens, peso_viagem (t por viagem, percentil 90), extra_pct (% dos dias acima
de 7h20). cap_viagem = carga por viagem de todas as abas (capacidade_viagem() recalcula só
para os circuitos do plano).

Sem QGIS (openpyxl): pode ser testado sozinho.
"""
import datetime
import json
import os
import re
import statistics

from .checklist import norm

JORNADA_PADRAO = 7 + 20 / 60
VERSAO_CACHE = 2


def horas(v):
    """Duração em horas: time, timedelta, fração de dia do Excel ou 'H:MM[:SS]'."""
    if v is None or v == "":
        return 0.0
    if isinstance(v, datetime.datetime):
        return v.hour + v.minute / 60 + v.second / 3600
    if isinstance(v, datetime.time):
        return v.hour + v.minute / 60 + v.second / 3600
    if isinstance(v, datetime.timedelta):
        return v.total_seconds() / 3600
    if isinstance(v, (int, float)):
        return float(v) * 24 if 0 <= v < 2 else float(v)
    m = re.match(r"^\s*(\d*)\s*:\s*(\d{1,2})(?:\s*:\s*(\d{1,2}))?", str(v))
    if not m:
        return 0.0
    return int(m.group(1) or 0) + int(m.group(2)) / 60 + int(m.group(3) or 0) / 3600


def hhmm(h):
    """7.333 -> '7h20'."""
    if h is None:
        return "—"
    neg = h < 0
    m = int(round(abs(h) * 60))
    return f"{'-' if neg else ''}{m // 60}h{m % 60:02d}"


def _codigo(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return s[:-2] if re.fullmatch(r"\d+\.0", s) else s


def _num(v):
    if v in (None, ""):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(".", "").replace(",", ".")) if "," in str(v) \
            else float(v)
    except ValueError:
        return 0.0


def _colunas(cab):
    """Acha as colunas pelo nome (sem acento/maiúsculas). None se a aba não serve."""
    n = [norm(str(c or "")).replace("_", " ") for c in cab]

    def achar(*pads):
        for pad in pads:
            for i, c in enumerate(n):
                if re.fullmatch(pad, c):
                    return i
        return None

    col = {"total": achar(r"tempo total( rd)?", r"tempo total.*", r"duracao( total)?"),
           "refeicao": achar(r"tempo (de )?refeicao", r"refeicao"),
           "prod": achar(r"tempo produtivo"),
           "improd": achar(r"tempo improdutivo"),
           "inicio": achar(r"inicio( da)? operacao", r"inicio", r"data")}
    pares = []
    for i, c in enumerate(n):
        m = re.fullmatch(r"setor\s*(\d+)", c)
        if m:
            j = achar(rf"peso\s*{m.group(1)}")
            if j is not None:
                pares.append((i, j))
    if not pares:
        i = achar(r"circuito", r"codigo( do)? circuito", r"setor")
        j = achar(r"peso total", r"peso( \(?t\)?)?", r"peso.*")
        if i is not None and j is not None:
            pares = [(i, j)]
    if col["total"] is None or not pares:
        return None
    col["pares"] = pares
    return col


def _ler_planilha(caminho, progresso=None):
    from openpyxl import load_workbook
    wb = load_workbook(caminho, read_only=True, data_only=True)
    por, pesos_viagem, datas, n_rd = {}, [], [], 0
    try:
        for ws in wb.worksheets:
            it = ws.iter_rows(values_only=True)
            try:
                cab = next(it)
            except StopIteration:
                continue
            col = _colunas(cab)
            if col is None:
                continue
            if progresso:
                progresso(f"Lendo o histórico: aba {ws.title}…")
            for r in it:
                if not r or len(r) <= col["total"]:
                    continue
                viagens = []
                for i, j in col["pares"]:
                    cod = _codigo(r[i] if i < len(r) else None)
                    pz = _num(r[j] if j < len(r) else None)
                    if cod and pz > 0:
                        viagens.append((cod, pz))
                total = horas(r[col["total"]])
                if not viagens or total < 0.5:
                    continue
                # peso em kg (valores grandes) ou toneladas
                ton = [pz / 1000 if pz > 100 else pz for _, pz in viagens]
                pesos_viagem += [t for t in ton if 0 < t < 40]
                ref = horas(r[col["refeicao"]]) if col["refeicao"] is not None else 0.0
                trab = max(0.0, total - ref)
                prod = horas(r[col["prod"]]) if col["prod"] is not None else trab
                improd = horas(r[col["improd"]]) if col["improd"] is not None else 0.0
                # RD com mais de um circuito: divide pelo peso
                tot_p = sum(ton) or 1.0
                cods = {}
                for (cod, _), t in zip(viagens, ton):
                    d = cods.setdefault(cod, [0.0, 0])
                    d[0] += t
                    d[1] += 1
                for cod, (t, nv) in cods.items():
                    f = t / tot_p
                    por.setdefault(cod, []).append(
                        (trab * f, prod * f, improd * f, t, nv))
                ini = r[col["inicio"]] if col["inicio"] is not None else None
                if isinstance(ini, datetime.datetime):
                    datas.append(ini)
                n_rd += 1
    finally:
        wb.close()
    return por, pesos_viagem, datas, n_rd


def ler(caminho, cache=None, progresso=None, minimo=5):
    """Resumo por circuito (mediana dos dias). 'cache': arquivo .json para não reler a
    planilha enquanto ela não mudar."""
    st = os.stat(caminho)
    chave = {"arquivo": os.path.normcase(os.path.abspath(caminho)), "mtime": st.st_mtime,
             "tamanho": st.st_size, "versao": VERSAO_CACHE}
    if cache and os.path.exists(cache):
        try:
            with open(cache, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("_chave") == chave:
                return d
        except Exception:
            pass
    por, pv, datas, n_rd = _ler_planilha(caminho, progresso)
    if not por:
        raise ValueError("Não achei RDs na planilha (colunas 'Tempo Total' e 'Setor N'/'Peso N' "
                         "ou 'Circuito'/'Peso').")
    med = statistics.median
    circ = {}
    for cod, l in por.items():
        if len(l) < minimo:
            continue
        pv = sorted(x[3] / x[4] for x in l)
        circ[cod] = {"n": len(l), "trab": med(x[0] for x in l), "prod": med(x[1] for x in l),
                     "improd": med(x[2] for x in l), "peso": med(x[3] for x in l),
                     "viagens": med(x[4] for x in l),
                     "peso_viagem": pv[int(0.9 * (len(pv) - 1))],
                     "extra_pct": round(100 * sum(1 for x in l if x[0] > JORNADA_PADRAO + 0.05)
                                        / len(l), 1)}
    pv.sort()
    d = {"_chave": chave, "arquivo": os.path.normpath(caminho),
         "periodo": [min(datas).strftime("%d/%m/%Y"), max(datas).strftime("%d/%m/%Y")]
         if datas else ["", ""],
         "rds": n_rd, "cap_viagem": pv[int(0.9 * (len(pv) - 1))] if pv else 10.0,
         "circuitos": circ}
    if cache:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(cache)), exist_ok=True)
            with open(cache, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
        except OSError:
            pass
    return d


def capacidade_viagem(h, codigos):
    """Carga típica por viagem (t) dos circuitos dados (mediana do percentil 90 de cada um)."""
    pv = [h["circuitos"][c].get("peso_viagem") for c in codigos if c in h["circuitos"]]
    pv = [x for x in pv if x]
    return statistics.median(pv) if pv else h.get("cap_viagem") or 10.0


def resumo_txt(h):
    return (f"{len(h['circuitos'])} circuitos · {h['rds']} RDs de {h['periodo'][0]} a "
            f"{h['periodo'][1]} · carga típica por viagem {h['cap_viagem']:.1f} t")
