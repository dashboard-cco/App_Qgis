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
    n = lyr.GetFeatureCount()
    ds = None
    os.replace(tmp, destino)
    return {"arquivo": destino, "vias": n, "km": round(total_m / 1000, 1), "epsg": epsg}
