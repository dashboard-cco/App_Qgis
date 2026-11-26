# -*- coding: utf-8 -*-
"""Frota e equipe: adequar um plano já feito às quantidades de veículos e de pessoal do
edital novo (seções "recursos" e "equipes" do perfil).

- comparar(perfil, plano): veículos que o plano usa (pico por dia e turno, contando que um
  veículo faz dois circuitos do mesmo turno se os horários não se sobrepõem) e pessoal
  (veículos × equipe padrão) contra o que o edital dá.
- propor(perfil, plano): o que fazer para ficar como o edital pede:
    0. horário de cada circuito = horário do turno no edital (seção turnos do perfil);
    1. equipamento que o edital não tem num turno -> muda de turno se o outro turno tem sobra
       (ex.: munk noturno -> diurno), senão substituto do edital com sobra (mais parecido);
    2. tipo/turno com veículos a mais -> tira circuitos, escolhendo a cada passo a operação
       que deixa a carga mais equilibrada:
         - juntar: o circuito inteiro vai para um vizinho;
         - dividir: as linhas do circuito são repartidas entre 2 a N vizinhos (cada linha
           vai para o vizinho mais perto que ainda cabe na jornada).
       Só entre circuitos com o mesmo equipamento, turno, dias e horário (e a mesma região,
       se o plano tiver esse campo), vizinhos até 'distancia' metros;
    3. ainda com veículos a mais e sobra no outro turno -> muda circuitos de turno;
    4. com histórico de operação (historico.py): tempo de cada circuito = mediana real; quem
       recebe tem de caber na jornada do edital (7h20) e circuitos acima dela passam linhas a
       vizinhos com folga (aliviar). Mostra as horas por dia × veículos do edital × jornada;
    5. desdobrar: a sobra de um equipamento (munk) vira circuitos novos mistos que saem de uma
       base (DL), com circuitos inteiros do turno que falta e a parte acima da jornada;
    6. redimensionar ao máximo: mais vizinhos, mais longe e também do outro turno, até a
       jornada. O que não couber vira "pontos" para levar ao órgão (depois da licitação).
  Antes de tudo, 'equipar' passa os circuitos escolhidos para outro equipamento.
- aplicar(perfil, plano, proposta): grava numa CÓPIA do plano (o original não muda):
  horários e turnos, troca equipamentos, passa linhas e pontos para os circuitos que
  recebem, refaz os polígonos e apaga o circuito que saiu (e os pontos de início/fim dele).

Sem roteirização: a ordem de passagem nas linhas recebidas deve ser revista.
Sem QGIS (osgeo + shapely): pode ser testado sozinho.
"""
import datetime
import math
import os
import re
import shutil
from collections import Counter, defaultdict

from . import estrutura
from .checklist import norm
from .perfil import codigo_valor

TURNOS = ("Diurno", "Noturno")
DIAS = ("Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo")
_DIAS_CHAVE = (("segunda", "seg"), ("terca", "ter"), ("quarta", "qua"), ("quinta", "qui"),
               ("sexta", "sex"), ("sabado", "sab"), ("domingo", "dom"))
_SEMANA = 7 * 1440


# ================================================================== mapa de campos
def _tokens(f):
    return {t for t in re.split(r"[^a-z0-9]+", norm(f["nome"]) + " " + norm(f.get("alias") or ""))
            if t}


def _campo(campos, *padroes, evitar=()):
    """Primeiro campo cujo nome/apelido casa com um dos padrões (regex sobre o nome normalizado)."""
    for pad in padroes:
        for f in campos:
            alvo = (norm(f["nome"]) + " " + norm(f.get("alias") or "")).replace("_", " ")
            if re.search(pad, alvo) and not any(re.search(e, alvo) for e in evitar):
                return f["nome"]
    return ""


def mapear(estr):
    """Descobre no plano a camada de circuitos e os campos de operação.

    {"camada", "codigo", "equipamento", "turno", "inicio", "fim", "dias": [7], "regiao",
     "linhas": [camadas], "pontos": [camadas], "inicio_fim": {camada: campo}}"""
    melhor, nota = None, 0
    for c in estr["camadas"]:
        dias = []
        for chaves in _DIAS_CHAVE:
            achado = ""
            for f in c["campos"]:
                tk = _tokens(f)
                if chaves[0] in tk or chaves[1] in tk or norm(f["nome"]).startswith(chaves[0]):
                    achado = f["nome"]
                    break
            dias.append(achado)
        equip = _campo(c["campos"], r"equipamento", r"veiculo", r"frota")
        n = sum(1 for d in dias if d) + (3 if equip else 0) + (1 if c["geometria"] == "poligono" else 0)
        if sum(1 for d in dias if d) >= 5 and equip and n > nota:
            melhor, nota = (c, dias, equip), n
    if melhor is None:
        return None
    c, dias, equip = melhor
    cf = c["campos"]
    codigo = _campo(cf, r"^codigo circuito\b", r"^cod\w* circ", r"^circuito\b", r"^codigo\b",
                    evitar=(r"\bra\b", r"regiao", r"servico", r"equip"))
    m = {"camada": c["nome"], "geometria": c["geometria"], "codigo": codigo, "equipamento": equip,
         "turno": _campo(cf, r"^turno\b", r"turno"),
         "inicio": _campo(cf, r"hor\w* inicio", r"hora ini", r"\binicio\b", r"saida"),
         "fim": _campo(cf, r"hor\w* termino", r"hor\w* fim", r"termino", r"\bfim\b",
                       r"chegada"),
         "dias": dias,
         "regiao": _campo(cf, r"^codigo ra\b", r"\bra\b", r"regiao", r"bairro", r"setor",
                          evitar=(r"\blay\b",)),
         "servico": _campo(cf, r"tipo servico", r"^servico\b", evitar=(r"equip",)),
         # de onde o veículo sai (DL / garagem / núcleo); sem campo próprio, o local de pesagem
         "base": _campo(cf, r"garagem", r"\bbase\b", r"\bdl\b", r"diretoria", r"local pesagem",
                        r"local destinacao"),
         "linhas": [], "pontos": [], "inicio_fim": {}, "tabelas": []}
    if not codigo:
        return None
    for o in estr["camadas"]:
        if o["nome"] == c["nome"] or not any(norm(f["nome"]) == norm(codigo) for f in o["campos"]):
            continue
        real = next(f["nome"] for f in o["campos"] if norm(f["nome"]) == norm(codigo))
        item = (o["nome"], real)
        if o["geometria"] == "linha":
            m["linhas"].append(item)
        elif o["geometria"] == "ponto":
            m["pontos"].append(item)
            campo_if = _campo_inicio_fim(o, estr.get("dominios") or {})
            if campo_if:
                m["inicio_fim"][o["nome"]] = campo_if
        else:
            m["tabelas"].append(item)
    return m


def _campo_inicio_fim(camada, dominios):
    nome = norm(camada["nome"])
    for f in camada["campos"]:
        vals = " ".join(str(v) for v in (dominios.get(f.get("dominio") or "") or {}).values())
        if "inicio" in norm(vals) and "fim" in norm(vals):
            return f["nome"]
    if "inicio" in nome and "fim" in nome:
        return _campo(camada["campos"], r"^tipo\b", r"inicio_fim", r"tipo")
    return ""


# ================================================================== leitura
def _minutos(v):
    if v is None or v == "":
        return None
    if isinstance(v, (datetime.datetime, datetime.time)):
        return v.hour * 60 + v.minute
    if isinstance(v, (list, tuple)) and len(v) >= 5:   # OGR DateTime: [a, m, d, h, min, s, tz]
        return int(v[3]) * 60 + int(v[4])
    if isinstance(v, (int, float)):
        return int(v * 1440) if 0 <= v < 1 else int(v // 100 * 60 + v % 100)
    m = re.search(r"(\d{1,2})\s*[:hH]\s*(\d{2})?", str(v))
    if m:
        return int(m.group(1)) * 60 + int(m.group(2) or 0)
    return None


def _turno(v, ini):
    t = norm(v or "")
    if "not" in t:
        return "Noturno"
    if t and ("diur" in t or "vesp" in t or "matut" in t or "dia" == t):
        return "Diurno"
    if ini is None:
        return "Diurno"
    return "Noturno" if ini >= 18 * 60 or ini < 4 * 60 else "Diurno"


def _sim(v):
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return v != 0
    return norm(str(v)) not in ("", "0", "n", "nao", "false", "f", "-")


def _cod(v):
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return codigo_valor(v) if v is not None else ""


def _shp(g):
    if g is None or g.IsEmpty():
        return None
    from shapely import wkb
    g = g.Clone()
    g.FlattenTo2D()
    try:
        s = wkb.loads(bytes(g.ExportToIsoWkb()))
    except Exception:
        return None
    if not s.is_valid:
        s = s.buffer(0)
    return s


@estrutura.com_excecoes
def ler_circuitos(caminho, mapa=None):
    """(circuitos, mapa, avisos). Cada circuito: codigo, fid, equip, turno, dias[7], ini, fim,
    regiao, geom (shapely), carga (km de linhas; sem linhas, km² do polígono), linhas, pontos."""
    estr = estrutura.ler(caminho)
    mapa = mapa or mapear(estr)
    if not mapa:
        raise ValueError("Não achei no plano a camada de circuitos (com dias da semana e "
                         "tipo de equipamento).")
    mapa.setdefault("servico", "")
    mapa.setdefault("base", "")
    if mapa["servico"] and not mapa.get("rotulos_servico"):
        cam = next((c for c in estr["camadas"] if c["nome"] == mapa["camada"]), None)
        fd = next((f for f in (cam or {}).get("campos", []) if f["nome"] == mapa["servico"]), {})
        dom = (estr.get("dominios") or {}).get(fd.get("dominio") or "") or {}
        mapa["rotulos_servico"] = {_cod(k): str(v) for k, v in dom.items()}
    ds = estrutura.abrir(caminho)
    lyr = ds.GetLayerByName(mapa["camada"])
    circ, avisos = {}, []
    for f in lyr:
        cod = f.GetField(mapa["codigo"])
        if cod in (None, ""):
            avisos.append(f"Feição {f.GetFID()} de {mapa['camada']} sem código de circuito.")
            continue
        cod = str(cod)
        ini = _minutos(f.GetField(mapa["inicio"])) if mapa["inicio"] else None
        fim = _minutos(f.GetField(mapa["fim"])) if mapa["fim"] else None
        dias = [bool(d) and _sim(f.GetField(d)) for d in mapa["dias"]]
        bruto = f.GetField(mapa["turno"]) if mapa["turno"] else None
        c = {"codigo": cod, "fid": f.GetFID(), "equip": _cod(f.GetField(mapa["equipamento"])),
             "turno": _turno(bruto, ini), "turno_bruto": bruto,
             "dias": dias, "ini": ini, "fim": fim,
             "regiao": f.GetField(mapa["regiao"]) if mapa["regiao"] else None,
             "servico": _cod(f.GetField(mapa["servico"])) if mapa["servico"] else "",
             "base": f.GetField(mapa["base"]) if mapa["base"] else None,
             "geom": _shp(f.GetGeometryRef()), "carga": 0.0, "linhas": [], "pontos": []}
        if cod in circ:
            avisos.append(f"Circuito {cod} repetido em {mapa['camada']} (usei o primeiro).")
            continue
        if ini is None or fim is None:
            avisos.append(f"Circuito {cod} sem horário de início/término (considerei o turno todo).")
        if not any(dias):
            avisos.append(f"Circuito {cod} sem dia da semana marcado (fica fora da contagem).")
        circ[cod] = c
    for camada, campo in mapa["linhas"]:
        for f in ds.GetLayerByName(camada):
            c = circ.get(str(f.GetField(campo)))
            g = f.GetGeometryRef()
            if c is None or g is None:
                continue
            s = _shp(g)
            km = g.Length() / 1000.0
            c["linhas"].append({"camada": camada, "fid": f.GetFID(), "geom": s, "km": km})
            c["carga"] += km
    for camada, campo in mapa["pontos"]:
        for f in ds.GetLayerByName(camada):
            c = circ.get(str(f.GetField(campo)))
            if c is not None:
                c["pontos"].append({"camada": camada, "fid": f.GetFID(),
                                    "geom": _shp(f.GetGeometryRef()),
                                    "inicio_fim": camada in mapa["inicio_fim"]})
    for c in circ.values():
        if not c["linhas"] and c["geom"] is not None:
            c["carga"] = c["geom"].area / 1e6
    return list(circ.values()), mapa, avisos


# ================================================================== edital
def lote_do_arquivo(p, caminho):
    """Lote do perfil pelo número no fim do nome do arquivo (CC01.gdb -> lote '1')."""
    base = os.path.splitext(os.path.basename(caminho.rstrip("/\\")))[0]
    m = re.search(r"(\d+)\D*$", base)
    if not m:
        return ""
    n = int(m.group(1))
    for lt in p.get("lotes", []):
        m2 = re.search(r"\d+", lt.get("codigo") or "")
        if m2 and int(m2.group()) == n:
            return lt["codigo"]
    return str(n)


def _mesmo_lote(a, b):
    if not a or not b:
        return True
    na, nb = re.search(r"\d+", a), re.search(r"\d+", b)
    if na and nb:
        return int(na.group()) == int(nb.group())
    return norm(a) == norm(b)


def _num(s):
    return [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", s or "")]


def _semelhanca(a, b):
    """Quão parecidos são dois nomes de equipamento (palavras + capacidade em m³)."""
    pa = {w for w in re.split(r"[^a-z]+", norm(a)) if len(w) > 2} - {"com", "caminhao", "veiculo"}
    pb = {w for w in re.split(r"[^a-z]+", norm(b)) if len(w) > 2} - {"com", "caminhao", "veiculo"}
    s = len(pa & pb) / max(1, len(pa | pb))
    na, nb = _num(a), _num(b)
    if na and nb:
        s += 0.5 * min(na[0], nb[0]) / max(na[0], nb[0])
    if ("munk" in pa or "munck" in pa) != ("munk" in pb or "munck" in pb):
        s -= 0.3
    return s


def nomes_equipamento(p, mapa):
    """{código: descrição} do campo de equipamento, pelos valores permitidos do perfil."""
    out = {}
    if not mapa:
        return out
    for cam in p.get("camadas", []):
        if norm(cam["nome"]) != norm(mapa["camada"]):
            continue
        for f in cam["campos"]:
            if norm(f["nome"]) == norm(mapa["equipamento"]):
                for v in f.get("valores_permitidos") or []:
                    cod = codigo_valor(v)
                    out[cod] = str(v)[len(cod):].lstrip(" -–") or str(v)
    return out


def recursos(p, servicos, lote, nomes=None):
    """O que o edital dá para estes serviços/lote:
    {"equip": {código: {"nome", "Diurno", "Noturno", "domingo"}},
     "pessoal": {função: {"nome", "Diurno", "Noturno"}},
     "equipes": {código: {função: quantidade}}, "sem_codigo": [nomes]}"""
    nomes = nomes or {}
    eq, pes, sem = {}, {}, []
    for r in p.get("recursos") or []:
        if servicos and r["servico"] not in servicos:
            continue
        if not _mesmo_lote(r.get("lote"), lote):
            continue
        if r["categoria"] == "pessoal":
            k = norm(r["nome"])
            d = pes.setdefault(k, {"nome": r["nome"], "Diurno": 0, "Noturno": 0})
            d["Diurno"] += r["diurno"]
            d["Noturno"] += r["noturno"]
            continue
        cod = codigo_valor(r.get("codigo_no_plano") or "") if r.get("codigo_no_plano") else ""
        if not cod and nomes:
            cand = max(nomes, key=lambda k: _semelhanca(r["nome"], nomes[k]))
            if _semelhanca(r["nome"], nomes[cand]) >= 0.6:
                cod = cand
        if not cod:
            sem.append(r["nome"])
            continue
        d = eq.setdefault(cod, {"nome": nomes.get(cod) or r["nome"], "Diurno": 0, "Noturno": 0,
                                "domingo": False})
        d["Diurno"] += r["diurno"]
        d["Noturno"] += r["noturno"]
        d["domingo"] = d["domingo"] or bool(r.get("domingo"))
    equipes = {}
    for e in p.get("equipes") or []:
        if servicos and e["servico"] not in servicos:
            continue
        cod = codigo_valor(e["codigo_no_plano"]) if e.get("codigo_no_plano") else ""
        if not cod and nomes:
            cand = max(nomes, key=lambda k: _semelhanca(e["equipamento"], nomes[k]))
            if _semelhanca(e["equipamento"], nomes[cand]) >= 0.6:
                cod = cand
        if cod and cod not in equipes:
            equipes[cod] = {norm(x["funcao"]): x["quantidade"] for x in e["funcoes"]}
    return {"equip": eq, "pessoal": pes, "equipes": equipes, "sem_codigo": sem}


# ================================================================== turnos e jornada
def turnos_edital(p, servicos):
    """Horários dos turnos do perfil (seção turnos): [{"turno", "ini", "fim" (minutos),
    "jornada" (h), "equip" ('' = todos), "obs"}]."""
    out = []
    for t in p.get("turnos") or []:
        if servicos and t.get("servico") and t["servico"] not in servicos:
            continue
        ini, fim, jor = _minutos(t.get("inicio")), _minutos(t.get("fim")), _minutos(t.get("jornada"))
        out.append({"turno": "Noturno" if "not" in norm(t.get("nome") or "") else "Diurno",
                    "ini": ini, "fim": fim, "jornada": jor / 60 if jor else None,
                    "equip": codigo_valor(t["equipamento"]) if t.get("equipamento") else "",
                    "obs": t.get("observacao") or ""})
    return out


def _opcoes_horario(tur, equip, turno):
    """Horários do edital para o equipamento/turno; os que valem só para o equipamento vêm
    primeiro (ex.: 08h00-16h20 só para o papa-lixo)."""
    esp = [t for t in tur if t["turno"] == turno and t["equip"] == equip and t["ini"] is not None]
    ger = [t for t in tur if t["turno"] == turno and not t["equip"] and t["ini"] is not None]
    return esp + ger


def horario_edital(tur, equip, turno, atual=None):
    """(ini, fim) que o edital pede; mantém o atual se ele já é uma das opções do edital."""
    ops = _opcoes_horario(tur, equip, turno)
    if not ops:
        return None
    if atual and any((o["ini"], o["fim"] % 1440) == (atual[0], (atual[1] or 0) % 1440)
                     for o in ops):
        return atual
    return ops[0]["ini"], ops[0]["fim"]


def jornada_edital(tur, equip, turno, padrao):
    for t in _opcoes_horario(tur, equip, turno) + [t for t in tur if t["turno"] == turno]:
        if t["jornada"]:
            return t["jornada"]
    return padrao


def _hm(minutos):
    if minutos is None:
        return "?"
    m = int(minutos) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


# ------------------------------------------------------------------ tempo de cada circuito
def _tempos(circ, hist, cap=10.0):
    """Põe em cada circuito o tempo de trabalho do histórico: t (h), prod, peso (t), viag, tv
    (h por viagem = ida/volta ao destino). Sem histórico, estima pelo km (média do mesmo
    equipamento e turno). Devolve quantos foram estimados."""
    import statistics
    for c in circ:
        c.update(t=None, prod=None, peso=None, viag=None, tv=None, hist=False)
    if not hist:
        return 0
    hc = hist.get("circuitos") or {}
    grupos = defaultdict(list)
    for c in circ:
        h = hc.get(c["codigo"])
        if not h:
            continue
        viag = max(1, int(round(h["viagens"])))
        c.update(t=h["trab"], prod=h["prod"], peso=h["peso"], viag=viag,
                 tv=h["improd"] / viag, hist=True)
        if c["carga"] > 0:
            grupos[(c["equip"], c["turno"])].append(c)
    todos = [x for g in grupos.values() for x in g]
    estimados = 0
    for c in circ:
        if c["hist"] or c["carga"] <= 0:
            continue
        g = grupos.get((c["equip"], c["turno"])) or todos
        if not g:
            continue
        pk = statistics.median(x["prod"] / x["carga"] for x in g)
        wk = statistics.median(x["peso"] / x["carga"] for x in g)
        tv = statistics.median(x["tv"] for x in g)
        prod, peso = pk * c["carga"], wk * c["carga"]
        viag = max(1, _teto(peso / cap))
        c.update(t=prod + viag * tv, prod=prod, peso=peso, viag=viag, tv=tv)
        estimados += 1
    return estimados


def _teto(v):
    import math
    return int(math.ceil(v - 1e-9))


def _apos_receber(v, x, frac, cap):
    """Tempo/peso de v depois de receber a fração 'frac' (por km de linha) do circuito x."""
    prod = v["prod"] + frac * x["prod"]
    peso = v["peso"] + frac * x["peso"]
    viag = max(v["viag"], _teto(peso / cap))
    return {"prod": prod, "peso": peso, "viag": viag,
            "t": v["t"] + frac * x["prod"] + (viag - v["viag"]) * v["tv"]}


def _apos_perder(x, frac, cap):
    prod = (1 - frac) * x["prod"]
    peso = (1 - frac) * x["peso"]
    viag = max(1, min(x["viag"], _teto(peso / cap)))
    return {"prod": prod, "peso": peso, "viag": viag,
            "t": x["t"] - frac * x["prod"] - (x["viag"] - viag) * x["tv"]}


def _tem_tempo(*cs):
    return all(c.get("t") is not None for c in cs)


def horas_por_dia(circ, rec, nomes, jfn):
    """Horas de trabalho por dia × veículos do edital × jornada:
    [{"codigo","nome","turno","dia","circuitos","horas","capacidade","saldo","sem_tempo"}]"""
    grupos = defaultdict(list)
    for c in circ:
        for d, sim in enumerate(c["dias"]):
            if sim:
                grupos[(c["equip"], c["turno"], d)].append(c)
    out = []
    for (eq, t, d), cs in sorted(grupos.items(), key=lambda kv: (str(kv[0][0]), kv[0][1],
                                                                 kv[0][2])):
        lim = rec["equip"].get(eq, {}).get(t) if eq in rec["equip"] else None
        h = sum(c["t"] for c in cs if c.get("t") is not None)
        cap_h = lim * jfn(eq, t) if lim is not None else None
        out.append({"codigo": eq, "nome": nomes.get(eq, eq), "turno": t, "dia": DIAS[d],
                    "circuitos": len(cs), "horas": round(h, 1),
                    "capacidade": round(cap_h, 1) if cap_h is not None else None,
                    "saldo": round(cap_h - h, 1) if cap_h is not None else None,
                    "sem_tempo": sum(1 for c in cs if c.get("t") is None)})
    return out


# ================================================================== necessidade
def _intervalos(c, folga):
    ini = c["ini"] if c["ini"] is not None else (6 * 60 if c["turno"] == "Diurno" else 19 * 60)
    fim = c["fim"] if c["fim"] is not None else ini + 8 * 60
    if fim <= ini:
        fim += 1440
    return ini, fim + folga


def _pico(lista, folga):
    """Nº mínimo de veículos para circuitos do mesmo dia (sobreposição máxima de horários)."""
    ev = []
    for c in lista:
        a, b = _intervalos(c, folga)
        ev += [(a, 1), (b, -1)]
    n = m = 0
    for _, d in sorted(ev):
        n += d
        m = max(m, n)
    return m


def necessidade(circuitos, folga=60):
    """{"veiculos": {(equip, turno): (pico, dia)}, "por_dia": {(dia, equip, turno): n}}"""
    grupos = defaultdict(list)
    for c in circuitos:
        for d, sim in enumerate(c["dias"]):
            if sim:
                grupos[(d, c["equip"], c["turno"])].append(c)
    por_dia = {k: _pico(v, folga) for k, v in grupos.items()}
    veic = {}
    for (d, eq, t), n in por_dia.items():
        if n > veic.get((eq, t), (0, 0))[0]:
            veic[(eq, t)] = (n, d)
    return {"veiculos": veic, "por_dia": por_dia}


def _pessoal(nec, equipes):
    """{(funcao, turno): (n, dia)} = veículos do dia × equipe padrão."""
    por = defaultdict(int)
    for (d, eq, t), n in nec["por_dia"].items():
        for funcao, q in (equipes.get(eq) or {}).items():
            por[(funcao, t, d)] += n * q
    out = {}
    for (funcao, t, d), n in por.items():
        if n > out.get((funcao, t), (0, 0))[0]:
            out[(funcao, t)] = (n, d)
    return out


# ================================================================== comparar
def _contexto(p, caminho, servicos=None, lote=None, mapa=None):
    servicos = servicos if servicos is not None else estrutura.servicos_do_arquivo(p, caminho)
    lote = lote if lote is not None else lote_do_arquivo(p, caminho)
    circ, mapa, avisos = ler_circuitos(caminho, mapa)
    nomes = nomes_equipamento(p, mapa)
    rec = recursos(p, servicos, lote, nomes)
    for k, v in rec["equip"].items():
        nomes.setdefault(k, v["nome"])
    return servicos, lote, circ, mapa, avisos, nomes, rec


def _tabela(circ, rec, nomes, folga):
    nec = necessidade(circ, folga)
    linhas = []
    codigos = sorted({eq for eq, _ in nec["veiculos"]} | set(rec["equip"]), key=str)
    for eq in codigos:
        for t in TURNOS:
            n, d = nec["veiculos"].get((eq, t), (0, None))
            lim = rec["equip"].get(eq, {}).get(t, 0) if eq in rec["equip"] else None
            if n == 0 and not lim:
                continue
            linhas.append({"categoria": "equipamento", "codigo": eq,
                           "nome": nomes.get(eq, eq), "turno": t, "plano": n,
                           "edital": lim, "dia_pico": DIAS[d] if d is not None else "",
                           "situacao": _situacao(n, lim)})
    pes = _pessoal(nec, rec["equipes"])
    funcoes = sorted({f for f, _ in pes} | set(rec["pessoal"]))
    for f in funcoes:
        for t in TURNOS:
            n, d = pes.get((f, t), (0, None))
            lim = rec["pessoal"].get(f, {}).get(t) if f in rec["pessoal"] else None
            if n == 0 and not lim:
                continue
            nome = rec["pessoal"].get(f, {}).get("nome") or f.capitalize()
            linhas.append({"categoria": "pessoal", "codigo": f, "nome": nome, "turno": t,
                           "plano": n, "edital": lim,
                           "dia_pico": DIAS[d] if d is not None else "",
                           "situacao": _situacao(n, lim)})
    return linhas, nec


def _situacao(n, lim):
    if lim is None:
        return "fora_do_edital" if n else "ok"
    if n > lim:
        return "excede"
    return "sobra" if n < lim else "ok"


@estrutura.com_excecoes
def comparar(p, caminho, servicos=None, lote=None, folga=60, mapa=None):
    """Plano × edital: veículos e pessoal por turno (no dia de pico)."""
    servicos, lote, circ, mapa, avisos, nomes, rec = _contexto(p, caminho, servicos, lote, mapa)
    linhas, _ = _tabela(circ, rec, nomes, folga)
    if not rec["equip"]:
        avisos.insert(0, "O perfil não tem a frota do edital para " +
                      f"{', '.join(servicos) or 'estes serviços'} lote {lote or '?'} "
                      "(seção recursos).")
    if rec["pessoal"] and not rec["equipes"]:
        avisos.insert(0, "Sem equipe padrão (seção equipes): não dá para contar o pessoal.")
    if rec["sem_codigo"]:
        avisos.append("Equipamentos do edital sem código no plano: " + ", ".join(rec["sem_codigo"]))
    for c in circ:
        eq = rec["equip"].get(c["equip"])
        if c["dias"][6] and eq is not None and not eq["domingo"]:
            avisos.append(f"Circuito {c['codigo']} roda no domingo, mas o edital não prevê "
                          f"{eq['nome']} aos domingos.")
    return {"plano": os.path.normpath(caminho), "servicos": servicos, "lote": lote,
            "mapa": {k: v for k, v in mapa.items()}, "circuitos": len(circ), "linhas": linhas,
            "avisos": avisos, "folga": folga,
            "cabe": not any(l["situacao"] in ("excede", "fora_do_edital") for l in linhas)}


# ================================================================== propor
# Etapas de compatibilidade, da mais rígida para a mais solta (só passa para a seguinte se
# nenhum circuito couber na anterior):
#   1. mesmos dias e mesmo horário;
#   2. o vizinho já roda em todos os dias do circuito (e talvez em mais) no mesmo turno —
#      a área retirada passa a ser atendida também nos dias a mais do vizinho.
ETAPAS = ("mesmos_dias", "dias_contidos")


def _compativeis(x, v, mesma_regiao, etapa):
    """v pode receber (parte de) x?"""
    if x["equip"] != v["equip"] or x["turno"] != v["turno"]:
        return False
    if mesma_regiao and x["regiao"] != v["regiao"]:
        return False
    if etapa == "mesmos_dias":
        return x["dias"] == v["dias"] and (x["ini"], x["fim"]) == (v["ini"], v["fim"])
    return all(dv or not dx for dx, dv in zip(x["dias"], v["dias"]))


def _dist(a, b):
    if a is None or b is None:
        return float("inf")
    return a.distance(b)


def _repartir(x, vizinhos, max_receptores, lim=None):
    """Cada linha de x vai para o vizinho mais perto; no máximo 'max_receptores' vizinhos.
    Com lim=(cap, jfn) e tempos conhecidos, só manda a linha para quem ainda cabe na jornada
    (senão o mais perto seguinte); devolve None se alguma linha não couber em ninguém."""
    if not x["linhas"]:
        return None
    if lim and _tem_tempo(x) and x["carga"] > 0:
        return _repartir_jornada(x, vizinhos, max_receptores, lim)
    escolha = {}
    for i, ln in enumerate(x["linhas"]):
        escolha[i] = min(vizinhos, key=lambda v: _dist(ln["geom"], v["geom"]))["codigo"]
    usados = Counter(escolha.values())
    if len(usados) > max_receptores:
        manter = {c for c, _ in usados.most_common(max_receptores)}
        viz = [v for v in vizinhos if v["codigo"] in manter]
        for i, ln in enumerate(x["linhas"]):
            if escolha[i] not in manter:
                escolha[i] = min(viz, key=lambda v: _dist(ln["geom"], v["geom"]))["codigo"]
    partes = defaultdict(list)
    for i, cod in escolha.items():
        partes[cod].append(i)
    return dict(partes)


def _folga(v, lim):
    cap, jfn = lim
    return jfn(v["equip"], v["turno"]) - v["t"] if v.get("t") is not None else 0.0


def _distribuir(x, linhas_idx, receptores, lim, frac_inicial=None):
    """Manda as linhas (índices) de x para os receptores, cada uma para o mais perto que
    ainda cabe na jornada. {codigo: [índices]} ou None se alguma não couber."""
    cap, jfn = lim
    frac = defaultdict(float, frac_inicial or {})
    partes = defaultdict(list)
    for i in linhas_idx:
        ln = x["linhas"][i]
        f = ln["km"] / x["carga"]
        for v in sorted(receptores, key=lambda v: _dist(ln["geom"], v["geom"])):
            novo = _apos_receber(v, x, frac[v["codigo"]] + f, cap)
            if novo["t"] <= jfn(v["equip"], v["turno"]) + 1e-6:
                frac[v["codigo"]] += f
                partes[v["codigo"]].append(i)
                break
        else:
            return None
    return dict(partes)


def _repartir_jornada(x, vizinhos, max_receptores, lim):
    viz = [v for v in vizinhos if _tem_tempo(v) and _folga(v, lim) > 0.05]
    if not viz:
        return None
    # os mais perto primeiro; entre eles, os de maior folga
    viz.sort(key=lambda v: _dist(x["geom"], v["geom"]))
    perto = sorted(viz[:max(6, max_receptores)], key=lambda v: -_folga(v, lim))
    if sum(_folga(v, lim) for v in perto[:max_receptores]) < x["prod"] * 0.95:
        return None
    escolhidos = perto[:max_receptores]
    ordem = sorted(range(len(x["linhas"])),
                   key=lambda i: min(_dist(x["linhas"][i]["geom"], v["geom"]) for v in escolhidos))
    return _distribuir(x, ordem, escolhidos, lim)


def _excessos(circ, rec, folga):
    nec = necessidade(circ, folga)
    out = {}
    for (eq, t), (n, _) in nec["veiculos"].items():
        if eq in rec["equip"] and n > rec["equip"][eq].get(t, 0):
            out[(eq, t)] = n - rec["equip"][eq].get(t, 0)
    return out


def _pico_de(circ, eq, t, folga):
    return necessidade([c for c in circ if c["equip"] == eq and c["turno"] == t],
                       folga)["veiculos"].get((eq, t), (0, 0))[0]


def _mudar_turno(c, novo, tur):
    """Passa o circuito para o outro turno, com o horário do edital (ou o mesmo tamanho)."""
    hr = horario_edital(tur, c["equip"], novo)
    if hr is None:
        dur = ((c["fim"] or 0) - (c["ini"] or 0)) % 1440 or 8 * 60
        ini = 6 * 60 if novo == "Diurno" else 16 * 60
        hr = (ini, (ini + dur) % 1440)
    c["turno"], c["ini"], c["fim"] = novo, hr[0], hr[1]


def _registro_turno(c, de, nomes, motivo):
    return {"circuito": c["codigo"], "equip": c["equip"], "nome_equip": nomes.get(c["equip"],
                                                                                 c["equip"]),
            "de": de, "para": c["turno"], "inicio": _hm(c["ini"]), "fim": _hm(c["fim"]),
            "dias": [DIAS[i] for i, s in enumerate(c["dias"]) if s],
            "tempo": round(c["t"], 2) if c.get("t") is not None else None, "motivo": motivo}


@estrutura.com_excecoes
def propor(p, caminho, servicos=None, lote=None, folga=60, mapa=None, metodo="auto",
           distancia=1500.0, max_receptores=3, mesma_regiao=True, outra_regiao=False,
           substituicoes=None, historico=None, jornada=None, horarios=True, mudar_turno=True,
           equipar=None, desdobrar="", equip_desdobrar=None, distancia_desdobrar=8000.0,
           redimensionar=False, distancia_max=5000.0, max_receptores_max=8):
    """Proposta para o plano ficar como o edital pede (nada é gravado).

    Etapas:
      0. horarios=True: horário de cada circuito = horário do turno no edital (seção turnos);
      1. mudar_turno=True: equipamento que o edital não tem num turno, mas tem com sobra no
         outro -> o circuito muda de turno (ex.: munk noturno -> diurno, 08h00-16h20);
         senão, troca pelo equipamento mais parecido com sobra (substituicoes força/recusa:
         {(codigo, turno): codigo_novo}, "" = não trocar);
      2. veículos acima do edital -> tira circuitos (juntar a um vizinho ou dividir entre
         2-N vizinhos). Com 'historico' (historico.ler), quem recebe tem de caber na jornada
         (padrão: a do edital, 7h20): tempo = do histórico + o tempo de coleta da parte
         recebida + viagens a mais ao destino;
      3. se ainda sobrar veículo e o outro turno tiver sobra, o circuito muda de turno;
      4. circuitos acima da jornada -> passa linhas a vizinhos com folga (aliviar);
      5. desdobrar="<base>" (ex.: "Sobradinho"): a sobra do equipamento 'equip_desdobrar'
         (padrão: o munk) vira circuitos NOVOS mistos que saem dessa base (DL/garagem; campo
         de base ou local de pesagem): recebem circuitos inteiros do turno que falta (ex.:
         noturno -> dia) e a parte acima da jornada dos circuitos da base, sempre até a
         jornada e só nos dias em que há veículo sobrando;
      6. redimensionar=True (ao máximo, para caber no edital): o que ainda passa do edital tira
         circuitos inteiros repartindo as linhas entre até 'max_receptores_max' vizinhos a até
         'distancia_max' m, enchendo cada um até a jornada — primeiro no mesmo turno, depois
         no outro turno (a coleta domiciliar não é presa a um turno) —, e os circuitos acima
         da jornada passam linhas do mesmo jeito.
    equipar={codigo: equipamento}: passa estes circuitos para outro equipamento antes de tudo
    (ex.: o munk da DL Sul faz o Noroeste: {"182501": "1", "182502": "1"}).
    metodo: "auto" (o que equilibra melhor), "juntar" ou "dividir".
    outra_regiao=True: em último caso, aceita vizinho de outra região (campo de região)."""
    servicos, lote, circ, mapa, avisos, nomes, rec = _contexto(p, caminho, servicos, lote, mapa)
    tur = turnos_edital(p, servicos)
    padrao = jornada or 7 + 20 / 60
    codigos_plano = {c["codigo"]: c.get("servico", "") for c in circ}

    def jfn(eq, t):
        return jornada or jornada_edital(tur, eq, t, padrao)

    cap = 10.0
    if historico:
        from .historico import capacidade_viagem
        cap = capacidade_viagem(historico, [c["codigo"] for c in circ])
    estimados = _tempos(circ, historico, cap)
    lim = (cap, jfn) if historico else None
    if historico:
        sem = [c["codigo"] for c in circ if c["t"] is None]
        if estimados:
            avisos.append(f"{estimados} circuito(s) sem histórico: tempo estimado pelo km.")
        if sem:
            avisos.append(f"Sem tempo para {len(sem)} circuito(s) (sem histórico nem linhas): "
                          + ", ".join(sem[:10]))
    antes, nec = _tabela(circ, rec, nomes, folga)
    horas_antes = horas_por_dia(circ, rec, nomes, jfn) if historico else []
    acima_antes = sum(1 for c in circ if c["t"] is not None and c["t"] > jfn(c["equip"], c["turno"]) + 1e-6)

    # escolha do usuário: circuitos que passam para outro equipamento
    equipados = []
    por_codigo = {c["codigo"]: c for c in circ}
    for cod, novo in (equipar or {}).items():
        c = por_codigo.get(str(cod).strip())
        novo = codigo_valor(novo)
        if c is None:
            avisos.append(f"Passar para {nomes.get(novo, novo)}: o circuito {cod} não existe "
                          "no plano.")
            continue
        if c["equip"] == novo:
            continue
        de = c["equip"]
        c["equip"] = novo
        equipados.append({"circuito": c["codigo"], "de": de, "nome_de": nomes.get(de, de),
                          "para": novo, "nome_para": nomes.get(novo, novo),
                          "turno": c["turno"], "base": c.get("base") or "",
                          "dias": [DIAS[i] for i, s in enumerate(c["dias"]) if s],
                          "tempo": round(c["t"], 2) if c.get("t") is not None else None})
    if equipados:
        nec = necessidade(circ, folga)

    # 0) horários do edital
    mud_horario = []
    if horarios and tur:
        grupos = defaultdict(list)
        for c in circ:
            hr = horario_edital(tur, c["equip"], c["turno"], (c["ini"], c["fim"]))
            if hr is None or (hr[0], hr[1] % 1440) == (c["ini"], (c["fim"] or 0) % 1440):
                continue
            grupos[(c["equip"], c["turno"], _hm(c["ini"]), _hm(c["fim"]), hr)].append(c["codigo"])
            c["ini"], c["fim"] = hr
        for (eq, t, a, b, hr), cods in sorted(grupos.items(), key=lambda kv: str(kv[0])):
            mud_horario.append({"equip": eq, "nome_equip": nomes.get(eq, eq), "turno": t,
                                "de": f"{a}–{b}", "para": f"{_hm(hr[0])}–{_hm(hr[1])}",
                                "inicio": _hm(hr[0]), "fim": _hm(hr[1]),
                                "circuitos": sorted(cods)})
        nec = necessidade(circ, folga)
    elif not tur:
        avisos.append("O perfil não tem os horários dos turnos (seção turnos): os horários "
                      "do plano foram mantidos.")

    # 1) equipamento que o edital não tem no turno
    mud_turno, trocas = [], []
    if rec["equip"] and mudar_turno:
        for (eq, t), (n, _) in sorted(nec["veiculos"].items(), key=lambda kv: str(kv[0])):
            if eq not in rec["equip"] or rec["equip"][eq].get(t, 0) > 0:
                continue
            outro = "Diurno" if t == "Noturno" else "Noturno"
            if rec["equip"][eq].get(outro, 0) <= 0:
                continue
            for c in sorted([c for c in circ if c["equip"] == eq and c["turno"] == t],
                            key=lambda c: c["t"] or 0):
                antes_c = (c["turno"], c["ini"], c["fim"])
                _mudar_turno(c, outro, tur)
                if _pico_de(circ, eq, outro, folga) > rec["equip"][eq][outro]:
                    c["turno"], c["ini"], c["fim"] = antes_c
                    break
                mud_turno.append(_registro_turno(
                    c, t, nomes, f"o edital não tem {nomes.get(eq, eq)} no {t.lower()}; "
                    f"no {outro.lower()} há sobra"))
        nec = necessidade(circ, folga)

    sobra = {}
    for eq, d in rec["equip"].items():
        for t in TURNOS:
            sobra[(eq, t)] = d.get(t, 0) - nec["veiculos"].get((eq, t), (0, 0))[0]
    if rec["equip"]:
        for (eq, t), (n, _) in sorted(nec["veiculos"].items(), key=lambda kv: str(kv[0])):
            if eq in rec["equip"] and rec["equip"][eq].get(t, 0) > 0:
                continue
            alternativas = sorted(
                [k for (k, tt) in sobra if tt == t and k != eq and rec["equip"][k].get(t, 0) > 0],
                key=lambda k: (-_semelhanca(nomes.get(eq, eq), nomes.get(k, k)),
                               -sobra[(k, t)]))
            forcado = (substituicoes or {}).get((eq, t))
            if forcado is not None:
                novo = forcado
            else:
                cabem = [k for k in alternativas if sobra[(k, t)] >= n]
                novo = (cabem or alternativas or [""])[0]
            afetados = [c for c in circ if c["equip"] == eq and c["turno"] == t]
            trocas.append({"de": eq, "nome_de": nomes.get(eq, eq), "turno": t, "para": novo,
                           "nome_para": nomes.get(novo, novo) if novo else "",
                           "alternativas": [{"codigo": k, "nome": nomes.get(k, k),
                                             "sobra": sobra[(k, t)]} for k in alternativas],
                           "circuitos": sorted(c["codigo"] for c in afetados)})
            if novo:
                for c in afetados:
                    c["equip"] = novo
                    if horarios and tur:
                        hr = horario_edital(tur, novo, t, (c["ini"], c["fim"]))
                        if hr:
                            c["ini"], c["fim"] = hr
                sobra[(novo, t)] = sobra.get((novo, t), 0) - n

    # 2) tirar circuitos onde há veículos a mais
    ops, nao_coube = [], []
    por_cod = {c["codigo"]: c for c in circ}
    etapas = [(e, mesma_regiao) for e in ETAPAS]
    if mesma_regiao and outra_regiao:
        etapas.append((ETAPAS[-1], False))
    while True:
        exc = _excessos(circ, rec, folga)
        if not exc:
            break
        melhor = None
        for etapa, mr in etapas:
            melhor = _melhor_operacao(circ, exc, por_cod, etapa, metodo, mr,
                                      distancia, max_receptores, lim)
            if melhor:
                break
        if melhor is None:
            break
        _, tipo, x, partes = melhor
        ops.append(_executar_op(tipo, x, partes, por_cod, nomes, cap, lim))
        circ.remove(x)
        del por_cod[x["codigo"]]

    # 3) ainda sobra veículo: muda de turno se o outro turno tiver sobra
    if mudar_turno:
        for (eq, t), n in sorted(_excessos(circ, rec, folga).items(), key=lambda kv: str(kv[0])):
            outro = "Diurno" if t == "Noturno" else "Noturno"
            if rec["equip"].get(eq, {}).get(outro, 0) <= 0:
                continue
            for c in sorted([c for c in circ if c["equip"] == eq and c["turno"] == t],
                            key=lambda c: c["t"] or 0):
                if _excessos(circ, rec, folga).get((eq, t), 0) <= 0:
                    break
                antes_c = (c["turno"], c["ini"], c["fim"])
                _mudar_turno(c, outro, tur)
                ok = _pico_de(circ, eq, outro, folga) <= rec["equip"][eq][outro] and (
                    c["t"] is None or c["t"] <= jfn(eq, outro) + 1e-6)
                if not ok:
                    c["turno"], c["ini"], c["fim"] = antes_c
                    continue
                mud_turno.append(_registro_turno(c, t, nomes, f"veículos acima do edital no "
                                                 f"{t.lower()}; sobra no {outro.lower()}"))

    # 4) circuitos acima da jornada: passa linhas a vizinhos com folga
    if lim:
        for x in sorted([c for c in circ if c["t"] is not None
                         and c["t"] > jfn(c["equip"], c["turno"]) + 1e-6],
                        key=lambda c: -(c["t"] - jfn(c["equip"], c["turno"]))):
            for etapa, mr in etapas:
                viz = [v for v in circ if v is not x and _compativeis(x, v, mr, etapa)
                       and _tem_tempo(v) and _folga(v, lim) > 0.05
                       and _dist(x["geom"], v["geom"]) <= distancia]
                partes = _aliviar(x, viz, lim)
                if partes:
                    ops.append(_executar_op("aliviar", x, partes, por_cod, nomes, cap, lim))
                    break

    # 5) desdobrar: a sobra de um equipamento vira circuitos novos que saem da base escolhida
    novos = []
    if desdobrar and str(desdobrar).strip():
        if not lim:
            avisos.append("Desdobrar precisa do histórico de operação (tempo de cada circuito).")
        else:
            novos = _desdobrar(circ, rec, nomes, tur, folga, lim, mapa, codigos_plano,
                               str(desdobrar).strip(), equip_desdobrar, distancia_desdobrar,
                               avisos)

    # 6) redimensionar ao máximo: vizinhos mais longe, mais receptores e o outro turno
    if redimensionar:
        if not lim:
            avisos.append("Redimensionar ao máximo precisa do histórico de operação (tempo de "
                          "cada circuito).")
        else:
            ops += _redimensionar(circ, rec, nomes, folga, lim, por_cod, distancia_max,
                                  max_receptores_max)
    for e in equipados:
        c = por_codigo[e["circuito"]]
        e["inicio"], e["fim"] = _hm(c["ini"]), _hm(c["fim"])

    # resultado
    acima = [{"circuito": c["codigo"], "equip": c["equip"], "nome_equip": nomes.get(c["equip"],
                                                                                   c["equip"]),
              "turno": c["turno"], "tempo": round(c["t"], 2),
              "jornada": round(jfn(c["equip"], c["turno"]), 2),
              "dias": [DIAS[i] for i, s in enumerate(c["dias"]) if s]}
             for c in circ if c["t"] is not None and c["t"] > jfn(c["equip"], c["turno"]) + 1e-6]
    acima.sort(key=lambda a: -(a["tempo"] - a["jornada"]))
    horas_depois = horas_por_dia(circ, rec, nomes, jfn) if historico else []
    for (eq, t), n in sorted(_excessos(circ, rec, folga).items(), key=lambda kv: str(kv[0])):
        falta = [h for h in horas_depois if h["codigo"] == eq and h["turno"] == t
                 and h["saldo"] is not None and h["saldo"] < 0]
        txt = (f"{nomes.get(eq, eq)} · {t}: ainda há {n} veículo(s) acima do edital — ")
        if lim:
            pior = min(falta, key=lambda h: h["saldo"]) if falta else None
            txt += ("os vizinhos não têm folga na jornada para receber mais circuitos"
                    + (f"; faltam até {historico_hhmm(-pior['saldo'])} de trabalho por dia "
                       f"({pior['dia']}), ~{-pior['saldo'] / jfn(eq, t):.1f} veículo(s)"
                       if pior else "") + ".")
        else:
            txt += "sem circuitos vizinhos compatíveis (mesmo turno e dias)."
        nao_coube.append(txt)
    if acima:
        nao_coube.append(f"Jornada · {len(acima)} circuito(s) ainda acima da jornada do edital — "
                         "sem vizinho com folga para receber as linhas.")
    depois, _ = _tabela(circ, rec, nomes, folga)
    res = {"plano": os.path.normpath(caminho), "servicos": servicos, "lote": lote,
            "mapa": mapa, "folga": folga, "metodo": metodo, "trocas": trocas, "operacoes": ops,
            "horarios": mud_horario, "mudancas_turno": mud_turno, "acima_jornada": acima,
            "equipados": equipados, "desdobramentos": novos,
            "acima_jornada_antes": acima_antes,
            "horas_antes": horas_antes, "horas_depois": horas_depois,
            "historico": ({k: historico[k] for k in ("arquivo", "periodo", "rds")}
                          | {"cap_viagem": round(cap, 1),
                             "circuitos": sum(1 for c in por_cod.values() if c.get("hist")),
                             "estimados": estimados})
            if historico else None,
            "jornada": round(jornada or (jfn("", "Diurno") if tur else padrao), 4),
            "nao_coube": nao_coube, "antes": antes, "depois": depois, "avisos": avisos,
            "cabe": not nao_coube and not any(l["situacao"] in ("excede", "fora_do_edital")
                                              for l in depois)}
    res["pontos"] = _pontos_orgao(dict(res, _excessos=_excessos(circ, rec, folga)), nomes,
                                  res["jornada"])
    return res


def _pontos_orgao(r, nomes, jornada):
    """Pontos detalhados para levar ao órgão (depois de ganhar a licitação): o que não coube
    no edital e o que a proposta mudou e precisa do aceite dele.
    [{"tema", "situacao", "proposta", "circuitos"}]"""
    from .historico import hhmm
    pts = []
    hd = r.get("horas_depois") or []
    # volume medido × frota inteira do edital, por dia
    tot = defaultdict(lambda: [0.0, 0.0])
    for h in hd:
        if h["capacidade"] is not None:
            tot[h["dia"]][0] += h["horas"]
            tot[h["dia"]][1] += h["capacidade"]
    falta = {d: v[1] - v[0] for d, v in tot.items() if v[1] - v[0] < -0.05}
    if falta:
        pior = min(falta, key=falta.get)
        pts.append({"tema": "Volume de trabalho × frota do edital",
                    "situacao": "Mesmo com todos os veículos do edital trabalhando a jornada "
                                f"inteira ({hhmm(jornada)}), faltam horas: "
                                + "; ".join(f"{d} {hhmm(-v)}" for d, v in falta.items())
                                + f" (pior: {pior}, ~{-falta[pior] / jornada:.1f} veículo(s)). "
                                "O tempo vem do histórico de operação (RDs).",
                    "proposta": "Rever com o órgão o dimensionamento: veículo(s) a mais, coleta "
                                "também no domingo ou flexibilização dos horários dos turnos.",
                    "circuitos": []})
    for (eq, t), n in sorted(r.get("_excessos", {}).items(), key=lambda kv: str(kv[0])):
        dias = [h for h in hd if h["codigo"] == eq and h["turno"] == t
                and h["saldo"] is not None and h["saldo"] < 0]
        lin = next((l for l in r["depois"] if l.get("codigo") == eq and l["turno"] == t
                    and l["categoria"] == "equipamento"), None)
        sit = (f"O plano usa {lin['plano']} veículo(s) ({lin['dia_pico']}) e o edital dá "
               f"{lin['edital']}" if lin else f"{n} veículo(s) acima do edital")
        prop = f"Pedir {n} veículo(s) a mais no {t.lower()}"
        if dias:
            sit += "; faltam " + "; ".join(f"{h['dia']} {hhmm(-h['saldo'])}" for h in dias)
            emh = max(-h["saldo"] for h in dias) / jornada
            if math.ceil(emh) < n:
                prop += (f" — em horas bastariam ~{emh:.1f}, se os circuitos fossem "
                         "reorganizados (roteirização) até a jornada,")
        pts.append({"tema": f"Frota · {nomes.get(eq, eq)} · {t}", "situacao": sit + ".",
                    "proposta": prop + " ou passar circuitos para o outro turno/dia com o "
                                "aceite do órgão.",
                    "circuitos": []})
    for l in r["depois"]:
        if l["categoria"] == "pessoal" and l["situacao"] == "excede":
            pts.append({"tema": f"Pessoal · {l['nome']} · {l['turno']}",
                        "situacao": f"O plano precisa de {l['plano']} ({l['dia_pico']}) e o "
                                    f"edital dá {l['edital']} (veículos × equipe padrão).",
                        "proposta": "Acompanha a frota: resolve junto com os veículos a mais.",
                        "circuitos": []})
    if r.get("acima_jornada"):
        a = r["acima_jornada"]
        pts.append({"tema": "Circuitos acima da jornada",
                    "situacao": f"{len(a)} circuito(s) com tempo típico maior que "
                                f"{hhmm(jornada)} (excesso total "
                                f"{hhmm(sum(x['tempo'] - x['jornada'] for x in a))} por dia); "
                                "os vizinhos não têm folga para receber as linhas.",
                    "proposta": "Dividir com veículo a mais, ou flexibilizar o horário destes "
                                "circuitos com o órgão.",
                    "circuitos": [x["circuito"] for x in a]})
    cruz = sorted({(o["circuito"], x["codigo"]) for o in r["operacoes"] for x in o["recebem"]
                   if x.get("turno") and x["turno"] != o["turno"]})
    if cruz:
        pts.append({"tema": "Áreas que mudam de turno",
                    "situacao": f"{len(cruz)} trecho(s) passam a ser coletados no outro turno "
                                "(ex.: noturno → diurno) para caber na frota: "
                                + ", ".join(f"{a}→{b}" for a, b in cruz[:15])
                                + ("…" if len(cruz) > 15 else "") + ".",
                    "proposta": "Confirmar com o órgão — áreas comerciais costumam ter coleta "
                                "preferencialmente noturna.",
                    "circuitos": sorted({a for a, _ in cruz} | {b for _, b in cruz})})
    mais = sorted({x["codigo"] for o in r["operacoes"] for x in o["recebem"] if x["dias_a_mais"]})
    if mais:
        pts.append({"tema": "Áreas atendidas em mais dias",
                    "situacao": f"{len(mais)} circuito(s) recebem trechos de circuitos com menos "
                                "dias de coleta (a área passa a ter coleta também nesses dias).",
                    "proposta": "Informar ao órgão a nova frequência destas áreas.",
                    "circuitos": mais})
    if r.get("desdobramentos"):
        nv = r["desdobramentos"]
        pts.append({"tema": "Circuitos novos mistos",
                    "situacao": f"{len(nv)} circuito(s) novo(s) "
                                f"({', '.join(n['codigo'] for n in nv)}) com semienterrado + porta "
                                "a porta, feitos com a sobra de veículo.",
                    "proposta": "Aceite do órgão para circuitos mistos e para os códigos novos.",
                    "circuitos": [n["codigo"] for n in nv]})
    if r.get("equipados") or r.get("mudancas_turno"):
        cods = [e["circuito"] for e in r.get("equipados") or []] + \
            [m["circuito"] for m in r.get("mudancas_turno") or []]
        pts.append({"tema": "Equipamento ou turno trocados",
                    "situacao": f"{len(cods)} circuito(s) mudam de equipamento ou de turno.",
                    "proposta": "Informar ao órgão (horário do turno do edital).",
                    "circuitos": cods})
    if r["operacoes"] or r.get("desdobramentos"):
        pts.append({"tema": "Ordem de passagem",
                    "situacao": "Os circuitos que receberam ou cederam linhas mantêm a ordem "
                                "antiga (sem roteirização).",
                    "proposta": "Rever a sequência de coleta antes de entregar o plano "
                                "executivo ao órgão.",
                    "circuitos": sorted({o["circuito"] for o in r["operacoes"]}
                                        | {x["codigo"] for o in r["operacoes"]
                                           for x in o["recebem"]})})
    return pts


def historico_hhmm(h):
    from .historico import hhmm
    return hhmm(h)


def _aliviar(x, viz, lim):
    """Linhas de x (as mais perto dos vizinhos primeiro) que passam para vizinhos com folga até
    x caber na jornada. {codigo: [índices]} ou None."""
    if not viz or not x["linhas"] or x["carga"] <= 0:
        return None
    cap, jfn = lim
    j = jfn(x["equip"], x["turno"])
    ordem = sorted(range(len(x["linhas"])),
                   key=lambda i: min(_dist(x["linhas"][i]["geom"], v["geom"]) for v in viz))
    frac = defaultdict(float)
    partes = defaultdict(list)
    saiu = 0.0
    for i in ordem:
        if _apos_perder(x, saiu, cap)["t"] <= j + 1e-6:
            break
        if saiu > 0.9:
            break
        ln = x["linhas"][i]
        f = ln["km"] / x["carga"]
        for v in sorted(viz, key=lambda v: _dist(ln["geom"], v["geom"])):
            if _apos_receber(v, x, frac[v["codigo"]] + f, cap)["t"] <= \
                    jfn(v["equip"], v["turno"]) + 1e-6:
                frac[v["codigo"]] += f
                partes[v["codigo"]].append(i)
                saiu += f
                break
    return dict(partes) if partes else None


# ------------------------------------------------------------------ desdobrar
def _txt(v):
    return norm(str(v or "")).replace("_", " ")


def _servico_misto(rot, atual):
    """Serviço misto da mesma família (Convencional Porta a Porta -> Convencional Mista);
    sem serviço misto no plano, fica o mesmo."""
    if not rot:
        return atual or ""
    mist = [k for k, v in rot.items() if "mist" in _txt(v)]
    if atual in mist:
        return atual
    fam = _txt(rot.get(atual, "")).replace("coleta", "").split("(")[0].split()
    for k in mist:
        if fam and fam[0] in _txt(rot[k]):
            return k
    return mist[0] if mist else (atual or "")


def _novo_codigo(usados, origem, servico, servicos_plano):
    """Código livre no padrão do plano: prefixo dos circuitos do mesmo serviço + o meio do
    código de origem (ex.: 102701 porta a porta -> 1827NN misto); senão, o maior + 1."""
    if origem.isdigit() and len(origem) >= 5:
        pref = Counter(c[:2] for c, s in servicos_plano.items()
                       if s == servico and c.isdigit() and len(c) == len(origem))
        p = pref.most_common(1)[0][0] if pref else origem[:2]
        for n in range(100):
            cand = f"{p}{origem[2:-2]}{n:02d}"
            if cand not in usados:
                return cand
    nums = [int(c) for c in usados if c.isdigit()]
    if nums:
        return str(max(nums) + 1)
    n = 1
    while f"{origem}-D{n}" in usados:
        n += 1
    return f"{origem}-D{n}"


def _vagas(circ, rec, eq, turno, folga):
    """Veículos do edital que sobram em cada dia (0..6) para o equipamento/turno."""
    d_ed = rec["equip"].get(eq, {})
    nec = necessidade([c for c in circ if c["equip"] == eq and c["turno"] == turno], folga)
    return [(d_ed.get(turno, 0) - nec["por_dia"].get((d, eq, turno), 0))
            if (d < 6 or d_ed.get("domingo")) else 0 for d in range(7)]


def _parte_para(x, b, jx, jb, cap):
    """Linhas de x que passam para o circuito novo b até x caber na jornada (jx), sem b
    passar da dele (jb). Começa pela ponta de x (ou pelo lado de b). [índices] ou None."""
    n = len(x["linhas"])
    if not n or x["carga"] <= 0:
        return None
    if b["geom"] is not None:
        ordem = sorted(range(n), key=lambda i: _dist(x["linhas"][i]["geom"], b["geom"]))
    else:
        cen = x["geom"].centroid if x["geom"] is not None else x["linhas"][0]["geom"]
        ponta = max(range(n), key=lambda i: _dist(x["linhas"][i]["geom"], cen)
                    if x["linhas"][i]["geom"] is not None else -1)
        g0 = x["linhas"][ponta]["geom"]
        ordem = sorted(range(n), key=lambda i: _dist(x["linhas"][i]["geom"], g0))
    frac, idx = 0.0, []
    for i in ordem:
        if _apos_perder(x, frac, cap)["t"] <= jx + 1e-6:
            break
        f = x["linhas"][i]["km"] / x["carga"]
        if _apos_receber(b, x, frac + f, cap)["t"] > jb + 1e-6 or frac + f > 0.9:
            return None
        frac += f
        idx.append(i)
    if idx and _apos_perder(x, frac, cap)["t"] <= jx + 1e-6:
        return idx
    return None


def _desdobrar(circ, rec, nomes, tur, folga, lim, mapa, servicos_plano, base, equip, distancia,
               avisos):
    """Circuitos novos com a sobra de 'equip' (padrão: munk), saindo da 'base':
      A. recebem circuitos inteiros do turno/equipamento com veículos ou horas a menos no
         edital (ex.: compactador noturno -> dia), até a jornada;
      B. recebem a parte acima da jornada dos circuitos da base (mesmos dias).
    Só nos dias em que o edital tem o veículo sobrando. Mexe em 'circ' (os inteiros saem,
    os novos entram). Devolve o relatório dos novos."""
    from shapely.ops import unary_union
    cap, jfn = lim
    eqs = rec["equip"]
    if not equip:
        mk = [k for k in eqs if "munk" in _txt(nomes.get(k, k))]
        equip = mk[0] if mk else max(
            eqs, default="", key=lambda k: sum(_vagas(circ, rec, k, t, folga)[0] for t in TURNOS))
    equip = codigo_valor(equip) if equip else ""
    if equip not in eqs:
        avisos.append(f"Desdobrar: o edital não tem o equipamento {equip or '?'}.")
        return []
    turno = max(TURNOS, key=lambda t: eqs[equip].get(t, 0))
    J = jfn(equip, turno)
    rot = mapa.get("rotulos_servico") or {}
    alvo = _txt(base)
    if mapa.get("base"):
        def da_base(c):
            return alvo in _txt(c.get("base"))
    else:
        avisos.append("Desdobrar: o plano não tem campo de base/garagem nem local de pesagem; "
                      "considerei todos os circuitos.")

        def da_base(c):
            return True
    if not any(da_base(c) for c in circ):
        avisos.append(f"Desdobrar: nenhum circuito sai de '{base}'.")
        return []
    usados = set(servicos_plano) | {c["codigo"] for c in circ}
    novos = []

    def abrir(x):
        serv = _servico_misto(rot, x.get("servico", ""))
        cod = _novo_codigo(usados, x["codigo"], serv, servicos_plano)
        usados.add(cod)
        hr = horario_edital(tur, equip, turno) or (x["ini"], x["fim"])
        return {"codigo": cod, "fid": None, "equip": equip, "turno": turno, "turno_bruto": None,
                "dias": list(x["dias"]), "ini": hr[0], "fim": hr[1], "regiao": x["regiao"],
                "base": x.get("base"), "servico": serv, "geom": None, "carga": 0.0,
                "linhas": [], "pontos": [], "t": 0.0, "prod": 0.0, "peso": 0.0, "viag": 0,
                "tv": x["tv"], "hist": False, "novo": True, "origens": []}

    def cabe_dias(x):
        v = _vagas(circ, rec, equip, turno, folga)
        return all(v[d] > 0 for d, s in enumerate(x["dias"]) if s)

    def perto(b, x):
        return b["geom"] is None or _dist(b["geom"], x["geom"]) <= distancia

    def receber(b, x, idx):
        inteiro = not x["linhas"] or len(idx) == len(x["linhas"])
        km = x["carga"] if inteiro else sum(x["linhas"][i]["km"] for i in idx)
        frac = 1.0 if inteiro or x["carga"] <= 0 else km / x["carga"]
        reg = {"circuito": x["codigo"], "inteiro": inteiro, "equip": x["equip"],
               "nome_equip": nomes.get(x["equip"], x["equip"]), "turno": x["turno"],
               "tempo_antes": round(x["t"], 2), "tempo_depois": None, "km": round(km, 2),
               "linhas": [(x["linhas"][i]["camada"], x["linhas"][i]["fid"]) for i in idx]}
        if inteiro and not b["origens"]:
            # circuito inteiro num circuito novo vazio: fica com o tempo real dele
            b.update({k: x[k] for k in ("t", "prod", "peso", "viag", "tv")})
        else:
            b.update(_apos_receber(b, x, frac, cap))
        if inteiro:
            b["linhas"] += x["linhas"]
            b["pontos"] += x["pontos"]
            if x["geom"] is not None:
                b["geom"] = x["geom"] if b["geom"] is None else \
                    unary_union([b["geom"].buffer(0), x["geom"].buffer(0)])
            circ.remove(x)
        else:
            x.update(_apos_perder(x, frac, cap))
            if x["geom"] is not None:
                _ceder_poligono(x, [b], {b["codigo"]: idx})
            tirar = set(idx)
            b["linhas"] += [x["linhas"][i] for i in idx]
            x["linhas"] = [ln for i, ln in enumerate(x["linhas"]) if i not in tirar]
            x["carga"] -= km
            reg["tempo_depois"] = round(x["t"], 2)
        if b["geom"] is None:
            lin = [ln["geom"] for ln in b["linhas"] if ln["geom"] is not None]
            b["geom"] = unary_union(lin).buffer(30) if lin else None
        b["carga"] += km
        b["origens"].append(reg)
        if not b.get("_no_plano"):
            b["_no_plano"] = True
            circ.append(b)

    # A) circuitos inteiros do turno/equipamento que falta no edital
    while True:
        exc = _excessos(circ, rec, folga)
        df = {}
        for h in horas_por_dia(circ, rec, nomes, jfn):
            if h["saldo"] is not None and h["saldo"] < 0:
                df[(h["codigo"], h["turno"], DIAS.index(h["dia"]))] = -h["saldo"]

        def ganho(x):
            g = sum(min(x["t"], df.get((x["equip"], x["turno"], d), 0))
                    for d, s in enumerate(x["dias"]) if s)
            return g + (x["t"] if (x["equip"], x["turno"]) in exc else 0)

        cands = [x for x in circ if not x.get("novo") and x["turno"] != turno and da_base(x)
                 and x.get("t") is not None and x["t"] <= J + 1e-6 and ganho(x) > 0]
        if not cands:
            break
        escolha = None
        for b in novos:           # primeiro: completar um circuito novo (sem gastar veículo)
            for x in cands:
                if x["dias"] == b["dias"] and perto(b, x) and \
                        _apos_receber(b, x, 1.0, cap)["t"] <= J + 1e-6:
                    if escolha is None or ganho(x) > escolha[0]:
                        escolha = (ganho(x), b, x)
        if escolha is None:
            for x in cands:
                if cabe_dias(x) and (escolha is None or ganho(x) > escolha[0]):
                    escolha = (ganho(x), None, x)
        if escolha is None:
            break
        _, b, x = escolha
        if b is None:
            b = abrir(x)
            novos.append(b)
        receber(b, x, list(range(len(x["linhas"]))))

    # B) parte acima da jornada dos circuitos da base
    acima = sorted([x for x in circ if not x.get("novo") and da_base(x) and x.get("t") is not None
                    and x["t"] > jfn(x["equip"], x["turno"]) + 1e-6 and x["linhas"]],
                   key=lambda x: -(x["t"] - jfn(x["equip"], x["turno"])))
    for x in acima:
        jx = jfn(x["equip"], x["turno"])
        feito = False
        for b in sorted([b for b in novos if b["dias"] == x["dias"] and perto(b, x)],
                        key=lambda b: b["t"]):
            idx = _parte_para(x, b, jx, J, cap)
            if idx:
                receber(b, x, idx)
                feito = True
                break
        if not feito and cabe_dias(x):
            b = abrir(x)
            idx = _parte_para(x, b, jx, J, cap)
            if idx:
                novos.append(b)
                receber(b, x, idx)
            else:
                usados.discard(b["codigo"])

    v = _vagas(circ, rec, equip, turno, folga)
    sobra = [f"{DIAS[d]} {n}" for d, n in enumerate(v)
             if n > 0 and (d < 6 or any(c["dias"][6] for c in circ))]
    if sobra:
        avisos.append(f"Desdobrar: ainda sobra {nomes.get(equip, equip)} no {turno.lower()} "
                      f"({', '.join(sobra)}) — sem circuito de '{base}' que caiba nesses dias.")
    out = []
    for b in novos:
        out.append({"codigo": b["codigo"], "equip": equip, "nome_equip": nomes.get(equip, equip),
                    "turno": turno, "inicio": _hm(b["ini"]), "fim": _hm(b["fim"]),
                    "dias": [DIAS[i] for i, s in enumerate(b["dias"]) if s],
                    "servico": b["servico"], "nome_servico": rot.get(b["servico"], b["servico"]),
                    "base": b.get("base") or "", "regiao": b["regiao"],
                    "tempo": round(b["t"], 2), "carga": round(b["carga"], 2),
                    "origens": b["origens"]})
    return out


# ------------------------------------------------------------------ redimensionar ao máximo
def _receptores_max(x, circ, lim, distancia, turnos):
    """Vizinhos que podem receber linhas de x no redimensionamento: mesmo equipamento, rodam
    em todos os dias de x, num dos 'turnos', com folga na jornada e até 'distancia'."""
    return [v for v in circ if v is not x and not v.get("novo") and v["equip"] == x["equip"]
            and v["turno"] in turnos and _tem_tempo(v) and _folga(v, lim) > 0.05
            and all(dv or not dx for dx, dv in zip(x["dias"], v["dias"]))
            and _dist(x["geom"], v["geom"]) <= distancia]


def _turnos_receber(x, rec):
    """O turno do circuito primeiro; depois o outro, se o edital tem o equipamento nele."""
    outro = "Diurno" if x["turno"] == "Noturno" else "Noturno"
    tt = [[x["turno"]]]
    if rec["equip"].get(x["equip"], {}).get(outro, 0) > 0:
        tt.append([x["turno"], outro])
    return tt


def _redimensionar(circ, rec, nomes, folga, lim, por_cod, distancia, max_receptores):
    """Redimensiona os circuitos ao máximo para caber no edital (sem circuito novo):
      a) veículos acima do edital -> tira circuitos inteiros, repartindo as linhas entre até
         'max_receptores' vizinhos (mesmo equipamento, rodam nos mesmos dias) que vão até a
         jornada — primeiro do mesmo turno, depois do outro turno (o edital não prende a
         coleta domiciliar a um turno);
      b) circuitos acima da jornada -> passam linhas a vizinhos do mesmo jeito.
    Devolve as operações (como as de juntar/dividir/aliviar)."""
    cap, jfn = lim
    ops = []
    tentados = set()
    while True:
        exc = _excessos(circ, rec, folga)
        if not exc:
            break
        nec = necessidade(circ, folga)["por_dia"]
        dias_exc = {(eq, t): {d for (d, e, tt), n in nec.items()
                              if (e, tt) == (eq, t) and n > rec["equip"][eq].get(t, 0)}
                    for (eq, t) in exc}
        cands = [x for x in circ if (x["equip"], x["turno"]) in exc and not x.get("novo")
                 and x["codigo"] not in tentados and _tem_tempo(x) and x["linhas"]
                 and x["carga"] > 0
                 and any(x["dias"][d] for d in dias_exc[(x["equip"], x["turno"])])]
        if not cands:
            break
        # o que mais alivia os dias com excesso e é mais fácil de repartir (menor tempo)
        cands.sort(key=lambda x: (-sum(x["dias"][d] for d in dias_exc[(x["equip"], x["turno"])]),
                                  x["t"]))
        feito = False
        for x in cands:
            tentados.add(x["codigo"])
            for turnos in _turnos_receber(x, rec):
                viz = _receptores_max(x, circ, lim, distancia, turnos)
                if not viz or sum(_folga(v, lim) for v in viz) < x["prod"] * 0.95:
                    continue
                viz.sort(key=lambda v: (v["turno"] != x["turno"], _dist(x["geom"], v["geom"])))
                escolhidos = viz[:max_receptores]
                ordem = sorted(range(len(x["linhas"])),
                               key=lambda i: min(_dist(x["linhas"][i]["geom"], v["geom"])
                                                 for v in escolhidos))
                partes = _distribuir(x, ordem, escolhidos, lim)
                if not partes:
                    continue
                tipo = "juntar" if len(partes) == 1 else "dividir"
                ops.append(_executar_op(tipo, x, partes, por_cod, nomes, cap, lim))
                ops[-1]["redimensionar"] = True
                circ.remove(x)
                por_cod.pop(x["codigo"], None)
                feito = True
                break
            if feito:
                break
        if not feito:
            break

    for x in sorted([c for c in circ if not c.get("novo") and c.get("t") is not None
                     and c["t"] > jfn(c["equip"], c["turno"]) + 1e-6],
                    key=lambda c: -(c["t"] - jfn(c["equip"], c["turno"]))):
        for turnos in _turnos_receber(x, rec):
            if x["t"] <= jfn(x["equip"], x["turno"]) + 1e-6:
                break
            viz = _receptores_max(x, circ, lim, distancia, turnos)
            partes = _aliviar(x, viz, lim)
            if partes:
                ops.append(_executar_op("aliviar", x, partes, por_cod, nomes, cap, lim))
                ops[-1]["redimensionar"] = True
    return ops


def _executar_op(tipo, x, partes, por_cod, nomes, cap, lim):
    """Registra a operação e simula: linhas, carga, tempos e polígonos de quem recebe."""
    recebe = []
    kms = []
    ordem = sorted(partes.items(), key=lambda kv: -len(kv[1]))
    t_x = x.get("t")
    for cod, idx in ordem:
        v = por_cod[cod]
        km = sum(x["linhas"][i]["km"] for i in idx) if x["linhas"] else x["carga"]
        kms.append(km)
        a_mais = [DIAS[i] for i, (dx, dv) in enumerate(zip(x["dias"], v["dias"]))
                  if dv and not dx]
        item = {"codigo": cod, "linhas": [(x["linhas"][i]["camada"], x["linhas"][i]["fid"])
                                          for i in idx],
                "km": round(km, 2), "carga_depois": round(v["carga"] + km, 2),
                "dias_a_mais": a_mais, "outra_regiao": v["regiao"] != x["regiao"],
                "turno": v["turno"], "tempo_antes": None, "tempo_depois": None}
        if lim and _tem_tempo(x, v) and x["carga"] > 0:
            novo = _apos_receber(v, x, km / x["carga"], cap)
            item["tempo_antes"], item["tempo_depois"] = round(v["t"], 2), round(novo["t"], 2)
        recebe.append(item)
    op = {"tipo": tipo, "circuito": x["codigo"], "equip": x["equip"],
          "nome_equip": nomes.get(x["equip"], x["equip"]), "turno": x["turno"],
          "dias": [DIAS[i] for i, s in enumerate(x["dias"]) if s],
          "carga": round(x["carga"], 2), "tempo": round(t_x, 2) if t_x is not None else None,
          "recebem": recebe}
    # simula
    km_x = x["carga"]
    saiu = 0.0
    for km, (cod, idx) in zip(kms, ordem):
        v = por_cod[cod]
        if lim and _tem_tempo(x, v) and km_x > 0:
            v.update(_apos_receber(v, x, km / km_x, cap))
        saiu += km
        v["linhas"] += [x["linhas"][i] for i in idx]
        v["carga"] += km
        if x["geom"] is not None and v["geom"] is not None and tipo == "juntar":
            v["geom"] = v["geom"].union(x["geom"])
    if tipo == "dividir" and x["geom"] is not None:
        _repartir_poligono(x, [por_cod[c] for c in partes], partes)
    if tipo == "aliviar":
        if lim and _tem_tempo(x) and km_x > 0:
            x.update(_apos_perder(x, saiu / km_x, cap))
        tirar = {i for idx in partes.values() for i in idx}
        if x["geom"] is not None:
            _ceder_poligono(x, [por_cod[c] for c in partes], partes)
        x["linhas"] = [ln for i, ln in enumerate(x["linhas"]) if i not in tirar]
        x["carga"] -= saiu
        op["tempo_depois"] = round(x["t"], 2) if x.get("t") is not None else None
        op["carga_depois"] = round(x["carga"], 2)
    else:
        alvo = por_cod[recebe[0]["codigo"]]
        alvo["pontos"] += [pt for pt in x["pontos"] if not pt["inicio_fim"]]
    return op


def _melhor_operacao(circ, exc, por_cod, etapa, metodo, mesma_regiao, distancia,
                     max_receptores, lim=None):
    """(nota, "juntar"|"dividir", circuito, {codigo_receptor: [índices de linhas]}) ou None.
    Nota = maior carga (h com histórico, senão km) de quem recebe depois da operação (menor =
    mais equilibrado). Com histórico, quem recebe tem de caber na jornada."""
    melhor = None

    def com_tempo(x, v):
        return lim is not None and _tem_tempo(x, v) and x["carga"] > 0

    for x in circ:
        if (x["equip"], x["turno"]) not in exc:
            continue
        viz = [v for v in circ if v is not x and _compativeis(x, v, mesma_regiao, etapa)
               and _dist(x["geom"], v["geom"]) <= distancia]
        if not viz:
            continue
        if metodo in ("auto", "juntar") or (metodo == "dividir" and
                                           (len(viz) < 2 or not x["linhas"])):
            for v in viz:
                if com_tempo(x, v):
                    novo = _apos_receber(v, x, 1.0, lim[0])
                    if novo["t"] > lim[1](v["equip"], v["turno"]) + 1e-6:
                        continue
                    nota = novo["t"]
                elif lim is not None:
                    continue
                else:
                    nota = v["carga"] + x["carga"]
                if melhor is None or nota < melhor[0]:
                    melhor = (nota, "juntar", x, {v["codigo"]: list(range(len(x["linhas"])))})
        if metodo in ("auto", "dividir") and len(viz) >= 2 and x["linhas"]:
            partes = _repartir(x, viz, max_receptores, lim)
            if partes and len(partes) >= 2:
                if lim is not None and _tem_tempo(x) and x["carga"] > 0:
                    nota = max(_apos_receber(por_cod[c], x,
                                             sum(x["linhas"][i]["km"] for i in idx) / x["carga"],
                                             lim[0])["t"] for c, idx in partes.items())
                else:
                    nota = max(por_cod[c]["carga"] + sum(x["linhas"][i]["km"] for i in idx)
                               for c, idx in partes.items())
                if melhor is None or nota < melhor[0]:
                    melhor = (nota, "dividir", x, partes)
    return melhor


def _ceder_poligono(x, receptores, partes):
    """x passa aos receptores o pedaço do polígono em volta das linhas que eles receberam."""
    from shapely.ops import unary_union
    poli = x["geom"]
    if poli is None or poli.geom_type not in ("Polygon", "MultiPolygon"):
        return
    tirar = {i for idx in partes.values() for i in idx}
    fica = [ln["geom"] for i, ln in enumerate(x["linhas"])
            if i not in tirar and ln["geom"] is not None]
    zona_fica = unary_union(fica).buffer(30) if fica else None
    cedido = []
    for r in receptores:
        lin = [x["linhas"][i]["geom"] for i in partes.get(r["codigo"], [])
               if x["linhas"][i]["geom"] is not None]
        if not lin:
            continue
        pd = poli.intersection(unary_union(lin).buffer(30))
        if zona_fica is not None:
            pd = pd.difference(zona_fica)
        if pd.is_empty or pd.area < 1:
            continue
        cedido.append(pd)
        r["geom"] = pd if r["geom"] is None else unary_union([r["geom"].buffer(0), pd.buffer(0)])
    if cedido:
        resto = poli.difference(unary_union(cedido))
        if not resto.is_empty:
            x["geom"] = resto


def _repartir_poligono(x, receptores, partes):
    """Divide o polígono de x entre os receptores (pela proximidade das linhas recebidas) e
    junta cada pedaço ao polígono do receptor. Atualiza r["geom"]."""
    from shapely.ops import unary_union
    poli = x["geom"]
    if poli is None:
        return {}
    if poli.geom_type not in ("Polygon", "MultiPolygon"):
        return {}
    pedacos = {}
    for r in receptores:
        idx = partes.get(r["codigo"], [])
        lin = [x["linhas"][i]["geom"] for i in idx if x["linhas"][i]["geom"] is not None]
        pedacos[r["codigo"]] = poli.intersection(unary_union(lin).buffer(30)) if lin else None
    usado = unary_union([g for g in pedacos.values() if g is not None and not g.is_empty]) \
        if any(g is not None and not g.is_empty for g in pedacos.values()) else None
    resto = poli.difference(usado) if usado is not None else poli
    for g in getattr(resto, "geoms", [resto]):
        if g.is_empty or g.area < 1:
            continue
        cod = min(pedacos, key=lambda c: _dist(g, pedacos[c]) if pedacos[c] is not None
                  else _dist(g, next(r for r in receptores if r["codigo"] == c)["geom"]))
        pedacos[cod] = g if pedacos[cod] is None else pedacos[cod].union(g)
    for r in receptores:
        pd = pedacos.get(r["codigo"])
        if pd is not None and not pd.is_empty and r["geom"] is not None:
            r["geom"] = unary_union([r["geom"].buffer(0), pd.buffer(0)])
    return pedacos


# ================================================================== aplicar
def destino_padrao(caminho):
    base, ext = os.path.splitext(caminho.rstrip("/\\"))
    return f"{base}_adequado{ext}"


def _copiar(origem, destino):
    if os.path.exists(destino):
        raise FileExistsError(f"Já existe {destino}. Apague ou escolha outro nome.")
    if os.path.isdir(origem):
        shutil.copytree(origem, destino)
    else:
        shutil.copy2(origem, destino)
        if origem.lower().endswith(".shp"):
            b0, b1 = os.path.splitext(origem)[0], os.path.splitext(destino)[0]
            for e in (".shx", ".dbf", ".prj", ".cpg", ".qix", ".sbn", ".sbx"):
                if os.path.exists(b0 + e):
                    shutil.copy2(b0 + e, b1 + e)


def _so_poligonos(g):
    """Geometria válida só com as partes de área (a união pode deixar linhas/pontos soltos)."""
    from shapely import make_valid, set_precision
    from shapely.geometry import MultiPolygon, Polygon
    # grade de 1 mm: o .gdb arredonda as coordenadas ao gravar e isso pode criar autointerseção
    g = make_valid(set_precision(make_valid(g), 0.001))
    partes = []
    for x in getattr(g, "geoms", [g]):
        if isinstance(x, Polygon):
            partes.append(x)
        elif isinstance(x, MultiPolygon):
            partes += list(x.geoms)
        elif hasattr(x, "geoms"):
            partes += [y for y in x.geoms if isinstance(y, Polygon)]
    partes = [x for x in partes if x.area > 0.01]
    return MultiPolygon(partes) if len(partes) != 1 else partes[0]


def _para_ogr(g, tipo_camada):
    from osgeo import ogr
    if g.geom_type in ("Polygon", "MultiPolygon", "GeometryCollection"):
        g = _so_poligonos(g)
    og = ogr.CreateGeometryFromWkb(g.wkb)
    return ogr.ForceTo(og, tipo_camada)


@estrutura.com_excecoes
def aplicar(p, caminho, proposta, saida=None):
    """Grava a proposta numa cópia do plano. Devolve {"saida", "trocas", "operacoes", "avisos"}."""
    from shapely.ops import unary_union
    saida = saida or destino_padrao(caminho)
    _copiar(caminho, saida)
    mapa = proposta["mapa"]
    circ, _, _ = ler_circuitos(saida, mapa)
    por_cod = {c["codigo"]: c for c in circ}
    ds = estrutura.abrir(saida, gravar=True)
    lyr = ds.GetLayerByName(mapa["camada"])
    tipo_poli = lyr.GetGeomType()
    avisos = []

    def gravar_campo(camada, fid, campo, valor):
        l = ds.GetLayerByName(camada)
        f = l.GetFeature(fid)
        if f is None:
            return
        i = f.GetFieldIndex(campo)
        tipo = f.GetFieldDefnRef(i).GetType()
        from osgeo import ogr
        if tipo in (ogr.OFTInteger, ogr.OFTInteger64):
            valor = int(valor)
        elif tipo == ogr.OFTReal:
            valor = float(valor)
        f.SetField(i, valor)
        l.SetFeature(f)

    def gravar_hora(fid, campo, minutos):
        if not campo or minutos is None:
            return
        from osgeo import ogr
        f = lyr.GetFeature(fid)
        i = f.GetFieldIndex(campo)
        if i < 0:
            return
        h, m = divmod(int(minutos) % 1440, 60)
        tipo = f.GetFieldDefnRef(i).GetType()
        if tipo == ogr.OFTDateTime:
            f.SetField(i, 1899, 12, 30, h, m, 0, 100)
        elif tipo == ogr.OFTDate:
            return
        elif tipo == ogr.OFTTime:
            f.SetField(i, 0, 0, 0, h, m, 0, 0)
        elif tipo in (ogr.OFTInteger, ogr.OFTInteger64):
            f.SetField(i, h * 100 + m)
        elif tipo == ogr.OFTReal:
            f.SetField(i, (h * 60 + m) / 1440.0)
        else:
            f.SetField(i, f"{h:02d}:{m:02d}")
        lyr.SetFeature(f)

    # valor do campo turno como o plano já escreve (ex.: 'Diurno', 'NOTURNO', '1 - Diurno')
    bruto = {}
    for c in circ:
        if c.get("turno_bruto") not in (None, ""):
            bruto.setdefault(c["turno"], c["turno_bruto"])

    # 0) horários do edital
    n_horarios = 0
    for h in proposta.get("horarios") or []:
        ini, fim = _minutos(h["inicio"]), _minutos(h["fim"])
        for cod in h["circuitos"]:
            c = por_cod.get(cod)
            if c:
                gravar_hora(c["fid"], mapa["inicio"], ini)
                gravar_hora(c["fid"], mapa["fim"], fim)
                n_horarios += 1

    # 1) mudanças de turno
    n_turno = 0
    for m in proposta.get("mudancas_turno") or []:
        c = por_cod.get(m["circuito"])
        if c is None:
            avisos.append(f"Circuito {m['circuito']} não encontrado na cópia.")
            continue
        if mapa["turno"]:
            gravar_campo(mapa["camada"], c["fid"], mapa["turno"],
                         bruto.get(m["para"], m["para"]))
        gravar_hora(c["fid"], mapa["inicio"], _minutos(m["inicio"]))
        gravar_hora(c["fid"], mapa["fim"], _minutos(m["fim"]))
        c["turno"] = m["para"]
        n_turno += 1

    # 2) trocas de equipamento (escolha do usuário e substitutos do edital)
    n_trocas = 0
    for e in proposta.get("equipados") or []:
        c = por_cod.get(e["circuito"])
        if c:
            gravar_campo(mapa["camada"], c["fid"], mapa["equipamento"], e["para"])
            n_trocas += 1
    for t in proposta.get("trocas") or []:
        if not t.get("para"):
            continue
        for cod in t["circuitos"]:
            c = por_cod.get(cod)
            if c:
                gravar_campo(mapa["camada"], c["fid"], mapa["equipamento"], t["para"])
                n_trocas += 1

    # 3) juntar / dividir / aliviar
    campo_cod = {cam: campo for cam, campo in mapa["linhas"] + mapa["pontos"] + mapa["tabelas"]}
    for op in proposta.get("operacoes") or []:
        x = por_cod.get(op["circuito"])
        if x is None:
            avisos.append(f"Circuito {op['circuito']} não encontrado na cópia.")
            continue
        receptores = [por_cod[r["codigo"]] for r in op["recebem"] if r["codigo"] in por_cod]
        if not receptores:
            continue
        partes = {}
        idx_de = {(ln["camada"], ln["fid"]): i for i, ln in enumerate(x["linhas"])}
        for r in op["recebem"]:
            idx = [idx_de[tuple(k)] for k in r["linhas"] if tuple(k) in idx_de]
            partes[r["codigo"]] = idx
            for i in idx:
                ln = x["linhas"][i]
                gravar_campo(ln["camada"], ln["fid"], campo_cod[ln["camada"]], r["codigo"])
                por_cod[r["codigo"]]["linhas"].append(ln)
        if op["tipo"] == "aliviar":
            # x continua; cede as linhas, o pedaço do polígono e os pontos que caem nele
            if x["geom"] is not None:
                _ceder_poligono(x, receptores, partes)
                for c in [x] + receptores:
                    if c["geom"] is None:
                        continue
                    f = lyr.GetFeature(c["fid"])
                    f.SetGeometry(_para_ogr(c["geom"], tipo_poli))
                    lyr.SetFeature(f)
            tirar = {i for idx in partes.values() for i in idx}
            x["linhas"] = [ln for i, ln in enumerate(x["linhas"]) if i not in tirar]
            for pt in list(x["pontos"]):
                if pt["inicio_fim"] or pt["geom"] is None:
                    continue
                for r in receptores:
                    # o ponto saiu do polígono de x e caiu no de quem recebeu
                    if r["geom"] is not None and r["geom"].covers(pt["geom"]) and not (
                            x["geom"] is not None and x["geom"].covers(pt["geom"])):
                        gravar_campo(pt["camada"], pt["fid"], campo_cod[pt["camada"]],
                                     r["codigo"])
                        r["pontos"].append(pt)
                        x["pontos"].remove(pt)
                        break
            continue
        # linhas que entraram em x depois da proposta (não deveria haver) vão para o 1º
        resto = [i for i in range(len(x["linhas"])) if not any(i in v for v in partes.values())]
        for i in resto:
            ln = x["linhas"][i]
            gravar_campo(ln["camada"], ln["fid"], campo_cod[ln["camada"]], receptores[0]["codigo"])
        # polígono
        if x["geom"] is not None:
            if op["tipo"] == "juntar" or len(receptores) == 1:
                r = receptores[0]
                r["geom"] = unary_union([r["geom"].buffer(0), x["geom"].buffer(0)]) \
                    if r["geom"] is not None else x["geom"]
            else:
                _repartir_poligono(x, receptores, partes)
            for r in receptores:
                if r["geom"] is None:
                    continue
                f = lyr.GetFeature(r["fid"])
                f.SetGeometry(_para_ogr(r["geom"], tipo_poli))
                lyr.SetFeature(f)
        # pontos: início/fim de x saem; os demais vão para o receptor que cobre/está mais perto
        for pt in x["pontos"]:
            l = ds.GetLayerByName(pt["camada"])
            if pt["inicio_fim"]:
                l.DeleteFeature(pt["fid"])
                continue
            alvo = min(receptores, key=lambda r: _dist(pt["geom"], r["geom"]))
            gravar_campo(pt["camada"], pt["fid"], campo_cod[pt["camada"]], alvo["codigo"])
            alvo["pontos"].append(pt)
        for cam, campo in mapa["tabelas"]:
            l = ds.GetLayerByName(cam)
            l.ResetReading()
            fids = [f.GetFID() for f in l if str(f.GetField(campo)) == x["codigo"]]
            for fid in fids:
                gravar_campo(cam, fid, campo, receptores[0]["codigo"])
        lyr.DeleteFeature(x["fid"])
        del por_cod[x["codigo"]]

    # 4) circuitos novos (desdobramento)
    n_novos = 0
    for nv in proposta.get("desdobramentos") or []:
        n_novos += _gravar_novo(ds, lyr, mapa, nv, por_cod, campo_cod, bruto, gravar_campo,
                                gravar_hora, avisos)
    ds.FlushCache()
    ds = None
    if proposta.get("operacoes") or n_novos:
        avisos.append("Sem roteirização: revise a ordem de passagem e os pontos de início/fim "
                      "dos circuitos que receberam linhas e dos circuitos novos.")
    return {"saida": os.path.normpath(saida), "trocas": n_trocas, "horarios": n_horarios,
            "mudancas_turno": n_turno, "novos": n_novos,
            "operacoes": len(proposta.get("operacoes") or []), "avisos": avisos}


def _gravar_novo(ds, lyr, mapa, nv, por_cod, campo_cod, bruto, gravar_campo, gravar_hora,
                 avisos):
    """Cria o circuito novo na cópia: feição copiada do 1º circuito de origem (mesmos dias,
    região e base), com código, equipamento, serviço, turno e horário novos; recebe as linhas,
    o polígono e os pontos das origens. Origem inteira sai do plano."""
    from osgeo import ogr
    from shapely.ops import unary_union
    origens = [(o, por_cod.get(o["circuito"])) for o in nv["origens"]]
    falta = [o["circuito"] for o, c in origens if c is None]
    if falta:
        avisos.append(f"Circuito novo {nv['codigo']}: origem {', '.join(falta)} não encontrada "
                      "na cópia; não foi criado.")
        return 0
    c0 = origens[0][1]
    src = lyr.GetFeature(c0["fid"])
    f = ogr.Feature(lyr.GetLayerDefn())
    f.SetFrom(src)
    for i in range(f.GetFieldCount()):     # textos com o código antigo (ex.: nome do circuito)
        if f.GetFieldDefnRef(i).GetType() == ogr.OFTString and f.IsFieldSetAndNotNull(i):
            s = f.GetFieldAsString(i)
            if c0["codigo"] in s:
                f.SetField(i, s.replace(c0["codigo"], nv["codigo"]))
    lyr.CreateFeature(f)
    fid = f.GetFID()
    novo = {"codigo": nv["codigo"], "fid": fid, "geom": None, "linhas": [], "pontos": []}
    gravar_campo(mapa["camada"], fid, mapa["codigo"], nv["codigo"])
    gravar_campo(mapa["camada"], fid, mapa["equipamento"], nv["equip"])
    if mapa.get("servico") and nv.get("servico") not in (None, ""):
        gravar_campo(mapa["camada"], fid, mapa["servico"], nv["servico"])
    if mapa["turno"]:
        gravar_campo(mapa["camada"], fid, mapa["turno"], bruto.get(nv["turno"], nv["turno"]))
    gravar_hora(fid, mapa["inicio"], _minutos(nv["inicio"]))
    gravar_hora(fid, mapa["fim"], _minutos(nv["fim"]))

    pedacos, inicio_fim = [], False
    for o, c in origens:
        if o["inteiro"]:
            if c["geom"] is not None:
                pedacos.append(c["geom"])
            for ln in c["linhas"]:
                gravar_campo(ln["camada"], ln["fid"], campo_cod[ln["camada"]], nv["codigo"])
            for pt in c["pontos"]:
                gravar_campo(pt["camada"], pt["fid"], campo_cod[pt["camada"]], nv["codigo"])
                inicio_fim = inicio_fim or pt["inicio_fim"]
            for cam, campo in mapa["tabelas"]:
                l = ds.GetLayerByName(cam)
                l.ResetReading()
                for fid_t in [t.GetFID() for t in l if str(t.GetField(campo)) == c["codigo"]]:
                    gravar_campo(cam, fid_t, campo, nv["codigo"])
            lyr.DeleteFeature(c["fid"])
            del por_cod[c["codigo"]]
            continue
        idx_de = {(ln["camada"], ln["fid"]): i for i, ln in enumerate(c["linhas"])}
        idx = [idx_de[tuple(k)] for k in o["linhas"] if tuple(k) in idx_de]
        if not idx:
            continue
        for i in idx:
            ln = c["linhas"][i]
            gravar_campo(ln["camada"], ln["fid"], campo_cod[ln["camada"]], nv["codigo"])
        rec = {"codigo": nv["codigo"], "geom": None}
        if c["geom"] is not None:
            _ceder_poligono(c, [rec], {nv["codigo"]: idx})
            f = lyr.GetFeature(c["fid"])
            f.SetGeometry(_para_ogr(c["geom"], lyr.GetGeomType()))
            lyr.SetFeature(f)
        if rec["geom"] is None:
            lin = [c["linhas"][i]["geom"] for i in idx if c["linhas"][i]["geom"] is not None]
            rec["geom"] = unary_union(lin).buffer(30) if lin else None
        if rec["geom"] is not None:
            pedacos.append(rec["geom"])
            for pt in list(c["pontos"]):
                if pt["inicio_fim"] or pt["geom"] is None:
                    continue
                if rec["geom"].covers(pt["geom"]) and not (
                        c["geom"] is not None and c["geom"].covers(pt["geom"])):
                    gravar_campo(pt["camada"], pt["fid"], campo_cod[pt["camada"]], nv["codigo"])
                    c["pontos"].remove(pt)
        tirar = set(idx)
        c["linhas"] = [ln for i, ln in enumerate(c["linhas"]) if i not in tirar]
    # início/fim: sem origem inteira, copia os da 1ª origem (a rever na roteirização)
    if not inicio_fim:
        for pt in c0["pontos"]:
            if not pt["inicio_fim"]:
                continue
            l = ds.GetLayerByName(pt["camada"])
            orig = l.GetFeature(pt["fid"])
            if orig is None:
                continue
            cp = ogr.Feature(l.GetLayerDefn())
            cp.SetFrom(orig)
            l.CreateFeature(cp)
            gravar_campo(pt["camada"], cp.GetFID(), campo_cod[pt["camada"]], nv["codigo"])
    if pedacos:
        g = unary_union([x.buffer(0) for x in pedacos])
        f = lyr.GetFeature(fid)
        f.SetGeometry(_para_ogr(g, lyr.GetGeomType()))
        lyr.SetFeature(f)
    por_cod[nv["codigo"]] = novo
    return 1


# ================================================================== relatório
def relatorio_xlsx(proposta, caminho_xlsx):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    cab_fill = PatternFill("solid", fgColor="44546A")

    def cab(ws, cols, larg):
        ws.append(cols)
        for c, w in zip(ws[ws.max_row], larg):
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = cab_fill
            ws.column_dimensions[c.column_letter].width = w
        ws.freeze_panes = ws.cell(ws.max_row + 1, 1)

    ws = wb.active
    ws.title = "Frota e equipe"
    cab(ws, ["Categoria", "Item", "Turno", "Plano antes", "Plano depois", "Edital",
             "Dia de pico (depois)", "Situação depois"], (13, 50, 10, 12, 13, 10, 18, 16))
    dep = {(l["categoria"], l["codigo"], l["turno"]): l for l in proposta["depois"]}
    for l in proposta["antes"]:
        d = dep.get((l["categoria"], l["codigo"], l["turno"]), {})
        ws.append([l["categoria"], l["nome"], l["turno"], l["plano"], d.get("plano", 0),
                   l["edital"] if l["edital"] is not None else "—", d.get("dia_pico", ""),
                   d.get("situacao", "")])
    wt = wb.create_sheet("Trocas de equipamento")
    cab(wt, ["Turno", "De", "Para", "Circuitos"], (10, 45, 45, 80))
    for t in proposta["trocas"]:
        wt.append([t["turno"], t["nome_de"], t["nome_para"] or "(sem troca)",
                   ", ".join(t["circuitos"])])
    wo = wb.create_sheet("Circuitos retirados")
    cab(wo, ["Operação", "Circuito", "Equipamento", "Turno", "Dias", "Km", "Tempo (h)",
             "Vai para", "Km recebidos", "Carga depois (km)", "Tempo antes (h)",
             "Tempo depois (h)", "Turno de quem recebe"],
        (16, 14, 40, 10, 30, 8, 10, 14, 13, 16, 14, 14, 18))
    for op in proposta["operacoes"]:
        for r in op["recebem"]:
            wo.append([op["tipo"] + (" (máximo)" if op.get("redimensionar") else ""),
                       op["circuito"], op["nome_equip"], op["turno"],
                       ", ".join(op["dias"]), op["carga"], op.get("tempo"), r["codigo"], r["km"],
                       r["carga_depois"], r.get("tempo_antes"), r.get("tempo_depois"),
                       r.get("turno", op["turno"])])
    if proposta.get("horarios"):
        wh = wb.create_sheet("Horários do edital")
        cab(wh, ["Equipamento", "Turno", "Horário no plano", "Horário do edital", "Circuitos"],
            (40, 10, 16, 16, 100))
        for h in proposta["horarios"]:
            wh.append([h["nome_equip"], h["turno"], h["de"], h["para"], ", ".join(h["circuitos"])])
    if proposta.get("mudancas_turno"):
        wm = wb.create_sheet("Mudança de turno")
        cab(wm, ["Circuito", "Equipamento", "De", "Para", "Início", "Término", "Dias",
                 "Tempo (h)", "Motivo"], (12, 40, 10, 10, 8, 8, 40, 10, 70))
        for m in proposta["mudancas_turno"]:
            wm.append([m["circuito"], m["nome_equip"], m["de"], m["para"], m["inicio"], m["fim"],
                       ", ".join(m["dias"]), m.get("tempo"), m["motivo"]])
    if proposta.get("equipados"):
        we = wb.create_sheet("Outro equipamento")
        cab(we, ["Circuito", "De", "Para", "Turno", "Início", "Término", "Dias", "Base",
                 "Tempo (h)"], (12, 40, 40, 10, 8, 8, 40, 32, 10))
        for e in proposta["equipados"]:
            we.append([e["circuito"], e["nome_de"], e["nome_para"], e["turno"], e.get("inicio"),
                       e.get("fim"), ", ".join(e["dias"]), e["base"], e.get("tempo")])
    if proposta.get("desdobramentos"):
        wn = wb.create_sheet("Circuitos novos")
        cab(wn, ["Circuito novo", "Equipamento", "Serviço", "Base", "Turno", "Início",
                 "Término", "Dias", "Tempo (h)", "Km", "Recebe de", "Inteiro/parte",
                 "Turno de origem", "Km recebidos", "Origem antes (h)", "Origem depois (h)"],
            (13, 40, 30, 32, 10, 8, 8, 40, 10, 8, 12, 12, 14, 12, 15, 16))
        for nv in proposta["desdobramentos"]:
            for o in nv["origens"]:
                wn.append([nv["codigo"], nv["nome_equip"], nv["nome_servico"], nv["base"],
                           nv["turno"], nv["inicio"], nv["fim"], ", ".join(nv["dias"]),
                           nv["tempo"], nv["carga"], o["circuito"],
                           "inteiro" if o["inteiro"] else "parte", o["turno"], o["km"],
                           o["tempo_antes"], o["tempo_depois"]])
    if proposta.get("horas_depois"):
        wj = wb.create_sheet("Horas por dia")
        cab(wj, ["Equipamento", "Turno", "Dia", "Circuitos", "Horas necessárias",
                 "Horas do edital (veículos × jornada)", "Saldo (h)"],
            (40, 10, 10, 10, 18, 32, 10))
        for h in proposta["horas_depois"]:
            wj.append([h["nome"], h["turno"], h["dia"], h["circuitos"], h["horas"],
                       h["capacidade"], h["saldo"]])
            if h["saldo"] is not None and h["saldo"] < 0:
                wj.cell(wj.max_row, 7).font = Font(bold=True, color="C00000")
    if proposta.get("acima_jornada"):
        wa = wb.create_sheet("Acima da jornada")
        cab(wa, ["Circuito", "Equipamento", "Turno", "Dias", "Tempo típico (h)", "Jornada (h)",
                 "Excesso (h)"], (12, 40, 10, 40, 16, 12, 12))
        for a in proposta["acima_jornada"]:
            wa.append([a["circuito"], a["nome_equip"], a["turno"], ", ".join(a["dias"]),
                       a["tempo"], a["jornada"], round(a["tempo"] - a["jornada"], 2)])
    if proposta.get("pontos"):
        wp = wb.create_sheet("Pontos para o órgão")
        cab(wp, ["Tema", "Situação", "Proposta", "Circuitos"], (34, 90, 60, 60))
        for pt in proposta["pontos"]:
            wp.append([pt["tema"], pt["situacao"], pt["proposta"], ", ".join(pt["circuitos"])])
        for row in wp.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical="top")
    if proposta["nao_coube"] or proposta["avisos"]:
        wa = wb.create_sheet("Avisos")
        for a in proposta["nao_coube"] + proposta["avisos"]:
            wa.append([a])
        wa.column_dimensions["A"].width = 120
    wb.save(caminho_xlsx)
    return caminho_xlsx
