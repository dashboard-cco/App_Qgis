# -*- coding: utf-8 -*-
"""Frota e equipe: adequar um plano já feito às quantidades de veículos e de pessoal do
edital novo (seções "recursos" e "equipes" do perfil).

- comparar(perfil, plano): veículos que o plano usa (pico por dia e turno, contando que um
  veículo faz dois circuitos do mesmo turno se os horários não se sobrepõem) e pessoal
  (veículos × equipe padrão) contra o que o edital dá.
- propor(perfil, plano): o que fazer para caber:
    1. equipamento que o edital não tem -> substituto do edital com sobra (mais parecido);
    2. tipo/turno com veículos a mais -> tira circuitos, escolhendo a cada passo a operação
       que deixa a carga (km de linhas) mais equilibrada:
         - juntar: o circuito inteiro vai para um vizinho;
         - dividir: as linhas do circuito são repartidas entre 2 ou 3 vizinhos (cada linha
           vai para o vizinho mais perto).
       Só entre circuitos com o mesmo equipamento, turno, dias e horário (e a mesma região,
       se o plano tiver esse campo), vizinhos até 'distancia' metros.
- aplicar(perfil, plano, proposta): grava numa CÓPIA do plano (o original não muda):
  troca equipamentos, passa linhas e pontos para os circuitos que recebem, refaz os
  polígonos e apaga o circuito que saiu (e os pontos de início/fim dele).

Sem roteirização: a ordem de passagem nas linhas recebidas deve ser revista.
Sem QGIS (osgeo + shapely): pode ser testado sozinho.
"""
import datetime
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
        c = {"codigo": cod, "fid": f.GetFID(), "equip": _cod(f.GetField(mapa["equipamento"])),
             "turno": _turno(f.GetField(mapa["turno"]) if mapa["turno"] else None, ini),
             "dias": dias, "ini": ini, "fim": fim,
             "regiao": f.GetField(mapa["regiao"]) if mapa["regiao"] else None,
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


def _repartir(x, vizinhos, max_receptores):
    """Cada linha de x vai para o vizinho mais perto; no máximo 'max_receptores' vizinhos."""
    if not x["linhas"]:
        return None
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


def _excessos(circ, rec, folga):
    nec = necessidade(circ, folga)
    out = {}
    for (eq, t), (n, _) in nec["veiculos"].items():
        if eq in rec["equip"] and n > rec["equip"][eq].get(t, 0):
            out[(eq, t)] = n - rec["equip"][eq].get(t, 0)
    return out


@estrutura.com_excecoes
def propor(p, caminho, servicos=None, lote=None, folga=60, mapa=None, metodo="auto",
           distancia=1500.0, max_receptores=3, mesma_regiao=True, outra_regiao=False,
           substituicoes=None):
    """Proposta para caber na frota do edital (nada é gravado).

    metodo: "auto" (o que equilibra melhor), "juntar" ou "dividir".
    substituicoes: {(codigo, turno): codigo_novo} para forçar/recusar trocas (None = automático;
    código_novo "" = não trocar).
    outra_regiao=True: em último caso, aceita vizinho de outra região (campo de região)."""
    servicos, lote, circ, mapa, avisos, nomes, rec = _contexto(p, caminho, servicos, lote, mapa)
    antes, nec = _tabela(circ, rec, nomes, folga)
    trocas = []

    # 1) equipamento que o edital não tem -> substituto com sobra
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
                sobra[(novo, t)] = sobra.get((novo, t), 0) - n

    # 2) tirar circuitos onde há veículos a mais
    ops, nao_coube = [], []
    por_cod = {c["codigo"]: c for c in circ}
    while True:
        exc = _excessos(circ, rec, folga)
        if not exc:
            break
        melhor = None
        etapas = [(e, mesma_regiao) for e in ETAPAS]
        if mesma_regiao and outra_regiao:
            etapas.append((ETAPAS[-1], False))
        for etapa, mr in etapas:
            melhor = _melhor_operacao(circ, exc, por_cod, etapa, metodo, mr,
                                      distancia, max_receptores)
            if melhor:
                break
        if melhor is None:
            for (eq, t), n in sorted(exc.items(), key=lambda kv: str(kv[0])):
                nao_coube.append(f"{nomes.get(eq, eq)} · {t}: ainda há {n} veículo(s) acima "
                                 "do edital — sem circuitos vizinhos compatíveis (mesmo turno "
                                 "e dias).")
            break
        _, tipo, x, partes = melhor
        recebe = []
        ordem = sorted(partes.items(), key=lambda kv: -len(kv[1]))
        for cod, idx in ordem:
            v = por_cod[cod]
            km = sum(x["linhas"][i]["km"] for i in idx) if x["linhas"] else x["carga"]
            a_mais = [DIAS[i] for i, (dx, dv) in enumerate(zip(x["dias"], v["dias"]))
                      if dv and not dx]
            recebe.append({"codigo": cod, "linhas": [(x["linhas"][i]["camada"],
                                                      x["linhas"][i]["fid"]) for i in idx],
                           "km": round(km, 2), "carga_depois": round(v["carga"] + km, 2),
                           "dias_a_mais": a_mais,
                           "outra_regiao": v["regiao"] != x["regiao"]})
        ops.append({"tipo": tipo, "circuito": x["codigo"], "equip": x["equip"],
                    "nome_equip": nomes.get(x["equip"], x["equip"]), "turno": x["turno"],
                    "dias": [DIAS[i] for i, s in enumerate(x["dias"]) if s],
                    "carga": round(x["carga"], 2), "recebem": recebe})
        # simula
        for r, (cod, idx) in zip(recebe, ordem):
            v = por_cod[cod]
            v["linhas"] += [x["linhas"][i] for i in idx]
            v["carga"] += r["km"]
            if x["geom"] is not None and v["geom"] is not None and tipo == "juntar":
                v["geom"] = v["geom"].union(x["geom"])
        if tipo == "dividir" and x["geom"] is not None:
            _repartir_poligono(x, [por_cod[c] for c in partes], partes)
        alvo = por_cod[recebe[0]["codigo"]]
        alvo["pontos"] += [pt for pt in x["pontos"] if not pt["inicio_fim"]]
        circ.remove(x)
        del por_cod[x["codigo"]]

    depois, _ = _tabela(circ, rec, nomes, folga)
    return {"plano": os.path.normpath(caminho), "servicos": servicos, "lote": lote,
            "mapa": mapa, "folga": folga, "metodo": metodo, "trocas": trocas, "operacoes": ops,
            "nao_coube": nao_coube, "antes": antes, "depois": depois, "avisos": avisos,
            "cabe": not nao_coube and not any(l["situacao"] in ("excede", "fora_do_edital")
                                              for l in depois)}


def _melhor_operacao(circ, exc, por_cod, etapa, metodo, mesma_regiao, distancia,
                     max_receptores):
    """(nota, "juntar"|"dividir", circuito, {codigo_receptor: [índices de linhas]}) ou None.
    Nota = maior carga de quem recebe depois da operação (menor = mais equilibrado)."""
    melhor = None
    for x in circ:
        if (x["equip"], x["turno"]) not in exc:
            continue
        viz = [v for v in circ if v is not x and _compativeis(x, v, mesma_regiao, etapa)
               and _dist(x["geom"], v["geom"]) <= distancia]
        if not viz:
            continue
        if metodo in ("auto", "juntar"):
            for v in viz:
                nota = v["carga"] + x["carga"]
                if melhor is None or nota < melhor[0]:
                    melhor = (nota, "juntar", x, {v["codigo"]: list(range(len(x["linhas"])))})
        if metodo in ("auto", "dividir") and len(viz) >= 2 and x["linhas"]:
            partes = _repartir(x, viz, max_receptores)
            if partes and len(partes) >= 2:
                nota = max(por_cod[c]["carga"] + sum(x["linhas"][i]["km"] for i in idx)
                           for c, idx in partes.items())
                if melhor is None or nota < melhor[0]:
                    melhor = (nota, "dividir", x, partes)
        if metodo == "dividir" and (len(viz) < 2 or not x["linhas"]):
            # sem 2 vizinhos para dividir: junta inteiro no vizinho de menor carga
            v = min(viz, key=lambda v: v["carga"])
            nota = v["carga"] + x["carga"]
            if melhor is None or nota < melhor[0]:
                melhor = (nota, "juntar", x, {v["codigo"]: list(range(len(x["linhas"])))})
    return melhor


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

    # 1) trocas de equipamento
    n_trocas = 0
    for t in proposta.get("trocas") or []:
        if not t.get("para"):
            continue
        for cod in t["circuitos"]:
            c = por_cod.get(cod)
            if c:
                gravar_campo(mapa["camada"], c["fid"], mapa["equipamento"], t["para"])
                n_trocas += 1

    # 2) juntar / dividir
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
    ds.FlushCache()
    ds = None
    if proposta.get("operacoes"):
        avisos.append("Sem roteirização: revise a ordem de passagem e os pontos de início/fim "
                      "dos circuitos que receberam linhas.")
    return {"saida": os.path.normpath(saida), "trocas": n_trocas,
            "operacoes": len(proposta.get("operacoes") or []), "avisos": avisos}


# ================================================================== relatório
def relatorio_xlsx(proposta, caminho_xlsx):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

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
    cab(wo, ["Operação", "Circuito", "Equipamento", "Turno", "Dias", "Km", "Vai para",
             "Km recebidos", "Carga depois (km)"], (10, 14, 40, 10, 30, 8, 14, 13, 16))
    for op in proposta["operacoes"]:
        for r in op["recebem"]:
            wo.append([op["tipo"], op["circuito"], op["nome_equip"], op["turno"],
                       ", ".join(op["dias"]), op["carga"], r["codigo"], r["km"],
                       r["carga_depois"]])
    if proposta["nao_coube"] or proposta["avisos"]:
        wa = wb.create_sheet("Avisos")
        for a in proposta["nao_coube"] + proposta["avisos"]:
            wa.append([a])
        wa.column_dimensions["A"].width = 120
    wb.save(caminho_xlsx)
    return caminho_xlsx
