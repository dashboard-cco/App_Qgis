# -*- coding: utf-8 -*-
"""Setorização e roteirização dos serviços de coleta e varrição (2ª versão).

Primeiro o DIMENSIONAMENTO (planejar), depois a DIVISÃO e a ORDEM DE PASSAGEM:

Coleta (domiciliar, seletiva)
  1. Capacidade de um circuito = (jornada − tempo fora) × velocidade (km) e
     viagens × carga por viagem (t).
  2. Cada bairro: km de vias, população (IBGE) → t/dia; a frequência do bairro dá o pico
     (trissemanal: segunda-feira junta 3 dias) → circuitos necessários.
  3. Bairro pequeno (menos de ~0,6 circuito) junta com o vizinho de mesma frequência;
     bairro grande é dividido em vários circuitos (cada circuito fica dentro do bairro).
  4. A frota fecha a conta: cada veículo-turno faz 1 circuito diário, ou 2 trissemanais
     (seg/qua/sex e ter/qui/sáb), 3 bissemanais ou 6 semanais. A frota toda é usada
     (o edital veda subutilização); se faltar frota, o app avisa (ponto para o órgão).
Varrição manual
  km/mês ÷ dias ÷ equipes = km por equipe/dia (o tamanho do circuito). Bairros de
  varrição diária (centro) primeiro; as outras equipes fazem um circuito por dia da
  semana, com os km repartidos pelos bairros pela população (avenidas e ruas mais densas
  primeiro). Cada circuito é repartido entre as duplas na ordem de passagem.
Varrição mecanizada
  Avenidas; km por varredeira/turno → circuitos em rodízio.
Zonas (drenagem, capina…)
  Uma área por equipe.

Ordem de passagem: roteirizacao.rota (percurso que passa por todas as vias do circuito).
Sem QGIS (osgeo + shapely + numpy + networkx).
"""
import math
import unicodedata
from collections import defaultdict

import numpy as np
from osgeo import ogr
from shapely.geometry import MultiLineString, MultiPoint
from shapely.ops import unary_union

try:
    from . import dimensionamento as DM
    from . import empresa as EMP
    from . import roteirizacao as RT
except ImportError:  # testes
    import dimensionamento as DM
    import empresa as EMP
    import roteirizacao as RT

VIAS = {
    "coleta": {"residential", "living_street", "unclassified", "tertiary", "secondary",
               "primary", "road", "tertiary_link", "secondary_link", "primary_link"},
    "varricao_mec": {"trunk", "primary", "secondary"},
    "varricao": {"residential", "living_street", "unclassified", "tertiary", "secondary",
                 "primary", "pedestrian", "road"},
    "zona": {"residential", "living_street", "unclassified", "tertiary", "secondary",
             "primary", "pedestrian", "service", "road"},
}
PRIORIDADE = {"primary": 0, "trunk": 0, "secondary": 1, "tertiary": 2, "pedestrian": 2,
              "residential": 3, "living_street": 3, "unclassified": 4, "road": 4}
PASSO_PONTOS = 60.0
JUNTAR_ABAIXO = 0.6          # bairro com menos que isso de circuito junta com o vizinho
DENS_MIN_VARRICAO = 15.0     # domicílios por km de via: abaixo disso não há calçada/casas
SALTO_MAX = 800.0            # m: maior caminhada entre dois grupos de ruas do circuito
FATOR_ANDAR = {"primary": 0.5, "secondary": 0.5, "tertiary": 0.75, "pedestrian": 0.75}
DIAS = {
    "diaria": [("", "seg a dom")],
    "trissemanal": [("SQS", "seg, qua, sex"), ("TQS", "ter, qui, sáb")],
    "bissemanal": [("SQ", "seg, qui"), ("TS", "ter, sex"), ("QS", "qua, sáb")],
    "semanal": [("SEG", "seg"), ("TER", "ter"), ("QUA", "qua"), ("QUI", "qui"),
                ("SEX", "sex"), ("SAB", "sáb"), ("DOM", "dom")],
    "quinzenal": [(f"{s}{d}", f"{n} (semana {s})") for s in (1, 2)
                  for d, n in (("SEG", "seg"), ("TER", "ter"), ("QUA", "qua"), ("QUI", "qui"),
                               ("SEX", "sex"), ("SAB", "sáb"), ("DOM", "dom"))],
}
NOME_FREQ = {"diaria": "Diária", "trissemanal": "Trissemanal (3x/semana)",
             "bissemanal": "Bissemanal (2x/semana)", "semanal": "Semanal (1x/semana)",
             "quinzenal": "Quinzenal"}

tipo_servico = DM.tipo_servico


def _sa(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()


def lados(par):
    """Sarjetas varridas por via (o km de varrição do edital é medido na sarjeta)."""
    try:
        return max(1, min(2, int(float(par.get("lados") or 2))))
    except (TypeError, ValueError):
        return 2


def por_slot(freq, dias_semana):
    """Circuitos que um veículo-turno (ou equipe) faz na semana com essa frequência."""
    if freq == "semanal":
        return max(1, min(7, int(dias_semana)))
    if freq == "quinzenal":
        return 2 * max(1, min(7, int(dias_semana)))
    return {"diaria": 1, "trissemanal": 2, "bissemanal": 3}.get(freq, 1)


def pico(freq, dias_semana):
    """Dias de lixo acumulado no pior dia de coleta (segunda-feira)."""
    if freq == "diaria":
        return 1 if int(dias_semana) >= 7 else 2
    return {"trissemanal": 3, "bissemanal": 4, "semanal": 7, "quinzenal": 14}.get(freq, 3)


def acumulo(freq, dias_semana):
    """Dias de lixo acumulado em média por coleta (o dimensionamento usa a média; o pico
    da segunda-feira vira alerta)."""
    if freq == "diaria":
        return 7.0 / max(1, min(7, int(dias_semana)))
    return {"trissemanal": 7 / 3, "bissemanal": 3.5, "semanal": 7.0, "quinzenal": 14.0}.get(freq, 7 / 3)


# ------------------------------------------------------------------ divisão geométrica
def bissecao(pontos, pesos, k):
    """Rótulos 0..k-1: bisseção recursiva pelo eixo mais comprido, cortando no peso
    proporcional ao nº de partes de cada lado (partes com a mesma carga). Os rótulos
    seguem a ordem espacial (vizinhos têm números seguidos)."""
    rot = np.zeros(len(pontos), dtype=int)

    def parte(idx, k, base):
        if k <= 1 or len(idx) <= 1:
            rot[idx] = base
            return
        p = pontos[idx]
        eixo = 0 if np.ptp(p[:, 0]) >= np.ptp(p[:, 1]) else 1
        ordem = idx[np.argsort(p[:, eixo], kind="stable")]
        k1 = k // 2
        acum = np.cumsum(pesos[ordem])
        corte = int(np.searchsorted(acum, acum[-1] * k1 / k)) + 1
        corte = min(max(corte, 1), len(ordem) - 1)
        parte(ordem[:corte], k1, base)
        parte(ordem[corte:], k - k1, base + k1)

    parte(np.arange(len(pontos)), k, 0)
    return rot


def poligonos(geoms_vias, rotulos, k, area):
    """Polígono de cada parte: Voronoi dos pontos das vias, dissolvido por parte e
    recortado na área (bairro/grupo/município) — cobre a área toda, sem sobreposição."""
    import shapely
    uni, dono, vistos = [], [], set()
    for i, ln in enumerate(geoms_vias):
        n = max(1, int(ln.length // PASSO_PONTOS))
        for j in range(n + 1):
            pt = ln.interpolate(min(ln.length, j * PASSO_PONTOS))
            ch = (round(pt.x, 1), round(pt.y, 1))
            if ch in vistos:
                continue
            vistos.add(ch)
            uni.append(pt)
            dono.append(i)
    if k == 1 or len(uni) < 3:
        return [_so_poligonos(area)] + [None] * (k - 1)
    cel = shapely.voronoi_polygons(MultiPoint(uni), extend_to=area.envelope.buffer(2000),
                                   ordered=True).geoms
    por = [[] for _ in range(k)]
    for c, d in zip(cel, dono):
        por[rotulos[d]].append(c)
    out = []
    for lst in por:
        g = unary_union(lst).intersection(area) if lst else None
        out.append(_so_poligonos(g))
    return out


def poligonos_quadras(T, ii, rot, n, area):
    """Polígono de cada parte feito com QUADRAS inteiras (a divisa entre circuitos fica
    numa via ou no limite do município). Cada quadra vai para a parte das vias em volta
    dela; as que não têm via do serviço em volta ficam com a parte vizinha. Depois, uma
    via que ficou no meio do polígono de outra parte passa para essa parte (`rot` é
    corrigido aqui). Devolve None se não houver quadras (aí vale o Voronoi)."""
    import shapely
    from shapely.strtree import STRtree
    if n <= 1:
        return [_so_poligonos(area)]
    qs = T.quadras_em(area)
    if len(qs) < n:
        return None
    geoms = [T.segs[i]["geom"] for i in ii]
    meios = shapely.points([[g.interpolate(0.5, normalized=True).x,
                             g.interpolate(0.5, normalized=True).y] for g in geoms])
    arv = STRtree(geoms)
    lab = [-1] * len(qs)
    for k, q in enumerate(qs):
        hits = arv.query(q.buffer(1.5), predicate="intersects")
        if not len(hits):
            continue
        d = shapely.distance(q.exterior, meios[hits])
        peso = defaultdict(float)
        for j, dj in zip(hits, d):
            if dj < 2.0:
                peso[rot[int(j)]] += geoms[int(j)].length
        if peso:
            lab[k] = max(peso, key=peso.get)
    if all(x < 0 for x in lab):
        return None
    # quadras sem via do serviço em volta: ficam com a vizinha
    aq = STRtree(qs)
    viz = [[int(j) for j in aq.query(q.buffer(0.5), predicate="intersects") if int(j) != k]
           for k, q in enumerate(qs)]
    for _ in range(300):
        mud = False
        for k in range(len(qs)):
            if lab[k] >= 0:
                continue
            peso = defaultdict(float)
            for j in viz[k]:
                if lab[j] >= 0:
                    peso[lab[j]] += 1.0
            if peso:
                lab[k] = max(peso, key=peso.get)
                mud = True
        if not mud:
            break
    if any(x < 0 for x in lab):
        com = [k for k in range(len(qs)) if lab[k] >= 0]
        cs = np.array([[qs[k].centroid.x, qs[k].centroid.y] for k in com])
        for k in range(len(qs)):
            if lab[k] < 0:
                c = qs[k].centroid
                lab[k] = lab[com[int(np.argmin((cs[:, 0] - c.x) ** 2 + (cs[:, 1] - c.y) ** 2))]]
    out = []
    for p in range(n):
        lst = [qs[k] for k in range(len(qs)) if lab[k] == p]
        out.append(_so_poligonos(unary_union(lst)) if lst else None)
    # via no MEIO do polígono de outra parte (as quadras dos dois lados são dela) → muda
    validos = [(p, g) for p, g in enumerate(out) if g is not None]
    if validos:
        ap = STRtree([g for _, g in validos])
        for j, m in enumerate(meios):
            hit = [validos[int(h)][0] for h in ap.query(m, predicate="intersects")
                   if validos[int(h)][1].contains_properly(m)]
            if len(hit) == 1 and hit[0] != rot[j]:
                rot[j] = hit[0]
    return out


def _so_poligonos(g):
    """Só as partes de área (a interseção pode deixar linhas/pontos soltos na borda)."""
    if g is None or g.is_empty:
        return None
    if g.geom_type in ("Polygon", "MultiPolygon"):
        return g.buffer(0)
    partes = [x for x in getattr(g, "geoms", []) if x.geom_type in ("Polygon", "MultiPolygon")]
    return unary_union(partes).buffer(0) if partes else None


# ------------------------------------------------------------------ vias de cada serviço
def vias_do_servico(T, tipo, par):
    out = []
    for i, s in enumerate(T.segs):
        if s["highway"] not in VIAS[tipo]:
            continue
        b = T.bairros[s["bairro"]] if T.bairros and s["bairro"] >= 0 else None
        if b is not None and b.get("frequencia") == "nao":
            continue
        if tipo in ("varricao", "varricao_mec") or (tipo == "coleta" and par.get("so_urbano")):
            if not s["urbano"]:
                continue
        if tipo in ("coleta", "varricao") and s.get("dom_setor") == 0:
            continue              # setor censitário sem domicílios (mata, indústria, represa)
        if tipo == "varricao" and s.get("dens_setor") is not None and \
                s["dens_setor"] < DENS_MIN_VARRICAO:
            continue              # estrada/via sem casas dos lados: ninguém varre a pé
        out.append(i)
    return out


def _freq_bairro(T, b, par, usa_arquivo):
    nome = _sa(T.bairros[b]["nome"]).split()
    palavras = [w.strip() for w in _sa(par.get("diaria_em")).split(",") if w.strip()]
    if any(p in nome for p in palavras):
        return "diaria"
    f = T.bairros[b].get("frequencia")
    if usa_arquivo and f in DIAS:
        return f
    return par.get("frequencia") if par.get("frequencia") in DIAS else "trissemanal"


def _juntar(T, grupos, need_min=JUNTAR_ABAIXO):
    """Junta os grupos (bairros) pequenos com o vizinho de mesma frequência."""
    viz = T.vizinhos_bairros()
    dono = {}
    for gi, g in enumerate(grupos):
        for b in g["bairros"]:
            dono[b] = gi
    vivos = set(range(len(grupos)))
    fixos = set()
    while True:
        cand = [gi for gi in vivos if gi not in fixos and grupos[gi]["need"] < need_min]
        if not cand:
            break
        gi = min(cand, key=lambda x: grupos[x]["need"])
        vz = {dono[v] for b in grupos[gi]["bairros"] for v in viz.get(b, ())
              if v in dono and dono[v] != gi and dono[v] in vivos}
        vz = [x for x in vz if grupos[x]["freq"] == grupos[gi]["freq"]]
        if not vz:
            fixos.add(gi)
            continue
        alvo = min(vz, key=lambda x: grupos[x]["need"])
        a, g = grupos[alvo], grupos[gi]
        for k in ("bairros", "idx", "idx_todos"):
            if k in a and k in g:
                a[k] += g[k]
        for k in ("km", "t_dia", "pop", "need"):
            a[k] += g[k]
        for b in g["bairros"]:
            dono[b] = alvo
        vivos.discard(gi)
        fixos.discard(alvo)
    return [grupos[gi] for gi in sorted(vivos)]


def planejar(T, tipo, par, idx=None, usa_freq_arquivo=True):
    """Dimensionamento: grupos (bairros) com nº de circuitos e a conta da frota."""
    par = DM.converter(par)
    idx = vias_do_servico(T, tipo, par) if idx is None else idx
    carga = T.carga(idx)
    pop_tot = sum(carga.values()) or 1.0
    al = []
    if tipo == "coleta":
        cap_km, cap_t = DM.capacidade(par)
        t_dia = float(par.get("t_mes") or 0) / 30.0
        slots = int(par["veiculos_diurno"]) + int(par["veiculos_noturno"])
        ds = int(par["dias_semana"])
    elif tipo == "varricao":
        # o km do edital é de sarjeta: cada via tem `lados` sarjetas (2 = os dois lados)
        cap_km = float(par["km_mes"]) / max(1, int(par["dias_mes"])) / max(1, int(par["equipes"])) \
            / lados(par)
        cap_t, t_dia = 1.0, 0.0
        slots = int(par["equipes"])
        ds = int(par["dias_semana"])
    elif tipo == "varricao_mec":
        cap_km = float(par["km_mes"]) / max(1, int(par["dias_mes"])) / max(1, int(par["maquinas"])) \
            / lados(par)
        cap_t, t_dia, slots, ds = 1.0, 0.0, int(par["maquinas"]), 7
    else:
        cap_km, cap_t, t_dia, slots, ds = 1.0, 1.0, 0.0, int(par.get("equipes") or 1), 6
    if cap_km <= 0.1 and tipo in ("varricao", "varricao_mec"):
        al.append("Sem a quantidade de km por mês do edital: informe para dimensionar.")
        cap_km = 15.0

    km_tot = sum(T.segs[i]["km"] for i in idx)
    plano = {"tipo": tipo, "par": par, "cap_km": cap_km, "cap_t": cap_t, "slots": slots,
             "km_vias": km_tot, "alertas": al, "grupos": [], "idx": idx, "carga": carga,
             "pop": pop_tot, "t_dia": t_dia, "dias_semana": ds}

    if tipo in ("varricao_mec", "zona") or not T.bairros:
        if tipo == "varricao_mec":
            n = max(slots, int(round(km_tot / cap_km))) if km_tot else 0
            vezes = float(par["km_mes"]) / lados(par) / km_tot if km_tot else 0
            plano["vezes_mes"] = vezes
            if km_tot and vezes < 4:
                al.append(f"As avenidas somam {km_tot:.0f} km: com {float(par['km_mes']):.0f} km/mês "
                          f"cada uma é varrida só {vezes:.1f} vez(es) por mês.")
            freq = "rodizio"
        elif tipo == "zona":
            n, freq = slots, "zona"
        else:
            freq = par.get("frequencia") or "trissemanal"
            n = max(1, slots * por_slot(freq, ds))
        plano["grupos"] = [{"bairros": [], "nomes": ["Município"], "idx": list(idx), "freq": freq,
                            "km": km_tot, "t_dia": t_dia, "pop": pop_tot, "need": n, "n": n}]
        plano["circuitos"] = n
        plano["slots_usados"] = slots if n else 0
        return plano

    # ---------------- por bairro
    usa_arq = usa_freq_arquivo and not (tipo == "coleta" and par.get("so_urbano"))
    if tipo == "varricao":
        usa_arq = False
    por_b = defaultdict(list)
    for i in idx:
        por_b[T.segs[i]["bairro"]].append(i)
    grupos = []
    for b, ii in por_b.items():
        if b < 0:
            continue
        f = _freq_bairro(T, b, par, usa_arq)
        km = sum(T.segs[i]["km"] for i in ii)
        pop = sum(carga[i] for i in ii)
        grupos.append({"bairros": [b], "idx": ii, "freq": f, "km": km, "pop": pop,
                       "t_dia": t_dia * pop / pop_tot, "need": 0.0})

    if tipo == "varricao":
        _varricao_selecionar(T, plano, grupos, cap_km, slots, ds)
        grupos = plano["grupos_sel"]
    for g in grupos:
        if tipo == "coleta":
            g["need"] = max(g["km"] / cap_km, g["t_dia"] * acumulo(g["freq"], ds) / cap_t)
        else:
            g["need"] = g["km"] / cap_km

    def custo(g):
        return 1.0 / por_slot(g["freq"], ds)

    # a frota toda é usada: o "tamanho" de um circuito é ajustado para caber nela
    escala = 1.0
    if tipo == "coleta" and slots:
        escala = sum(g["need"] * custo(g) for g in grupos) / slots or 1.0
        plano["ocupacao"] = escala
        if escala > 1.05:
            al.append(f"Frota insuficiente para a capacidade calculada: cada circuito fica com "
                      f"{escala:.0%} da capacidade (km/t por turno). Ponto para o órgão, ou "
                      "aumentar viagens/velocidade, ou reduzir a frequência.")
        for g in grupos:
            g["need"] = g["need"] / escala
    def usado(gs):
        return sum(g["n"] * custo(g) for g in gs)

    if tipo == "varricao":
        # junta bairros vizinhos até o nº de grupos caber nos circuitos das equipes
        base = grupos
        for lim in (JUNTAR_ABAIXO, 0.8, 1.0, 1.3, 1.6, 2.0, 3.0, 5.0):
            grupos = _juntar(T, [dict(g, bairros=list(g["bairros"]), idx=list(g["idx"]),
                                      **({"idx_todos": list(g["idx_todos"])} if "idx_todos" in g else {}))
                                 for g in base], lim)
            for g in grupos:
                g["n"] = max(1, int(round(g["need"])))
            dia = [g for g in grupos if g["freq"] == "diaria"]
            sem = [g for g in grupos if g["freq"] != "diaria"]
            n_d = sum(g["n"] for g in dia)
            resto = max(0, slots - n_d)
            alvo = resto * (por_slot(sem[0]["freq"], ds) if sem else 0)
            if len(sem) <= alvo:
                break
        if n_d > slots:
            al.append(f"A varrição diária precisa de {n_d} equipes e o edital tem {slots}.")
        # bairros juntados: escolhe as ruas de novo no grupo todo, num bloco só (a pé)
        for g in sem:
            if len(g["bairros"]) > 1 and g.get("idx_todos"):
                g["idx"] = _crescer(T, g["idx_todos"], g["km"], carga)
                g["km"] = sum(T.segs[i]["km"] for i in g["idx"])
                g["pop"] = sum(carga.get(i, 0) for i in g["idx"])
        _repartir(sem, alvo)
    else:
        # junta mais bairros enquanto a frota não fecha (cada circuito ≥ 1 veículo-turno)
        base = grupos
        for lim in (JUNTAR_ABAIXO, 0.7, 0.8, 0.9, 1.0, 1.15, 1.3, 1.5, 2.0):
            grupos = _juntar(T, [dict(g, bairros=list(g["bairros"]), idx=list(g["idx"]))
                                 for g in base], lim)
            _alocar(grupos, slots, custo, ds)
            if usado(grupos) <= slots + 1e-9:
                break
        if usado(grupos) > slots + 1e-9:
            al.append(f"Frota insuficiente: os bairros pedem {usado(grupos):.1f} veículos-turno "
                      f"e o edital tem {slots} (ponto para o órgão).")
    acima_km, acima_t = [], []
    for g in grupos:
        g["nomes"] = [T.bairros[b]["nome"] for b in g["bairros"]]
        g["km_circ"] = g["km"] / g["n"]
        g["t_circ"] = g["t_dia"] * acumulo(g["freq"], ds) / g["n"]
        g["t_pico"] = g["t_dia"] * pico(g["freq"], ds) / g["n"]
        if tipo == "coleta":
            if g["km_circ"] > cap_km * 1.15:
                acima_km.append(g)
            if g["t_pico"] > cap_t * 1.3:
                acima_t.append(g)
    if acima_km:
        m = max(acima_km, key=lambda g: g["km_circ"])
        al.append(f"{sum(g['n'] for g in acima_km)} circuito(s) acima de {cap_km:.0f} km "
                  f"(maior: {m['km_circ']:.0f} km em {', '.join(m['nomes'][:2])}) — em geral "
                  "área rural, com poucas casas; conferir.")
    if acima_t:
        m = max(acima_t, key=lambda g: g["t_pico"])
        al.append(f"{sum(g['n'] for g in acima_t)} circuito(s) passam de {cap_t:.0f} t no pico "
                  f"(segunda-feira; maior: {m['t_pico']:.1f} t em {', '.join(m['nomes'][:2])}) — "
                  "prever viagem extra nesse dia.")
    plano["grupos"] = grupos
    plano["circuitos"] = sum(g["n"] for g in grupos)
    plano["slots_usados"] = usado(grupos)
    return plano


def _alocar(grupos, slots, custo, ds):
    """Nº de circuitos de cada grupo: arredonda o need e ajusta até usar a frota toda,
    com conjuntos completos por veículo-turno (ex.: 2 trissemanais)."""
    def usado():
        return sum(g["n"] * custo(g) for g in grupos)

    for g in grupos:
        g["n"] = max(1, int(round(g["need"])))
    while True:
        cands = [g for g in grupos if usado() + custo(g) <= slots + 1e-9]
        if not cands:
            break
        max(cands, key=lambda x: x["need"] / x["n"])["n"] += 1
    while usado() > slots + 1e-9:
        cands = [g for g in grupos if g["n"] > 1]
        if not cands:
            break
        min(cands, key=lambda x: x["need"] / x["n"])["n"] -= 1
    for f in {g["freq"] for g in grupos}:
        gs = [g for g in grupos if g["freq"] == f]
        k = por_slot(f, ds)
        while sum(g["n"] for g in gs) % k:
            if usado() + custo(gs[0]) <= slots + 1e-9:
                max(gs, key=lambda x: x["need"] / x["n"])["n"] += 1
            else:
                cc = [g for g in gs if g["n"] > 1]
                if not cc:
                    break
                min(cc, key=lambda x: x["need"] / x["n"])["n"] -= 1


def _repartir(grupos, alvo):
    """Distribui `alvo` circuitos entre os grupos pelo need (maiores restos)."""
    if not grupos:
        return
    tot = sum(g["need"] for g in grupos) or 1.0
    base = [max(1, int(alvo * g["need"] / tot)) for g in grupos]
    for g, n in zip(grupos, base):
        g["n"] = n
    while sum(g["n"] for g in grupos) < alvo:
        max(grupos, key=lambda x: x["need"] / x["n"])["n"] += 1
    while sum(g["n"] for g in grupos) > alvo:
        cc = [g for g in grupos if g["n"] > 1]
        if not cc:
            break
        min(cc, key=lambda x: x["need"] / x["n"])["n"] -= 1


def _varricao_selecionar(T, plano, grupos, cap_km, slots, ds):
    """Varrição: os bairros diários entram inteiros; nos outros, o km que as equipes
    restantes conseguem na semana é repartido pela população, avenidas primeiro."""
    dia = [g for g in grupos if g["freq"] == "diaria"]
    sem = [g for g in grupos if g["freq"] != "diaria"]
    km_d = sum(g["km"] for g in dia)
    n_d = math.ceil(km_d / cap_km - 0.15) if km_d else 0
    n_d = min(n_d, slots)
    resto = max(0, slots - n_d)
    f = sem[0]["freq"] if sem else "semanal"
    orcamento = resto * por_slot(f, ds) * cap_km
    # repartição pela população, sem passar do km de cada bairro (enchimento)
    quota = {id(g): 0.0 for g in sem}
    livres = [g for g in sem if g["km"] > 0]
    sobra = orcamento
    while livres and sobra > 0.01:
        pop = sum(g["pop"] for g in livres) or len(livres)
        prox = []
        dist = 0.0
        for g in livres:
            q = sobra * ((g["pop"] or 1) / pop)
            add = min(q, g["km"] - quota[id(g)])
            quota[id(g)] += add
            dist += add
            if quota[id(g)] < g["km"] - 0.01:
                prox.append(g)
        sobra -= dist
        if dist < 0.01:
            break
        livres = prox
    carga = plano["carga"]
    sel = []
    for g in sem:
        q = quota[id(g)]
        if q <= 0.05:
            continue
        esc = _crescer(T, g["idx"], q, carga)
        km = sum(T.segs[i]["km"] for i in esc)
        g2 = dict(g, idx=esc, km=km, pop=sum(carga.get(i, 0) for i in esc),
                  idx_todos=list(g["idx"]))
        sel.append(g2)
    plano["grupos_sel"] = dia + sel
    plano["km_semanal_sem_varricao"] = sum(g["km"] for g in sem) - sum(g["km"] for g in sel)
    if sobra > cap_km:
        plano["alertas"].append(f"Sobram {sobra:.0f} km/semana de capacidade: todas as vias "
                                "urbanas já cabem — dá para aumentar a frequência.")


def _crescer(T, idx, q, carga):
    """Escolhe ~q km de vias do bairro JUNTAS (para a equipe andar de uma rua para a
    vizinha): começa na via mais importante e mais densa e vai crescendo pela malha,
    rua vizinha por rua vizinha; avenidas "contam menos" e entram antes."""
    import heapq
    if not idx:
        return []
    adj = defaultdict(list)
    for i in idx:
        adj[T.segs[i]["u"]].append(i)
        adj[T.segs[i]["v"]].append(i)

    def semente(rest, perto=None):
        if perto is None:
            return min(rest, key=lambda i: (PRIORIDADE.get(T.segs[i]["highway"], 5),
                                            -(carga.get(i, 0) / max(T.segs[i]["km"], 1e-6))))
        return min(rest, key=lambda i: T.segs[i]["geom"].distance(perto))

    resto, esc, km = set(idx), [], 0.0
    while resto and km < q:
        sel = MultiLineString([T.segs[i]["geom"] for i in esc]) if esc else None
        s0 = semente(resto, sel.centroid if sel is not None else None)
        if sel is not None and T.segs[s0]["geom"].distance(sel) > SALTO_MAX:
            # o resto está longe (outro núcleo): a pé não compensa; procura a rua mais
            # perto do que já foi escolhido, senão para
            s0 = min(resto, key=lambda i: T.segs[i]["geom"].distance(sel))
            if T.segs[s0]["geom"].distance(sel) > SALTO_MAX:
                break
        fila = [(0.0, s0)]
        while fila and km < q:
            c, i = heapq.heappop(fila)
            if i not in resto:
                continue
            resto.discard(i)
            esc.append(i)
            km += T.segs[i]["km"]
            passo = T.segs[i]["geom"].length * FATOR_ANDAR.get(T.segs[i]["highway"], 1.0)
            for n in (T.segs[i]["u"], T.segs[i]["v"]):
                for j in adj[n]:
                    if j in resto:
                        heapq.heappush(fila, (c + passo, j))
    return esc


# ------------------------------------------------------------------ divisão + roteiro
def dividir(T, plano):
    """Circuitos: cada grupo é dividido em n partes equilibradas (dentro dos bairros)."""
    tipo, cap_km, cap_t = plano["tipo"], plano["cap_km"], plano["cap_t"]
    carga, pop, t_dia, ds = plano["carga"], plano["pop"], plano["t_dia"], plano["dias_semana"]
    area_mun = T.limite
    circuitos = []
    for gi, g in enumerate(plano["grupos"]):
        ii = g["idx"]
        if not ii:
            continue
        n = min(g["n"], len(ii))
        pk = acumulo(g["freq"], ds) if g["freq"] in DIAS else 1
        t_seg = np.array([t_dia * carga.get(i, 0) / pop for i in ii])
        km = np.array([T.segs[i]["km"] for i in ii])
        pesos = km / cap_km + (t_seg * pk / cap_t if tipo == "coleta" and t_dia else 0)
        pts = np.array([[T.segs[i]["geom"].interpolate(0.5, normalized=True).x,
                         T.segs[i]["geom"].interpolate(0.5, normalized=True).y] for i in ii])
        rot = bissecao(pts, pesos, n)
        if g["bairros"]:
            area = unary_union([T.bairros[b]["geom"] for b in g["bairros"]]).buffer(0)
        else:
            area = area_mun if area_mun is not None else \
                MultiLineString([T.segs[i]["geom"] for i in ii]).convex_hull.buffer(200)
        polis = None
        if hasattr(T, "quadras_em"):
            polis = poligonos_quadras(T, ii, rot, n, area)
        if polis is None:
            polis = poligonos([T.segs[i]["geom"] for i in ii], rot, n, area)
        for k in range(n):
            sel = [ii[j] for j in range(len(ii)) if rot[j] == k]
            if not sel:
                continue
            circuitos.append({"grupo": gi, "parte": k, "idx": sel, "geom": polis[k],
                              "vias_geom": MultiLineString([T.segs[i]["geom"] for i in sel]),
                              "freq": g["freq"], "nomes": g["nomes"],
                              "km": sum(T.segs[i]["km"] for i in sel),
                              "t": sum(t_dia * carga.get(i, 0) / pop for i in sel) * pk})
    return circuitos


def _ruas(T, idx, n=3):
    km = defaultdict(float)
    for i in idx:
        if T.segs[i]["nome"]:
            km[T.segs[i]["nome"]] += T.segs[i]["km"]
    r = sorted(km, key=lambda x: -km[x])
    return ", ".join(r[:n]) + ("…" if len(r) > n else "")


def codigos(p, servico, lote, plano, circuitos):
    """Veículo/equipe, turno, dias e código de cada circuito."""
    s = next((x for x in p.get("servicos") or [] if x["codigo"] == servico), {})
    sigla = (s.get("sigla") or "").strip() or f"S{servico}"
    tipo, par, ds = plano["tipo"], plano["par"], plano["dias_semana"]
    veic = EMP.veiculos_do_edital(p, servico, lote, sigla)
    if tipo == "varricao" or not veic:
        n = plano["slots"]
        veic = [{"identificacao": EMP.ident_veiculo(sigla, lote, "Diurno", i + 1)
                 .replace("-D", "-E"), "turno": "Diurno"} for i in range(n)]
    # unidades de trabalho (o que um veículo-turno faz na semana)
    unidades = []
    if tipo == "varricao_mec":
        nm = max(1, plano["slots"])
        for j in range(nm):
            unidades.append([c for k, c in enumerate(circuitos) if k % nm == j])
    elif tipo == "zona":
        unidades = [[c] for c in circuitos]
    else:
        por_f = defaultdict(list)
        for c in circuitos:
            por_f[c["freq"]].append(c)
        for f, cs in por_f.items():
            k = por_slot(f, ds)
            nu = math.ceil(len(cs) / k)
            if nu > 1 and k > 1:
                # circuitos do mesmo veículo vizinhos: bisseção dos centros em nu partes
                pts = np.array([[c_["geom"].centroid.x, c_["geom"].centroid.y]
                                if c_["geom"] is not None else [0.0, 0.0] for c_ in cs])
                rot = bissecao(pts, np.ones(len(cs)), nu)
                ordem = [cs[i] for i in np.argsort(rot, kind="stable")]
            else:
                ordem = cs
            for j in range(0, len(ordem), k):
                unidades.append(ordem[j:j + k])
    # mais densos (centro) com o turno noturno, se houver
    dens = lambda u: sum(c["t"] for c in u) / max(1e-6, sum(c["km"] for c in u)) \
        if tipo == "coleta" else -sum(c["km"] for c in u)
    unidades.sort(key=lambda u: (0 if u[0]["freq"] == "diaria" else 1, -dens(u)))
    noturnos = [v for v in veic if v["turno"] == "Noturno"]
    diurnos = [v for v in veic if v["turno"] != "Noturno"]
    ordem_v = noturnos + diurnos if tipo == "coleta" else diurnos + noturnos
    sem_veic = 0
    for ui, u in enumerate(unidades):
        if ui < len(ordem_v):
            v = ordem_v[ui]
        else:
            sem_veic += 1
            v = {"identificacao": f"{sigla}-L{int(lote):02d}-X{sem_veic:02d}"
                 if str(lote).isdigit() else f"{sigla}-X{sem_veic:02d}", "turno": "Diurno"}
        for k, c in enumerate(u):
            c["veiculo"], c["turno"] = v["identificacao"], v["turno"]
            if tipo == "varricao_mec":
                c["codigo"] = f"{v['identificacao']}-C{k + 1:02d}"
                c["dias"] = f"rodízio: circuito {k + 1} de {len(u)} (1 por turno)"
                c["frequencia"] = f"{plano.get('vezes_mes', 0):.1f} vez(es)/mês"
            elif tipo == "zona":
                c["codigo"], c["dias"], c["frequencia"] = v["identificacao"], "", "conforme demanda"
            else:
                suf, dias = DIAS[c["freq"]][k] if k < len(DIAS[c["freq"]]) else (f"{k + 1}", "")
                if c["freq"] == "diaria":
                    dias = "seg a dom" if ds >= 7 else "seg a sáb"
                c["codigo"] = v["identificacao"] + (f"-{suf}" if suf else "")
                c["dias"] = dias
                c["frequencia"] = NOME_FREQ.get(c["freq"], c["freq"])
    if sem_veic:
        plano["alertas"].append(f"{sem_veic} conjunto(s) de circuitos sem veículo/equipe "
                                "(códigos X..): falta frota.")
    circuitos.sort(key=lambda c: c["codigo"])
    return circuitos


def inicio_padrao(T):
    if T.limite is not None:
        c = T.limite.representative_point()
        return (c.x, c.y)
    return None


def setorizar(p, servicos, lote, T, params=None, rotear=True, progresso=None, cancelado=None):
    """Planeja, divide, codifica e roteiriza cada serviço. params: {serviço: parâmetros}
    (os do dimensionamento na tela); sem eles, os padrões do edital.
    Devolve {servico: {"plano", "circuitos", "tipo"}}."""
    params = params or {}
    res = {}
    rede = None
    for c in servicos:
        par = params.get(c) or DM.padrao(p, c, lote)
        if not par:
            continue
        tipo = par["tipo"]
        plano = planejar(T, tipo, par)
        if not plano["circuitos"]:
            continue
        circ = dividir(T, plano)
        codigos(p, c, lote, plano, circ)
        if rotear and tipo != "zona":
            if rede is None:
                rede = RT.Rede(T.segs)
            ini = inicio_padrao(T)
            a_pe = tipo == "varricao"
            dup = 0
            if tipo == "varricao":
                dup = max(1, int(plano["par"]["varredores"]) // max(1, int(plano["par"]["equipes"])) // 2)
            for k, ci in enumerate(circ):
                if cancelado and cancelado():
                    raise InterruptedError("Cancelado.")
                if progresso:
                    progresso(f"Ordem de passagem {c}: circuito {k + 1}/{len(circ)}…", k, len(circ))
                if a_pe:      # a equipe começa no próprio circuito (é levada até lá)
                    m = ci["vias_geom"].centroid
                    r = RT.rota(rede, ci["idx"], (m.x, m.y), a_pe=True)
                else:
                    r = RT.rota(rede, ci["idx"], ini)
                ci["rota"] = r
                ci["itinerario"] = RT.itinerario(T.segs, r["passos"], dup)
                ci["km_desloc"] = r["km_deslocamento"]
        if tipo == "varricao":
            longe = [ci for ci in circ if ci.get("km_desloc", 0) > 0.8 * ci["km"]]
            if longe:
                plano["alertas"].append(
                    f"{len(longe)} circuito(s) a pé andam mais sem varrer do que varrendo "
                    f"({', '.join(ci.get('codigo', '') for ci in longe[:4])}"
                    f"{'…' if len(longe) > 4 else ''}): bairros com muitas ruas sem saída ou "
                    "espalhadas — conferir no mapa; pode valer levar a equipe de carro.")
        for ci in circ:
            ci["nome"] = " + ".join(ci["nomes"][:3]) + ("…" if len(ci["nomes"]) > 3 else "")
            if ci["nome"] == "Município" or not ci["nome"]:
                ci["nome"] = _ruas(T, ci["idx"])
            ci["ruas"] = _ruas(T, ci["idx"], 5)
            ci["horas"] = _horas(plano, ci)
        res[c] = {"plano": plano, "circuitos": circ, "tipo": tipo}
    return res


def _horas(plano, ci):
    par, tipo = plano["par"], plano["tipo"]
    if tipo == "coleta":
        return ci["km"] / float(par["velocidade_kmh"]) + float(par["improdutivo_h"]) + \
            ci.get("km_desloc", 0) / 20.0
    return None


# ------------------------------------------------------------------ resumo / gravar
def resumo(res):
    """Linhas por serviço para a tela e o relatório."""
    out = []
    for c, r in res.items():
        pl, circ = r["plano"], r["circuitos"]
        por_f = defaultdict(int)
        for ci in circ:
            por_f[ci.get("frequencia") or ci["freq"]] += 1
        km = [ci["km"] for ci in circ] or [0]
        out.append({"servico": c, "tipo": r["tipo"], "circuitos": len(circ),
                    "por_frequencia": dict(por_f), "km_min": min(km), "km_max": max(km),
                    "km_medio": sum(km) / len(km), "cap_km": pl["cap_km"],
                    "cap_t": pl["cap_t"], "slots": pl["slots"],
                    "slots_usados": pl.get("slots_usados"), "grupos": len(pl["grupos"]),
                    "km_vias": pl["km_vias"], "alertas": list(pl["alertas"]),
                    "km_desloc": sum(ci.get("km_desloc", 0) for ci in circ)})
    return out


CAMPOS_SETORES = [("bairros", ogr.OFTString), ("veiculo", ogr.OFTString),
                  ("km", ogr.OFTReal), ("km_desloc", ogr.OFTReal), ("t_coleta", ogr.OFTReal),
                  ("horas", ogr.OFTReal), ("origem", ogr.OFTString)]
CAMPOS_ROTAS = [("via", ogr.OFTString), ("tipo", ogr.OFTString), ("dupla", ogr.OFTInteger),
                ("km", ogr.OFTReal), ("origem", ogr.OFTString)]


def gravar(gpkg, p, res):
    """Grava os circuitos (setores) e a ordem de passagem (rotas: um trecho por linha,
    na ordem) no mapa do plano, trocando o que o app gravou antes. Devolve o nº de
    circuitos."""
    ds = ogr.Open(gpkg, 1)
    for nome, campos in (("setores", CAMPOS_SETORES), ("rotas", CAMPOS_ROTAS)):
        lyr = ds.GetLayerByName(nome)
        if lyr is None:
            continue
        defn = lyr.GetLayerDefn()
        for k, t in campos:
            if defn.GetFieldIndex(k) < 0:
                lyr.CreateField(ogr.FieldDefn(k, t))
        lyr.SetAttributeFilter("origem = 'App_Qgis'")
        for fid in [f.GetFID() for f in lyr]:
            lyr.DeleteFeature(fid)
        lyr.SetAttributeFilter(None)
    ls, lr = ds.GetLayerByName("setores"), ds.GetLayerByName("rotas")
    n = 0

    def put(f, campos):
        d = f.GetDefnRef()
        for k, v in campos.items():
            if d.GetFieldIndex(k) >= 0 and v is not None:
                f.SetField(k, v)

    ds.StartTransaction()
    for c, r in res.items():
        pl = r["plano"]
        obs = ("Gerado pelo App_Qgis: dimensionamento pela frota/jornada/frequência do edital, "
               "divisão por bairros (IBGE/OSM) e ordem de passagem calculada. Revisar.")
        for ci in r["circuitos"]:
            if ci["geom"] is not None:
                f = ogr.Feature(ls.GetLayerDefn())
                f.SetGeometry(ogr.ForceToMultiPolygon(ogr.CreateGeometryFromWkb(ci["geom"].wkb)))
                put(f, {"codigo": ci["codigo"], "nome": ci["nome"][:250], "servico": c,
                        "frequencia": ci.get("frequencia", "")[:250], "turno": ci.get("turno"),
                        "dias": ci.get("dias"), "observacao": obs, "origem": "App_Qgis",
                        "bairros": ", ".join(ci["nomes"])[:250], "veiculo": ci.get("veiculo"),
                        "km": round(ci["km"], 2), "km_desloc": round(ci.get("km_desloc", 0), 2),
                        "t_coleta": round(ci["t"], 2) if r["tipo"] == "coleta" else None,
                        "horas": round(ci["horas"], 2) if ci.get("horas") else None})
                ls.CreateFeature(f)
            if lr is None:
                continue
            itin = ci.get("itinerario")
            if itin:
                for it in itin:
                    fr = ogr.Feature(lr.GetLayerDefn())
                    fr.SetGeometry(ogr.ForceToMultiLineString(
                        ogr.CreateGeometryFromWkb(it["geom"].wkb)))
                    put(fr, {"codigo": ci["codigo"], "setor": ci["codigo"], "servico": c,
                             "turno": ci.get("turno"), "ordem": it["ordem"],
                             "via": it["via"][:250],
                             "tipo": "servico" if it["servico"] else "deslocamento",
                             "dupla": it["dupla"] or None, "km": round(it["km"], 3),
                             "observacao": ("" if it["servico"] else
                                            "deslocamento sem serviço (via já feita ou ligação)"),
                             "origem": "App_Qgis"})
                    lr.CreateFeature(fr)
            elif ci.get("vias_geom") is not None:
                fr = ogr.Feature(lr.GetLayerDefn())
                fr.SetGeometry(ogr.ForceToMultiLineString(
                    ogr.CreateGeometryFromWkb(ci["vias_geom"].wkb)))
                put(fr, {"codigo": ci["codigo"], "setor": ci["codigo"], "servico": c,
                         "turno": ci.get("turno"), "tipo": "servico",
                         "km": round(ci["km"], 3), "origem": "App_Qgis",
                         "observacao": "Vias da área (sem ordem de passagem)."})
                lr.CreateFeature(fr)
        n += len(r["circuitos"])
    ds.CommitTransaction()
    ds = None
    return n


def planilha(destino, res, nomes_servicos=None):
    """Planilha do dimensionamento, dos circuitos e dos itinerários (ordem de passagem)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Dimensionamento"
    ws.append(["Serviço", "Item", "Valor"])
    for c, r in res.items():
        pl = r["plano"]
        nm = (nomes_servicos or {}).get(c, "")
        ws.append([f"{c} {nm}", "Tipo", DM.ROTULOS_TIPO.get(r["tipo"], r["tipo"])])
        for k, rot, _ in DM.CAMPOS.get(r["tipo"], []):
            if k in pl["par"]:
                ws.append([c, rot, pl["par"][k]])
        for lin in DM.resumo_parametros(pl["par"]):
            ws.append([c, "Conta", lin])
        ws.append([c, "Vias do serviço (km)", round(pl["km_vias"], 1)])
        ws.append([c, "Circuitos", len(r["circuitos"])])
        ws.append([c, "Veículos/equipes-turno usados", f"{pl.get('slots_usados', 0):.1f} de {pl['slots']}"])
        for a in pl["alertas"]:
            ws.append([c, "ALERTA", a])
        ws.append([])
    wc = wb.create_sheet("Circuitos")
    wc.append(["Serviço", "Circuito", "Veículo/equipe", "Turno", "Frequência", "Dias",
               "Bairros", "Principais vias", "km de serviço", "km de deslocamento",
               "t por coleta (pico)", "Horas estimadas"])
    for c, r in res.items():
        for ci in r["circuitos"]:
            wc.append([c, ci["codigo"], ci.get("veiculo"), ci.get("turno"), ci.get("frequencia"),
                       ci.get("dias"), ", ".join(ci["nomes"]), ci.get("ruas"),
                       round(ci["km"], 2), round(ci.get("km_desloc", 0), 2),
                       round(ci["t"], 2) if r["tipo"] == "coleta" else None,
                       round(ci["horas"], 2) if ci.get("horas") else None])
    wi = wb.create_sheet("Itinerários")
    wi.append(["Serviço", "Circuito", "Ordem", "Via", "Tipo", "Dupla", "km"])
    for c, r in res.items():
        for ci in r["circuitos"]:
            for it in ci.get("itinerario") or []:
                wi.append([c, ci["codigo"], it["ordem"], it["via"],
                           "serviço" if it["servico"] else "deslocamento",
                           it["dupla"] or None, round(it["km"], 3)])
    for w in (ws, wc, wi):
        for cel in w[1]:
            cel.font = Font(bold=True)
        w.freeze_panes = "A2"
    wb.save(destino)
    return destino
