# -*- coding: utf-8 -*-
"""Ordem de passagem de cada circuito (roteirização por arcos — "problema do carteiro
chinês"): o veículo/equipe precisa passar por TODAS as vias do circuito; o percurso é um
caminho fechado que cobre cada via, repetindo o mínimo possível (deslocamento).

1. As vias do circuito viram um grafo (nós = cruzamentos).
2. Partes soltas do circuito são ligadas pelo caminho mais curto na malha viária toda.
3. Cruzamentos com nº ímpar de vias são pareados (emparelhamento de custo mínimo), e o
   caminho mais curto entre cada par é percorrido de novo (deslocamento sem serviço).
4. Com todos os nós pares, o percurso é um circuito euleriano (Hierholzer), começando no
   ponto de entrada e preferindo respeitar a mão de direção das vias de mão única.

Sem QGIS (networkx + scipy).
"""
from collections import defaultdict

import networkx as nx
import numpy as np
from shapely.geometry import LineString
from shapely.ops import linemerge

MAX_EMPARELHAR = 160         # acima disso, emparelhamento guloso (rápido)
MARGEM_SUB = 1500.0          # m em volta do circuito para procurar caminhos


class Rede:
    """Malha viária inteira (todos os trechos), para os deslocamentos."""

    def __init__(self, segs):
        self.segs = segs
        self.S = nx.Graph()
        for i, s in enumerate(segs):
            u, v = s["u"], s["v"]
            if u == v:
                continue
            w = s["geom"].length
            if not self.S.has_edge(u, v) or self.S[u][v]["w"] > w:
                self.S.add_edge(u, v, w=w, seg=i)
        self._nos = np.array(list(self.S.nodes)) if self.S.number_of_nodes() else np.zeros((0, 2))
        self._lista = list(self.S.nodes)

    def sub(self, nos, margem=MARGEM_SUB):
        xs = [n[0] for n in nos]
        ys = [n[1] for n in nos]
        x0, x1, y0, y1 = min(xs) - margem, max(xs) + margem, min(ys) - margem, max(ys) + margem
        m = ((self._nos[:, 0] >= x0) & (self._nos[:, 0] <= x1) &
             (self._nos[:, 1] >= y0) & (self._nos[:, 1] <= y1))
        return self.S.subgraph([self._lista[i] for i in np.nonzero(m)[0]])

    def caminho(self, G, a, b):
        try:
            return nx.dijkstra_path(G, a, b, weight="w")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            try:
                return nx.dijkstra_path(self.S, a, b, weight="w")
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                return None


def _emparelhar(G, impares):
    """Pares de nós ímpares com a menor soma de distâncias (exato até MAX_EMPARELHAR)."""
    dist = {}
    for o in impares:
        try:
            d = nx.single_source_dijkstra_path_length(G, o, cutoff=6000, weight="w")
        except nx.NodeNotFound:
            d = {}
        dist[o] = d
    pares = []
    if len(impares) <= MAX_EMPARELHAR:
        K = nx.Graph()
        for i, a in enumerate(impares):
            for b in impares[i + 1:]:
                K.add_edge(a, b, w=dist[a].get(b, 1e7))
        pares = list(nx.min_weight_matching(K, weight="w"))
    else:
        cand = sorted((d, a, b) for a in impares for b, d in dist[a].items()
                      if b in dist and a < b)
        livres = set(impares)
        for d, a, b in cand:
            if a in livres and b in livres:
                pares.append((a, b))
                livres -= {a, b}
        sobra = sorted(livres)
        pares += list(zip(sobra[::2], sobra[1::2]))
    return pares


def rota(rede, idx, inicio=None, a_pe=False):
    """Percurso do circuito com as vias `idx` (índices de rede.segs).
    Devolve {"passos": [(seg, de, para, servico?)], "km_servico", "km_deslocamento",
    "contramao_km"}."""
    segs = rede.segs
    R = nx.MultiGraph()
    for i in idx:
        s = segs[i]
        R.add_edge(s["u"], s["v"], key=("s", i), seg=i, servico=True)
    if R.number_of_edges() == 0:
        return {"passos": [], "km_servico": 0.0, "km_deslocamento": 0.0, "contramao_km": 0.0}
    G = rede.sub(list(R.nodes))
    n_d = 0

    def deslocar(caminho):
        nonlocal n_d
        for a, b in zip(caminho[:-1], caminho[1:]):
            d = rede.S[a][b]
            n_d += 1
            R.add_edge(a, b, key=("d", n_d), seg=d["seg"], servico=False)

    # 1) ligar as partes soltas ao maior pedaço
    comps = sorted(nx.connected_components(R), key=len, reverse=True)
    principal = set(comps[0])
    resto = [set(c) for c in comps[1:]]
    while resto:
        alvo = set().union(*resto)
        fontes = [n for n in principal if n in G]
        achou = None
        if fontes:
            dist, cam = nx.multi_source_dijkstra(G, fontes, weight="w")
            melhor = min((dist[n], n) for n in alvo if n in dist) if any(n in dist for n in alvo) else None
            if melhor:
                achou = cam[melhor[1]]
        if achou is None:            # fora do recorte: procura na malha toda
            fontes = [n for n in principal if n in rede.S]
            dist, cam = nx.multi_source_dijkstra(rede.S, fontes, weight="w")
            cands = [(dist[n], n) for n in alvo if n in dist]
            if not cands:
                break                # pedaço sem ligação na malha (ilha): fica de fora
            achou = cam[min(cands)[1]]
        deslocar(achou)
        fim = achou[-1]
        junto = next(c for c in resto if fim in c)
        principal |= junto | set(achou)
        resto.remove(junto)
    if resto:                        # ilhas: só o pedaço principal é percorrido
        R = R.subgraph(principal).copy()

    # 2) nós ímpares → emparelhar e repetir o caminho mais curto
    impares = sorted(n for n, g in R.degree() if g % 2)
    if impares:
        for a, b in _emparelhar(G, impares):
            c = rede.caminho(G, a, b)
            if c:
                deslocar(c)

    # 3) percurso euleriano (preferindo a mão de direção)
    nos = list(R.nodes)
    if inicio is not None:
        arr = np.array(nos)
        k = int(np.argmin((arr[:, 0] - inicio[0]) ** 2 + (arr[:, 1] - inicio[1]) ** 2))
        ini = nos[k]
    else:
        ini = nos[0]
    passos = _euler(R, ini, segs, a_pe)
    km_s = sum(segs[p[0]]["km"] for p in passos if p[3])
    km_d = sum(segs[p[0]]["km"] for p in passos if not p[3])
    contra = 0.0 if a_pe else sum(segs[p[0]]["km"] for p in passos
                 if segs[p[0]]["mao_unica"] and p[1] != segs[p[0]]["u"])
    return {"passos": passos, "km_servico": km_s, "km_deslocamento": km_d,
            "contramao_km": contra}


def _euler(R, ini, segs, a_pe=False):
    adj = defaultdict(list)
    info = {}
    for u, v, k, d in R.edges(keys=True, data=True):
        info[k] = (u, v, d["seg"], d["servico"])
        adj[u].append(k)
        if v != u:
            adj[v].append(k)
    usados = set()

    def nota(k, x):
        u, v, sg, serv = info[k]
        s = segs[sg]
        certo = a_pe or (not s["mao_unica"]) or (x == s["u"])
        return (0 if certo else 2) + (0 if serv else 1)

    pilha = [(ini, None)]
    saida = []
    while pilha:
        x, chegada = pilha[-1]
        lst = [k for k in adj[x] if k not in usados]
        adj[x] = lst
        if lst:
            k = min(lst, key=lambda e: nota(e, x))
            usados.add(k)
            u, v, sg, serv = info[k]
            y = v if x == u else u
            pilha.append((y, (sg, x, y, serv)))
        else:
            pilha.pop()
            if chegada:
                saida.append(chegada)
    saida.reverse()
    return saida


def geometria_passo(segs, passo):
    sg, de, _, _ = passo
    g = segs[sg]["geom"]
    return g if segs[sg]["u"] == de else LineString(list(g.coords)[::-1])


def itinerario(segs, passos, duplas=0):
    """Junta passos seguidos na mesma via e do mesmo tipo: [(ordem, via, servico, km,
    geom, dupla)]. Com duplas > 1, o serviço é repartido em partes iguais de km."""
    total = sum(segs[p[0]]["km"] for p in passos if p[3]) or 1.0
    acum, out = 0.0, []
    for p in passos:
        s = segs[p[0]]
        dup = 0
        if duplas and duplas > 1:
            dup = min(duplas, int(acum / total * duplas) + 1) if p[3] else (out[-1][5] if out else 1)
        if p[3]:
            acum += s["km"]
        via = s["nome"] or "(sem nome)"
        g = geometria_passo(segs, p)
        if out and out[-1][1] == via and out[-1][2] == p[3] and out[-1][5] == dup:
            o = out[-1]
            out[-1] = (o[0], via, p[3], o[3] + s["km"], o[4] + [g], dup)
        else:
            out.append((len(out) + 1, via, p[3], s["km"], [g], dup))
    res = []
    for o in out:
        m = linemerge(o[4]) if len(o[4]) > 1 else o[4][0]
        res.append({"ordem": o[0], "via": o[1], "servico": o[2], "km": o[3], "geom": m,
                    "dupla": o[5]})
    return res
