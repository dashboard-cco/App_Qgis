# -*- coding: utf-8 -*-
"""Dados de base baixados da internet quando a pasta do contrato não tem:

- limite do município (IBGE, API de malhas — oficial e atualizada);
- vias (OpenStreetMap, pela Overpass API), recortadas no limite do município.

Ficam em <pasta>/App_Qgis/Base/ e só são baixados uma vez. Sem QGIS (osgeo + urllib).
"""
import json
import math
import os
import time
import unicodedata
import urllib.parse
import urllib.request

from osgeo import gdal, ogr, osr

try:
    from . import pastas as PA
except ImportError:  # testes
    import pastas as PA

UA = {"User-Agent": "QGIS_IA-plugin/2 (planos de servico)"}
IBGE_MUNICIPIOS = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios"
IBGE_MALHA = ("https://servicodados.ibge.gov.br/api/v3/malhas/municipios/{id}"
              "?formato=application/vnd.geo%2Bjson&qualidade=maxima")
OVERPASS = ["https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter"]
# vias por onde passa caminhão de coleta / varredeira (sem trilha, ciclovia, escada…)
TIPOS_VIA = ("motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|"
             "secondary_link|tertiary|tertiary_link|unclassified|residential|living_street|"
             "service|pedestrian|road")
PASSO_GRAUS = 0.25          # tamanho de cada pedaço da consulta à Overpass (~28 km)


def _sa(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower().strip()


def _baixar(url, dados=None, tentativas=3, espera=5, timeout=240):
    erro = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, data=dados, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:      # 429/504 da Overpass: espera e tenta de novo
            erro = e
            time.sleep(espera * (i + 1))
    raise ConnectionError(f"Não consegui baixar {url.split('?')[0]}: {erro}")


def _srs(epsg):
    s = osr.SpatialReference()
    s.ImportFromEPSG(int(epsg))
    s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return s


def utm_sirgas(lon, lat):
    """EPSG SIRGAS 2000 / UTM da zona do ponto (Brasil: 31978-31985 no sul)."""
    zona = int((lon + 180) // 6) + 1
    return (31960 + zona) if lat < 0 else (31954 + zona)


# ====================================================================== IBGE
def municipio_ibge(nome, uf, baixar=_baixar):
    """{"id", "nome"} do município no IBGE (pelo nome, sem acento/maiúscula)."""
    lista = json.loads(baixar(IBGE_MUNICIPIOS.format(uf=uf.strip().upper())))
    alvo = _sa(nome)
    for m in lista:
        if _sa(m["nome"]) == alvo:
            return {"id": m["id"], "nome": m["nome"]}
    for m in lista:
        if alvo and (alvo in _sa(m["nome"]) or _sa(m["nome"]) in alvo):
            return {"id": m["id"], "nome": m["nome"]}
    raise ValueError(f"Município '{nome}' não encontrado no IBGE ({uf}).")


def limite_municipio(pasta, nome, uf, baixar=_baixar):
    """Baixa o limite do município (GeoJSON do IBGE) e grava em Base/limite_<mun>.gpkg."""
    m = municipio_ibge(nome, uf, baixar)
    destino = os.path.join(PA.base(pasta, criar=True), f"limite_{_arq(m['nome'])}_{uf.upper()}.gpkg")
    if os.path.exists(destino):
        return destino
    gj = baixar(IBGE_MALHA.format(id=m["id"]))
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    tmp = destino + ".geojson"
    with open(tmp, "wb") as f:
        f.write(gj)
    try:
        with gdal.ExceptionMgr(useExceptions=True):
            gdal.VectorTranslate(destino, tmp, format="GPKG", layerName="limite",
                                 SQLStatement=None, dstSRS="EPSG:4674")
            ds = ogr.Open(destino, 1)
            lyr = ds.GetLayer(0)
            if lyr.FindFieldIndex("municipio", True) < 0:
                lyr.CreateField(ogr.FieldDefn("municipio", ogr.OFTString))
                lyr.CreateField(ogr.FieldDefn("codigo_ibge", ogr.OFTString))
            for f in lyr:
                f.SetField("municipio", m["nome"])
                f.SetField("codigo_ibge", str(m["id"]))
                lyr.SetFeature(f)
            ds = None
    finally:
        os.remove(tmp)
    return destino


def _arq(s):
    return "".join(c if c.isalnum() else "_" for c in _sa(s)).strip("_")


def geometria_limite(caminho):
    """União dos polígonos do arquivo, em SIRGAS 2000 geográfico (EPSG:4674)."""
    ds = gdal.OpenEx(caminho, gdal.OF_VECTOR)
    lyr = ds.GetLayer(0)
    uniao = None
    for f in lyr:
        g = f.GetGeometryRef()
        if g is not None:
            g = g.Clone()
            uniao = g if uniao is None else uniao.Union(g)
    s = lyr.GetSpatialRef()
    if s is not None and uniao is not None:
        s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        uniao.TransformTo(_srs(4674))
    return uniao


# ====================================================================== OpenStreetMap
def _pedacos(env, passo=PASSO_GRAUS):
    x0, x1, y0, y1 = env
    nx, ny = max(1, math.ceil((x1 - x0) / passo)), max(1, math.ceil((y1 - y0) / passo))
    for i in range(nx):
        for j in range(ny):
            yield (x0 + i * passo, y0 + j * passo,
                   min(x1, x0 + (i + 1) * passo), min(y1, y0 + (j + 1) * passo))


def _consulta(b):
    s, w, n, e = b[1], b[0], b[3], b[2]
    return (f'[out:json][timeout:180];way["highway"~"^({TIPOS_VIA})$"]'
            f'({s:.6f},{w:.6f},{n:.6f},{e:.6f});out geom tags;')


def vias_osm(pasta, limite, epsg=None, nome="vias_osm", baixar=_baixar, progresso=None,
             cancelado=None):
    """Baixa do OpenStreetMap as vias dentro do limite (arquivo de polígono) e grava em
    Base/<nome>.gpkg, camada 'vias_osm', no EPSG pedido (padrão: UTM SIRGAS da região).
    Devolve {"arquivo", "vias", "km"}."""
    destino = os.path.join(PA.base(pasta, criar=True), f"{nome}.gpkg")
    if os.path.exists(destino):
        if not vias_tratadas(destino):        # baixado antes do tratamento existir
            tr = tratar_vias(destino, progresso)
            return {"arquivo": destino, "vias": tr["trechos"], "km": tr["km"],
                    "ja_existia": True, "tratamento": tr}
        ds = ogr.Open(destino)
        lyr = ds.GetLayer(0)
        km = sum(f.GetGeometryRef().Length() for f in lyr if f.GetGeometryRef()) / 1000
        return {"arquivo": destino, "vias": lyr.GetFeatureCount(), "km": round(km, 1),
                "ja_existia": True}
    area = geometria_limite(limite)
    if area is None:
        raise ValueError("O limite não tem polígono.")
    env = area.GetEnvelope()
    c = area.Centroid()
    epsg = epsg or utm_sirgas(c.GetX(), c.GetY())
    ct = osr.CoordinateTransformation(_srs(4674), _srs(epsg))
    pedacos = list(_pedacos(env))
    vistos = set()
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    tmp = destino + ".tmp.gpkg"
    if os.path.exists(tmp):
        os.remove(tmp)
    drv = ogr.GetDriverByName("GPKG")
    ds = drv.CreateDataSource(tmp)
    lyr = ds.CreateLayer("vias_osm", _srs(epsg), ogr.wkbLineString)
    for nome_c, tipo in (("osm_id", ogr.OFTInteger64), ("highway", ogr.OFTString),
                         ("nome", ogr.OFTString), ("mao_unica", ogr.OFTInteger)):
        lyr.CreateField(ogr.FieldDefn(nome_c, tipo))
    total_m = 0.0
    lyr.StartTransaction()
    for k, b in enumerate(pedacos):
        if cancelado and cancelado():
            ds = None
            os.remove(tmp)
            raise InterruptedError("Download cancelado.")
        if progresso:
            progresso(f"Baixando vias do OpenStreetMap ({k + 1}/{len(pedacos)})…", k, len(pedacos))
        caixa = ogr.CreateGeometryFromWkt(
            f"POLYGON(({b[0]} {b[1]},{b[2]} {b[1]},{b[2]} {b[3]},{b[0]} {b[3]},{b[0]} {b[1]}))")
        if not caixa.Intersects(area):
            continue
        resp = None
        for url in OVERPASS:
            try:
                resp = json.loads(baixar(url, urllib.parse.urlencode(
                    {"data": _consulta(b)}).encode()))
                break
            except Exception:
                continue
        if resp is None:
            ds = None
            os.remove(tmp)
            raise ConnectionError("O OpenStreetMap (Overpass) não respondeu. Tente mais tarde.")
        for el in resp.get("elements", []):
            if el.get("type") != "way" or el["id"] in vistos or not el.get("geometry"):
                continue
            vistos.add(el["id"])
            g = ogr.Geometry(ogr.wkbLineString)
            for pt in el["geometry"]:
                g.AddPoint_2D(pt["lon"], pt["lat"])
            g.AssignSpatialReference(_srs(4674))
            if not g.Intersects(area):
                continue
            g = g.Intersection(area)
            if g is None or g.IsEmpty():
                continue
            g.Transform(ct)
            tags = el.get("tags") or {}
            partes = [g] if g.GetGeometryType() in (ogr.wkbLineString, ogr.wkbLineString25D) \
                else [g.GetGeometryRef(i).Clone() for i in range(g.GetGeometryCount())]
            for p in partes:
                if p.GetGeometryType() not in (ogr.wkbLineString, ogr.wkbLineString25D):
                    continue
                f = ogr.Feature(lyr.GetLayerDefn())
                f.SetGeometry(p)
                f.SetField("osm_id", el["id"])
                f.SetField("highway", tags.get("highway", ""))
                f.SetField("nome", tags.get("name", ""))
                f.SetField("mao_unica", 1 if tags.get("oneway") in ("yes", "1", "-1") else 0)
                lyr.CreateFeature(f)
                total_m += p.Length()
    lyr.CommitTransaction()
    ds = None
    os.replace(tmp, destino)
    tr = tratar_vias(destino)
    return {"arquivo": destino, "vias": tr["trechos"], "km": tr["km"], "epsg": epsg,
            "tratamento": tr}


# ---------------------------------------------------------------------- tratamento das vias
TOL_NO = 0.5                # m: ponta de via a menos disso de outra via = encontro (T)
PRIORIDADE_VIA = {"motorway": 0, "trunk": 1, "primary": 2, "secondary": 3, "tertiary": 4,
                  "unclassified": 5, "residential": 6, "living_street": 7, "road": 8,
                  "pedestrian": 9, "service": 10}


def _ch(c, casas=1):
    return (round(c[0], casas), round(c[1], casas))


def vias_tratadas(caminho):
    """True se o arquivo de vias já passou por tratar_vias (tem o campo 'trecho')."""
    ds = ogr.Open(caminho)
    if ds is None:
        return False
    lyr = ds.GetLayer(0)
    return lyr.GetLayerDefn().GetFieldIndex("trecho") >= 0


def tratar_vias(caminho, progresso=None):
    """Limpa as vias baixadas do OSM para evitar erro na criação dos circuitos:
    1. tira as linhas duplicadas (mesma geometria, em qualquer sentido);
    2. quebra as linhas em todos os encontros (nós em comum e pontas que encostam no meio
       de outra via — "T"); viadutos/túneis que só se cruzam sem nó em comum NÃO são
       quebrados (não há ligação entre eles);
    3. tira de novo os trechos repetidos (vias sobrepostas viram trechos iguais) e os
       pedaços com menos de 0,5 m.
    Regrava o arquivo com um trecho por linha (campo 'trecho'). Devolve as contagens."""
    from shapely import wkb as _wkb
    from shapely.geometry import LineString, Point
    from shapely.ops import substring
    from shapely.strtree import STRtree

    if progresso:
        progresso("Tratando as vias (duplicadas e encontros)…")
    ds = ogr.Open(caminho)
    lyr = ds.GetLayer(0)
    srs = lyr.GetSpatialRef().Clone() if lyr.GetSpatialRef() else None
    nome_cam = lyr.GetName()
    defn = lyr.GetLayerDefn()
    campos = [(defn.GetFieldDefn(i).GetName(), defn.GetFieldDefn(i).GetType())
              for i in range(defn.GetFieldCount()) if defn.GetFieldDefn(i).GetName() != "trecho"]
    linhas = []
    for f in lyr:
        g = f.GetGeometryRef()
        if g is None or g.IsEmpty():
            continue
        sg = _wkb.loads(bytes(g.ExportToIsoWkb()))
        at = {n: f.GetField(n) for n, _ in campos}
        for ln in getattr(sg, "geoms", [sg]):
            if ln.geom_type != "LineString":
                continue
            cs = [c[:2] for c in ln.coords]
            # tira vértices repetidos seguidos
            cs = [c for k, c in enumerate(cs) if k == 0 or _ch(c) != _ch(cs[k - 1])]
            if len(cs) >= 2:
                linhas.append((LineString(cs), at))
    ds = None
    n_orig = len(linhas)

    def ordem(at):
        return (PRIORIDADE_VIA.get(at.get("highway") or "", 20), 0 if at.get("nome") else 1)

    def assinatura(cs):
        a = tuple(_ch(c) for c in cs)
        return min(a, a[::-1])

    # 1) duplicadas inteiras (fica a de classe mais alta / com nome)
    linhas.sort(key=lambda x: ordem(x[1]))
    vistos, unicas = set(), []
    for ln, at in linhas:
        k = assinatura(ln.coords)
        if k in vistos:
            continue
        vistos.add(k)
        unicas.append((ln, at))
    dup1 = n_orig - len(unicas)

    # 2) pontos de quebra: vértices usados por mais de uma via (ou ponta) + pontas em "T"
    cont = {}
    for ln, _ in unicas:
        cs = ln.coords
        for i, c in enumerate(cs):
            k = _ch(c)
            cont[k] = cont.get(k, 0) + (2 if i in (0, len(cs) - 1) else 1)
    geoms = [ln for ln, _ in unicas]
    arv = STRtree(geoms)
    cortes_t = {}                  # índice da linha → [distâncias ao longo dela]
    for i, ln in enumerate(geoms):
        for c in (ln.coords[0], ln.coords[-1]):
            p = Point(c)
            for j in arv.query(p.buffer(TOL_NO), predicate="intersects"):
                j = int(j)
                if j == i:
                    continue
                d = geoms[j].project(p)
                if TOL_NO < d < geoms[j].length - TOL_NO:
                    q = geoms[j].interpolate(d)
                    if _ch((q.x, q.y)) not in cont or cont[_ch((q.x, q.y))] < 2:
                        cortes_t.setdefault(j, []).append(d)
    trechos = []
    for i, (ln, at) in enumerate(unicas):
        cs = list(ln.coords)
        dist = [0.0]
        for a, b in zip(cs[:-1], cs[1:]):
            dist.append(dist[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        pos = {dist[k] for k in range(1, len(cs) - 1) if cont[_ch(cs[k])] >= 2}
        pos |= set(cortes_t.get(i, []))
        pos = sorted(x for x in pos if TOL_NO < x < ln.length - TOL_NO)
        marcos = [0.0] + pos + [ln.length]
        for a, b in zip(marcos[:-1], marcos[1:]):
            if b - a < TOL_NO:
                continue
            g = substring(ln, a, b) if (a, b) != (0.0, ln.length) else ln
            if g.geom_type == "LineString" and g.length >= TOL_NO:
                trechos.append((g, at))

    # 3) trechos repetidos depois da quebra (vias sobrepostas)
    vistos, finais = set(), []
    for g, at in trechos:
        k = assinatura(g.coords)
        if k in vistos:
            continue
        vistos.add(k)
        finais.append((g, at))
    dup2 = len(trechos) - len(finais)

    tmp = caminho + ".trat.gpkg"
    if os.path.exists(tmp):
        os.remove(tmp)
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(tmp)
    out = ds.CreateLayer(nome_cam, srs, ogr.wkbLineString)
    for n, t in campos:
        out.CreateField(ogr.FieldDefn(n, t))
    out.CreateField(ogr.FieldDefn("trecho", ogr.OFTInteger))
    out.StartTransaction()
    total = 0.0
    for k, (g, at) in enumerate(finais, start=1):
        f = ogr.Feature(out.GetLayerDefn())
        f.SetGeometry(ogr.CreateGeometryFromWkb(g.wkb))
        for n, _ in campos:
            if at.get(n) is not None:
                f.SetField(n, at[n])
        f.SetField("trecho", k)
        out.CreateFeature(f)
        total += g.length
    out.CommitTransaction()
    ds = None
    try:
        os.replace(tmp, caminho)
    except PermissionError:          # aberto no QGIS: regrava dentro do próprio arquivo
        ds = ogr.Open(caminho, 1)
        lyr = ds.GetLayerByName(nome_cam) or ds.GetLayer(0)
        if lyr.GetLayerDefn().GetFieldIndex("trecho") < 0:
            lyr.CreateField(ogr.FieldDefn("trecho", ogr.OFTInteger))
        lyr.StartTransaction()
        for fid in [f.GetFID() for f in lyr]:
            lyr.DeleteFeature(fid)
        for k, (g, at) in enumerate(finais, start=1):
            f = ogr.Feature(lyr.GetLayerDefn())
            f.SetGeometry(ogr.CreateGeometryFromWkb(g.wkb))
            for n, _ in campos:
                if at.get(n) is not None:
                    f.SetField(n, at[n])
            f.SetField("trecho", k)
            lyr.CreateFeature(f)
        lyr.CommitTransaction()
        ds = None
        os.remove(tmp)
    return {"linhas_originais": n_orig, "duplicadas": dup1 + dup2, "trechos": len(finais),
            "quebras_t": sum(len(v) for v in cortes_t.values()), "km": round(total / 1000, 1)}


# ====================================================================== IBGE: setores (população)
IBGE_SETORES = ("/vsicurl/https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/"
                "Agregados_por_Setores_Censitarios/malha_com_atributos/setores/gpkg/UF/"
                "{uf}/{uf}_setores_CD2022.gpkg")


def setores_ibge(pasta, limite, epsg=None, fonte=None):
    """Setores censitários do Censo 2022 do município (população v0001 e domicílios v0002,
    situação urbana/rural e bairro do IBGE, quando a prefeitura informou), lidos direto do
    servidor do IBGE (só o pedaço do município, ~5 s). Grava Base/setores_ibge.gpkg."""
    destino = os.path.join(PA.base(pasta, criar=True), "setores_ibge.gpkg")
    if os.path.exists(destino):
        return destino
    ds = ogr.Open(limite)
    lyr = ds.GetLayer(0)
    f = lyr.GetNextFeature()
    cod = None
    if f is not None and lyr.GetLayerDefn().GetFieldIndex("codigo_ibge") >= 0:
        cod = f.GetField("codigo_ibge")
    ds = None
    area = geometria_limite(limite)
    if area is None:
        raise ValueError("O limite não tem polígono.")
    x0, x1, y0, y1 = area.GetEnvelope()
    c = area.Centroid()
    epsg = epsg or utm_sirgas(c.GetX(), c.GetY())
    if fonte is None:
        uf = _uf_do_codigo(cod)
        if not uf:
            raise ValueError("Sem o código IBGE do município no limite.")
        fonte = IBGE_SETORES.format(uf=uf)
    tmp = destino + ".tmp.gpkg"
    if os.path.exists(tmp):
        os.remove(tmp)
    antes = gdal.GetConfigOption("GDAL_HTTP_USERAGENT")
    gdal.SetConfigOption("GDAL_HTTP_USERAGENT", UA["User-Agent"])
    try:
        with gdal.ExceptionMgr(useExceptions=True):
            src = gdal.OpenEx(fonte, gdal.OF_VECTOR)
            nome_lyr = src.GetLayer(0).GetName()
            campos = [src.GetLayer(0).GetLayerDefn().GetFieldDefn(i).GetName()
                      for i in range(src.GetLayer(0).GetLayerDefn().GetFieldCount())]
            sel = [c_ for c_ in ("CD_SETOR", "CD_SIT", "NM_BAIRRO", "v0001", "v0002")
                   if c_ in campos]
            where = f"CD_MUN = '{cod}'" if cod and "CD_MUN" in campos else None
            gdal.VectorTranslate(tmp, src, format="GPKG", layers=[nome_lyr],
                                 spatFilter=(x0, y0, x1, y1), where=where,
                                 selectFields=sel, layerName="setores",
                                 dstSRS=f"EPSG:{epsg}", geometryType="PROMOTE_TO_MULTI")
            src = None
    finally:
        gdal.SetConfigOption("GDAL_HTTP_USERAGENT", antes)
    os.replace(tmp, destino)
    return destino


_UF_COD = {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
           "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
           "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
           "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF"}


def _uf_do_codigo(cod):
    return _UF_COD.get(str(cod or "")[:2])


# ====================================================================== OSM: bairros
def _consulta_bairros(b):
    s, w, n, e = b[1], b[0], b[3], b[2]
    caixa = f"({s:.6f},{w:.6f},{n:.6f},{e:.6f})"
    return (f'[out:json][timeout:120];(node["place"~"^(suburb|neighbourhood|quarter)$"]{caixa};'
            f'way["place"~"^(suburb|neighbourhood|quarter)$"]{caixa};'
            f'relation["place"~"^(suburb|neighbourhood|quarter)$"]{caixa};'
            f'relation["boundary"="administrative"]["admin_level"="10"]{caixa};);'
            'out tags center;')


def bairros_osm(pasta, limite, epsg=None, baixar=_baixar):
    """Pontos dos bairros no OpenStreetMap (place=suburb/neighbourhood/quarter), dentro do
    limite. Grava Base/bairros_osm.gpkg (nome, tipo). Devolve o caminho (ou None)."""
    destino = os.path.join(PA.base(pasta, criar=True), "bairros_osm.gpkg")
    if os.path.exists(destino):
        return destino
    area = geometria_limite(limite)
    env = area.GetEnvelope()
    c = area.Centroid()
    epsg = epsg or utm_sirgas(c.GetX(), c.GetY())
    ct = osr.CoordinateTransformation(_srs(4674), _srs(epsg))
    resp = None
    for url in OVERPASS:
        try:
            resp = json.loads(baixar(url, urllib.parse.urlencode(
                {"data": _consulta_bairros(env)}).encode()))
            break
        except Exception:
            continue
    if resp is None:
        raise ConnectionError("O OpenStreetMap (Overpass) não respondeu. Tente mais tarde.")
    pts = []
    for el in resp.get("elements", []):
        t = el.get("tags") or {}
        nome = t.get("name")
        if el["type"] == "node":
            lon, lat = el.get("lon"), el.get("lat")
        else:
            lon, lat = (el.get("center") or {}).get("lon"), (el.get("center") or {}).get("lat")
        if not nome or lon is None:
            continue
        g = ogr.Geometry(ogr.wkbPoint)
        g.AddPoint_2D(lon, lat)
        if not g.Within(area):
            continue
        g.Transform(ct)
        pts.append((nome, t.get("place") or f"admin_level={t.get('admin_level')}", g))
    if not pts:
        return None
    tmp = destino + ".tmp.gpkg"
    if os.path.exists(tmp):
        os.remove(tmp)
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(tmp)
    lyr = ds.CreateLayer("bairros_osm", _srs(epsg), ogr.wkbPoint)
    lyr.CreateField(ogr.FieldDefn("nome", ogr.OFTString))
    lyr.CreateField(ogr.FieldDefn("tipo", ogr.OFTString))
    lyr.StartTransaction()
    for nome, tipo, g in pts:
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetGeometry(g)
        f.SetField("nome", nome)
        f.SetField("tipo", tipo)
        lyr.CreateFeature(f)
    lyr.CommitTransaction()
    ds = None
    os.replace(tmp, destino)
    return destino
