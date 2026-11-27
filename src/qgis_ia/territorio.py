# -*- coding: utf-8 -*-
"""Território do município para a setorização: vias (trechos entre cruzamentos), setores
censitários do IBGE (população e domicílios) e bairros.

Bairros: os do IBGE quando a prefeitura informou (NM_BAIRRO nos setores); senão, cada
setor censitário vai para o ponto de bairro do OpenStreetMap mais próximo e os setores de
um mesmo bairro são unidos — o contorno segue os setores do IBGE (ruas, rios, ferrovias).
O resultado fica em App_Qgis/Base/bairros.gpkg, com o campo "frequencia" que o usuário
pode mudar no QGIS (diaria, trissemanal, bissemanal, semanal ou "nao" para não atender);
na próxima vez o app usa o que estiver no arquivo.

Sem QGIS (osgeo + shapely + numpy + scipy).
"""
import os
import re
import unicodedata
from collections import Counter, defaultdict

import numpy as np
from osgeo import ogr, osr
from shapely import wkb as _wkb
from shapely.geometry import LineString, Point
from shapely.ops import unary_union
from shapely.strtree import STRtree

FREQUENCIAS = ("diaria", "trissemanal", "bissemanal", "semanal", "quinzenal", "nao")


def _sa(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower().strip()


def _srs(epsg):
    s = osr.SpatialReference()
    s.ImportFromEPSG(int(epsg))
    s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return s


def _ler_camada(caminho, epsg=None, camada=None):
    """[(shapely, {campos})] no EPSG pedido."""
    ds = ogr.Open(caminho)
    lyr = ds.GetLayerByName(camada) if camada else ds.GetLayer(0)
    ct = None
    if epsg:
        src = lyr.GetSpatialRef()
        if src is not None and src.GetAuthorityCode(None) != str(epsg):
            src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            ct = osr.CoordinateTransformation(src, _srs(epsg))
    defn = lyr.GetLayerDefn()
    nomes = [defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())]
    out = []
    for f in lyr:
        g = f.GetGeometryRef()
        if g is None or g.IsEmpty():
            continue
        g = g.Clone()
        if ct:
            g.Transform(ct)
        out.append((_wkb.loads(bytes(g.ExportToIsoWkb())), {n: f.GetField(n) for n in nomes}))
    return out


def epsg_de(caminho):
    ds = ogr.Open(caminho)
    s = ds.GetLayer(0).GetSpatialRef()
    return int(s.GetAuthorityCode(None)) if s is not None and s.GetAuthorityCode(None) else None


# ------------------------------------------------------------------ vias em trechos
def _chave(c):
    return (round(c[0], 1), round(c[1], 1))


def segmentar(caminho_vias, epsg=None):
    """Trechos de via entre cruzamentos (os ways do OSM atravessam vários cruzamentos).
    Cada trecho: geom, km, nome, highway, mao_unica, u, v (nós = coordenadas)."""
    linhas = []
    for g, at in _ler_camada(caminho_vias, epsg):
        for ln in getattr(g, "geoms", [g]):
            if ln.length > 0.5:
                linhas.append((ln, at))
    cont = Counter()
    for ln, _ in linhas:
        cs = ln.coords
        for i, c in enumerate(cs):
            cont[_chave(c)] += 2 if i in (0, len(cs) - 1) else 1
    segs = []
    for ln, at in linhas:
        cs = list(ln.coords)
        atual = [cs[0]]
        for i in range(1, len(cs)):
            atual.append(cs[i])
            if i == len(cs) - 1 or cont[_chave(cs[i])] >= 2:
                if len(atual) >= 2:
                    g = LineString(atual)
                    if g.length > 0.1:
                        segs.append({"geom": g, "km": g.length / 1000.0,
                                     "nome": at.get("nome") or "",
                                     "highway": at.get("highway") or "",
                                     "mao_unica": int(at.get("mao_unica") or 0),
                                     "u": _chave(atual[0]), "v": _chave(atual[-1])})
                atual = [cs[i]]
    return segs


# ------------------------------------------------------------------ setores e bairros
def ler_setores(caminho, epsg):
    out = []
    for g, at in _ler_camada(caminho, epsg):
        def num(k):
            try:
                return float(at.get(k) or 0)
            except (TypeError, ValueError):
                return 0.0
        sit = str(at.get("CD_SIT") or "")
        out.append({"geom": g.buffer(0), "pop": num("v0001"), "dom": num("v0002"),
                    "urbano": sit[:1] in ("1", "2", "3", "4") if sit else True,
                    "bairro_ibge": (at.get("NM_BAIRRO") or "").strip(),
                    "codigo": at.get("CD_SETOR") or ""})
    return out


def _nome_bom(nome, municipio):
    n = _sa(nome)
    return n and n != _sa(municipio)


def montar_bairros(setores, pontos_arq=None, epsg=None, municipio=""):
    """Bairros = união dos setores censitários de cada bairro. Devolve (lista, fonte)."""
    com_nome = [s for s in setores if s["bairro_ibge"]]
    grupos = defaultdict(list)
    fonte = ""
    if setores and len(com_nome) >= 0.8 * len(setores):
        for i, s in enumerate(setores):
            grupos[s["bairro_ibge"] or "Sem bairro"].append(i)
        fonte = "IBGE (Censo 2022)"
    elif pontos_arq and os.path.exists(pontos_arq):
        from scipy.spatial import cKDTree
        pts = [(g, at["nome"]) for g, at in _ler_camada(pontos_arq, epsg)
               if _nome_bom(at.get("nome"), municipio)]
        if not pts:
            return [], ""
        # o mesmo nome em pontos diferentes (ex.: "Jardim Luela"/"Jardim Luella") vira um só
        nomes = {}
        for _, n in pts:
            nomes.setdefault(_sa(n).replace("ll", "l"), n)
        arv = cKDTree(np.array([[g.x, g.y] for g, _ in pts]))
        for i, s in enumerate(setores):
            rp = s["geom"].representative_point()
            _, j = arv.query([rp.x, rp.y])
            n = pts[j][1]
            grupos[nomes[_sa(n).replace("ll", "l")]].append(i)
        fonte = "OpenStreetMap (pontos de bairro) + setores do IBGE"
    else:
        return [], ""
    out = []
    for nome, idx in grupos.items():
        g = unary_union([setores[i]["geom"] for i in idx]).buffer(0)
        pop = sum(setores[i]["pop"] for i in idx)
        urb = sum(setores[i]["pop"] for i in idx if setores[i]["urbano"])
        out.append({"nome": nome, "geom": g, "pop": pop,
                    "dom": sum(setores[i]["dom"] for i in idx),
                    "urbano": urb >= 0.5 * pop if pop else False,
                    "setores": idx, "frequencia": ""})
    out.sort(key=lambda b: b["nome"])
    return out, fonte


def gravar_bairros(caminho, bairros, epsg, fonte):
    if os.path.exists(caminho):
        os.remove(caminho)
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(caminho)
    lyr = ds.CreateLayer("bairros", _srs(epsg), ogr.wkbMultiPolygon)
    for n, t in (("nome", ogr.OFTString), ("frequencia", ogr.OFTString),
                 ("populacao", ogr.OFTInteger), ("domicilios", ogr.OFTInteger),
                 ("urbano", ogr.OFTInteger), ("area_km2", ogr.OFTReal), ("fonte", ogr.OFTString)):
        lyr.CreateField(ogr.FieldDefn(n, t))
    lyr.StartTransaction()
    for b in bairros:
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetGeometry(ogr.ForceToMultiPolygon(ogr.CreateGeometryFromWkb(b["geom"].wkb)))
        f.SetField("nome", b["nome"])
        f.SetField("frequencia", b.get("frequencia") or "")
        f.SetField("populacao", int(b["pop"]))
        f.SetField("domicilios", int(b["dom"]))
        f.SetField("urbano", 1 if b["urbano"] else 0)
        f.SetField("area_km2", round(b["geom"].area / 1e6, 3))
        f.SetField("fonte", fonte)
        lyr.CreateFeature(f)
    lyr.CommitTransaction()
    ds = None


def ler_bairros(caminho, epsg):
    out = []
    for g, at in _ler_camada(caminho, epsg):
        out.append({"nome": at.get("nome") or "", "geom": g.buffer(0),
                    "frequencia": _sa(at.get("frequencia")),
                    "pop": float(at.get("populacao") or 0), "dom": float(at.get("domicilios") or 0),
                    "urbano": bool(at.get("urbano"))})
    return out


def frequencia_padrao(texto):
    """(padrão, {palavra do bairro: frequência}) a partir da frequência do edital, ex.:
    "Diária no Centro Expandido; trissemanal nos demais bairros" →
    ("trissemanal", {"centro": "diaria"})."""
    t = _sa(texto)
    especiais = {}
    padrao = ""
    for parte in re.split(r"[;\n]", t):
        f = ("diaria" if re.search(r"diari|todos os dias|seg\w* a dom", parte) else
             "trissemanal" if re.search(r"trissemanal|3x|tres vezes|alternad", parte) else
             "bissemanal" if re.search(r"bissemanal|2x|duas vezes", parte) else
             "semanal" if re.search(r"semanal|1x|uma vez", parte) else "")
        if not f:
            continue
        if re.search(r"demais|restante|outros|outras", parte):
            padrao = f
        m = re.search(r"\b(?:no|na|nos|nas|em)\s+([a-z ]{3,40})", parte)
        if m and not re.search(r"demais|restante", m.group(1)):
            especiais[m.group(1).split()[0]] = f
        elif not padrao:
            padrao = f
    return padrao or "", especiais


def frequencias_dos_bairros(bairros, texto, padrao_sem_texto="trissemanal"):
    """Preenche a frequência dos bairros que ainda não têm (o usuário pode ter editado)."""
    padrao, esp = frequencia_padrao(texto)
    for b in bairros:
        if b.get("frequencia") in FREQUENCIAS:
            continue
        n = _sa(b["nome"])
        f = next((v for k, v in esp.items() if k and k in n.split()), None)
        b["frequencia"] = f or padrao or padrao_sem_texto
    return bairros


class Territorio:
    """Trechos de via + setores + bairros, já relacionados (trecho → setor → bairro)."""

    def __init__(self, vias_arq, limite_arq=None, setores_arq=None, bairros_arq=None,
                 pontos_arq=None, municipio="", texto_frequencia=""):
        self.epsg = epsg_de(vias_arq) or 31983
        self.segs = segmentar(vias_arq, self.epsg)
        self.limite = None
        if limite_arq:
            self.limite = unary_union([g for g, _ in _ler_camada(limite_arq, self.epsg)]).buffer(0)
        self.setores = ler_setores(setores_arq, self.epsg) if setores_arq and \
            os.path.exists(setores_arq) else []
        self.fonte_bairros = ""
        if bairros_arq and os.path.exists(bairros_arq):
            self.bairros = ler_bairros(bairros_arq, self.epsg)
            self.fonte_bairros = "arquivo"
        else:
            self.bairros, self.fonte_bairros = montar_bairros(self.setores, pontos_arq,
                                                              self.epsg, municipio)
            if self.bairros:
                frequencias_dos_bairros(self.bairros, texto_frequencia)
                if bairros_arq:
                    gravar_bairros(bairros_arq, self.bairros, self.epsg, self.fonte_bairros)
        self._relacionar()

    def _relacionar(self):
        meios = [s["geom"].interpolate(0.5, normalized=True) for s in self.segs]
        for s in self.segs:
            s["setor"], s["bairro"] = -1, -1
        if self.setores:
            arv = STRtree([x["geom"] for x in self.setores])
            for i, m in enumerate(meios):
                hit = arv.query(m, predicate="intersects")
                if len(hit):
                    self.segs[i]["setor"] = int(hit[0])
        if self.bairros:
            arv = STRtree([b["geom"] for b in self.bairros])
            for i, m in enumerate(meios):
                hit = arv.query(m, predicate="intersects")
                if len(hit):
                    self.segs[i]["bairro"] = int(hit[0])
                else:              # fora de todos (borda): o bairro mais próximo
                    j = arv.nearest(m)
                    self.segs[i]["bairro"] = int(j) if j is not None else -1
        km_setor = defaultdict(float)
        for s in self.segs:
            km_setor[s["setor"]] += s["km"]
        for s in self.segs:
            st = self.setores[s["setor"]] if s["setor"] >= 0 else None
            s["urbano"] = st["urbano"] if st else True
            s["dom_setor"] = st["dom"] if st else None
            # domicílios por km de via no setor: mede se a rua tem casas dos lados
            s["dens_setor"] = (st["dom"] / km_setor[s["setor"]]) if st and km_setor[s["setor"]]                 else None

    @property
    def quadras(self):
        """Polígonos fechados pelas vias e pelo limite do município (quadras). Os circuitos
        são feitos com quadras inteiras, então a divisa entre dois circuitos é sempre uma
        via (ou o limite do município)."""
        if getattr(self, "_quadras", None) is None:
            import shapely
            linhas = [s["geom"] for s in self.segs]
            if self.limite is not None:
                linhas.append(self.limite.boundary)
            try:
                rede = unary_union(linhas)
                pol = [p for p in shapely.get_parts(shapely.polygonize(
                    shapely.get_parts(rede))) if p.area > 1.0]
                if self.limite is not None:
                    pol = [p for p in pol if p.representative_point().within(self.limite)]
                self._quadras = pol
            except Exception:
                self._quadras = []
            self._arv_quadras = STRtree(self._quadras) if self._quadras else None
        return self._quadras

    def quadras_em(self, area):
        """Quadras (recortadas) dentro da área."""
        if not self.quadras or area is None:
            return []
        out = []
        for j in self._arv_quadras.query(area, predicate="intersects"):
            q = self._quadras[int(j)]
            if q.within(area):
                out.append(q)
                continue
            g = q.intersection(area)
            partes = [x for x in getattr(g, "geoms", [g]) if x.geom_type == "Polygon" and x.area > 1.0]
            out += partes
        return out

    def carga(self, idx):
        """População atendida por trecho (a do setor censitário, repartida pelo
        comprimento dos trechos escolhidos dentro dele). Sem IBGE: proporcional aos km."""
        idx = list(idx)
        if not self.setores:
            return {i: self.segs[i]["km"] for i in idx}
        km_setor = defaultdict(float)
        for i in idx:
            km_setor[self.segs[i]["setor"]] += self.segs[i]["km"]
        out = {}
        for i in idx:
            st = self.segs[i]["setor"]
            pop = self.setores[st]["pop"] if st >= 0 else 0.0
            out[i] = pop * self.segs[i]["km"] / km_setor[st] if km_setor[st] else 0.0
        return out

    def vizinhos_bairros(self):
        viz = defaultdict(set)
        if not self.bairros:
            return viz
        arv = STRtree([b["geom"] for b in self.bairros])
        for i, b in enumerate(self.bairros):
            for j in arv.query(b["geom"].buffer(5), predicate="intersects"):
                if int(j) != i:
                    viz[i].add(int(j))
        return viz
