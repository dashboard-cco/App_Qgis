# -*- coding: utf-8 -*-
"""Estrutura de arquivos de plano (File Geodatabase, GeoPackage, shapefiles) com GDAL/OGR.

- ler(caminho): camadas, campos (nome, apelido, tipo, tamanho, domínio) e domínios.
- completar_perfil(perfil, estrutura): usa um modelo do contratante (ou um plano já aceito)
  para pôr no perfil os nomes técnicos exatos de camadas e campos, tamanhos e domínios.
- completar_plano(perfil, caminho, servicos): no plano EXISTENTE, cria só as camadas e os
  campos que faltam (nada é apagado nem renomeado; antes faz uma cópia de segurança) e põe o
  valor padrão do perfil (ex.: ciclo = 0) nos registros vazios.

Sem QGIS (só osgeo): pode ser testado sozinho.
"""
import copy
import datetime
import os
import re
import shutil

from .checklist import norm
from .perfil import codigo_valor

# tabelas internas do ArcGIS/GDAL que não são camadas do plano
_SISTEMA = re.compile(r"^(T_\d+_|GDB_|Toolbox$|layer_styles$|gpkg_|rtree_|sqlite_)", re.IGNORECASE)
_CAMPOS_SISTEMA = {"shape_length", "shape_area", "objectid", "fid", "globalid", "shape_leng"}

_GEOM = {"Point": "ponto", "Line": "linha", "Polygon": "poligono"}
_TIPO_OGR = {"String": "texto", "Integer": "inteiro", "Integer64": "inteiro", "Real": "decimal",
             "Date": "data", "DateTime": "data_hora", "Time": "texto"}
_DRIVER_EXT = {".gdb": "OpenFileGDB", ".gpkg": "GPKG", ".shp": "ESRI Shapefile",
               ".geojson": "GeoJSON"}


def _ogr():
    from osgeo import gdal, ogr, osr
    return gdal, ogr, osr


def com_excecoes(fn):
    """Liga as exceções do GDAL só durante a função (sem mudar o modo global do QGIS)."""
    import functools

    @functools.wraps(fn)
    def envolta(*a, **k):
        from osgeo import gdal
        with gdal.ExceptionMgr(useExceptions=True):
            return fn(*a, **k)
    return envolta


def geometria_ogr(tipo_geom):
    _, ogr, _ = _ogr()
    plano = ogr.GT_Flatten(tipo_geom)
    if plano in (ogr.wkbPoint, ogr.wkbMultiPoint):
        return "ponto"
    if plano in (ogr.wkbLineString, ogr.wkbMultiLineString):
        return "linha"
    if plano in (ogr.wkbPolygon, ogr.wkbMultiPolygon):
        return "poligono"
    return "tabela"


def abrir(caminho, gravar=False):
    gdal, ogr, _ = _ogr()
    flags = gdal.OF_VECTOR | (gdal.OF_UPDATE if gravar else 0)
    return gdal.OpenEx(caminho, flags)


@com_excecoes
def ler(caminho):
    """Estrutura do arquivo: {"caminho", "formato", "camadas": [...], "dominios": {...}}."""
    _, ogr, _ = _ogr()
    ds = abrir(caminho)
    if ds is None:
        raise ValueError(f"Não consegui abrir {caminho}")
    dominios = {}
    for nome in (ds.GetFieldDomainNames() or []) if hasattr(ds, "GetFieldDomainNames") else []:
        d = ds.GetFieldDomain(nome)
        if d is not None and d.GetDomainType() == ogr.OFDT_CODED:
            dominios[nome] = {str(k): (v if v is not None else str(k))
                              for k, v in d.GetEnumeration().items()}
    camadas = []
    for i in range(ds.GetLayerCount()):
        lyr = ds.GetLayerByIndex(i)
        if _SISTEMA.match(lyr.GetName()):
            continue
        defn = lyr.GetLayerDefn()
        srs = lyr.GetSpatialRef()
        epsg = None
        if srs is not None:
            srs.AutoIdentifyEPSG()
            cod = srs.GetAuthorityCode(None)
            epsg = int(cod) if cod and cod.isdigit() else None
        campos = []
        for j in range(defn.GetFieldCount()):
            fd = defn.GetFieldDefn(j)
            if fd.GetName().lower() in _CAMPOS_SISTEMA:
                continue
            campos.append({"nome": fd.GetName(), "alias": fd.GetAlternativeName() or "",
                           "tipo": _TIPO_OGR.get(fd.GetTypeName(), "texto"),
                           "tamanho": fd.GetWidth() if fd.GetType() == ogr.OFTString else 0,
                           "dominio": fd.GetDomainName() or "",
                           "anulavel": bool(fd.IsNullable())})
        camadas.append({"nome": lyr.GetName(), "geometria": geometria_ogr(lyr.GetGeomType()),
                        "epsg": epsg, "feicoes": lyr.GetFeatureCount(), "campos": campos})
    ext = os.path.splitext(caminho.rstrip("/\\"))[1].lower()
    return {"caminho": os.path.normpath(caminho), "formato": _DRIVER_EXT.get(ext, ds.GetDriver().ShortName),
            "camadas": camadas, "dominios": dominios}


# ------------------------------------------------------------------ perfil a partir de modelo
def _chaves_campo(f):
    """Nomes pelos quais um campo pode ser reconhecido (nome técnico, apelido, descrição)."""
    out = {norm(f.get("nome")), norm(f.get("alias")), norm(f.get("descricao"))}
    return {c for c in out if c}


_VAZIAS = {"de", "da", "do", "das", "dos", "e", "ou", "a", "o"}


def _palavras(s):
    return [w for w in s.split("_") if w and w not in _VAZIAS]


def _parecido(a, b):
    """Dois rótulos normalizados são o mesmo campo? ('codigo_ra' ~ 'codigo_regiao_administrativa',
    'horario_inicio' ~ 'horario_de_inicio')."""
    if a == b:
        return True
    la, lb = _palavras(a), _palavras(b)
    pa, pb = set(la), set(lb)
    if not pa or not pb:
        return False
    if pa == pb:
        return True
    so_a = [w for w in la if w not in pb]
    so_b = [w for w in lb if w not in pa]
    if pa & pb and len(so_a) == 1 and len(so_b) >= 2 and so_a[0] == "".join(w[0] for w in so_b):
        return True
    if pa & pb and len(so_b) == 1 and len(so_a) >= 2 and so_b[0] == "".join(w[0] for w in so_a):
        return True
    return len(pa & pb) / len(pa | pb) >= 0.66


def _acha_campo(campo_perfil, campos_modelo, usados):
    cp = _chaves_campo(campo_perfil)
    for exato in (True, False):
        for f in campos_modelo:
            if f["nome"] in usados:
                continue
            cm = _chaves_campo(f)
            if exato and cp & cm:
                return f
            if not exato and any(_parecido(a, b) for a in cp for b in cm):
                return f
    return None


def _pontuacao(cam_perfil, cam_modelo):
    if cam_perfil["geometria"] != cam_modelo["geometria"]:
        return 0.0
    if norm(cam_perfil["nome"]) == norm(cam_modelo["nome"]):
        return 2.0
    usados, acertos = set(), 0
    for f in cam_perfil.get("campos", []):
        m = _acha_campo(f, cam_modelo["campos"], usados)
        if m:
            usados.add(m["nome"])
            acertos += 1
    if acertos < 2 and min(len(cam_perfil.get("campos", [])), len(cam_modelo["campos"])) > 1:
        return 0.0
    menor = max(min(len(cam_perfil.get("campos", [])), len(cam_modelo["campos"])), 1)
    maior = max(len(cam_perfil.get("campos", [])), len(cam_modelo["campos"]), 1)
    # parte dos campos achada + desempate pela semelhança de tamanho
    nota = acertos / menor + 0.25 * acertos / maior
    # nome da camada do modelo citado no nome do edital ('st_quantificacao' ~ 'POLILINHA DE QUANTIFICAÇÃO')
    edital = set(_palavras(norm(cam_perfil["nome"])))
    if any(len(w) >= 5 and w in edital for w in _palavras(norm(cam_modelo["nome"]))):
        nota += 0.5
    return nota


def completar_perfil(p, estrutura, servicos=None, minimo=0.5):
    """Devolve (perfil_novo, relatorio). Cada camada do modelo substitui a camada do perfil
    mais parecida (mesma geometria e campos), que passa a ter os nomes técnicos do modelo."""
    p = copy.deepcopy(p)
    doms = estrutura.get("dominios", {})
    rel = {"modelo": estrutura["caminho"], "ligadas": [], "novas": [], "campos_so_no_perfil": {}}
    nome_modelo = os.path.basename(estrutura["caminho"].rstrip("/\\"))
    modelos = [cm for cm in estrutura["camadas"]
               if not (cm["geometria"] == "tabela" and not cm["campos"])]
    # atribuição global: os pares mais parecidos primeiro (camadas dos serviços do modelo valem mais)
    pares = []
    for j, cm in enumerate(modelos):
        for i, cp in enumerate(p["camadas"]):
            nota = _pontuacao(cp, cm)
            if nota < minimo:
                continue
            if servicos and set(cp.get("servicos") or []) & set(servicos):
                nota += 1.0
            pares.append((nota, i, j))
    destino, usadas = {}, set()
    for nota, i, j in sorted(pares, reverse=True):
        if j not in destino and i not in usadas:
            destino[j] = i
            usadas.add(i)

    for j, cm in enumerate(modelos):
        alvo = destino.get(j)
        campos, usados = [], set()
        if alvo is not None:
            antiga = p["camadas"][alvo]
            por_modelo = {}
            for f in antiga["campos"]:
                m = _acha_campo(f, cm["campos"], usados)
                if m:
                    usados.add(m["nome"])
                    por_modelo[m["nome"]] = f
                else:
                    rel["campos_so_no_perfil"].setdefault(cm["nome"], []).append(f["nome"])
        else:
            antiga, por_modelo = None, {}
        for fm in cm["campos"]:
            fp = por_modelo.get(fm["nome"], {})
            valores = fp.get("valores_permitidos") or []
            if fm["dominio"] in doms:
                valores = [f"{k} - {v}" if str(k) != str(v) else str(k)
                           for k, v in doms[fm["dominio"]].items()]
            campos.append({"nome": fm["nome"], "tipo": fm["tipo"], "tamanho": fm["tamanho"],
                           # campo só do modelo (o edital não cita): não é obrigatório preencher
                           "obrigatorio": fp.get("obrigatorio", False),
                           "descricao": fp.get("descricao") or fp.get("nome") or fm["alias"],
                           "valores_permitidos": valores,
                           "valor_padrao": fp.get("valor_padrao", "")})
        # campos que o edital pede e o modelo não tem: ficam, com nome técnico a confirmar
        for f in (antiga or {}).get("campos", []):
            if f in por_modelo.values():
                continue
            extra = dict(f, nome=norm(f["nome"]), _nome_a_confirmar=True)
            extra.setdefault("descricao", f["nome"])
            if not extra.get("descricao"):
                extra["descricao"] = f["nome"]
            extra.setdefault("valor_padrao", "")
            campos.append(extra)
        nova = {"nome": cm["nome"], "descricao": (antiga or {}).get("descricao", "") or
                f"Camada do modelo {nome_modelo}",
                "geometria": cm["geometria"],
                "servicos": (antiga or {}).get("servicos") or list(servicos or []),
                "campos": campos,
                "fonte": (antiga or {}).get("fonte") or {"documento": nome_modelo, "paginas": ""},
                "_modelo": nome_modelo}
        if antiga is not None:
            nova["_nome_no_edital"] = antiga["nome"]
            p["camadas"][alvo] = nova
            rel["ligadas"].append({"edital": antiga["nome"], "modelo": cm["nome"],
                                   "campos": len(campos)})
        else:
            p["camadas"].append(nova)
            rel["novas"].append(cm["nome"])
    if not p["contrato"].get("sistema_referencia"):
        epsgs = {c["epsg"] for c in estrutura["camadas"] if c["epsg"]}
        if len(epsgs) == 1:
            p["contrato"]["sistema_referencia"] = f"EPSG:{epsgs.pop()}"
    return p, rel


# ------------------------------------------------------------------ plano existente
def servicos_do_arquivo(p, caminho):
    """Serviços do perfil cuja sigla abre o nome do arquivo (CC01.gdb -> P1)."""
    base = norm(os.path.splitext(os.path.basename(caminho.rstrip("/\\")))[0])
    achados = []
    for s in p.get("servicos", []):
        for sig in re.split(r"[/,;\s]+", s.get("sigla") or ""):
            if sig and base.startswith(norm(sig)):
                achados.append(s["codigo"])
                break
    return achados


def camadas_exigidas(p, servicos):
    """Camadas do perfil para estes serviços (sem repetir nome)."""
    out, vistos = [], set()
    for c in p.get("camadas", []):
        if servicos and c.get("servicos") and not set(c["servicos"]) & set(servicos):
            continue
        if c["geometria"] == "tabela" and c["nome"].lower().endswith((".xlsx", ".xls", ".csv")):
            continue
        if norm(c["nome"]) in vistos:
            continue
        vistos.add(norm(c["nome"]))
        out.append(c)
    return out


def _tipo_campo_ogr(tipo):
    _, ogr, _ = _ogr()
    return {"texto": ogr.OFTString, "inteiro": ogr.OFTInteger, "decimal": ogr.OFTReal,
            "data": ogr.OFTDate, "data_hora": ogr.OFTDateTime,
            "booleano": ogr.OFTInteger}.get(tipo, ogr.OFTString)


def _geom_ogr(geometria):
    _, ogr, _ = _ogr()
    return {"ponto": ogr.wkbPoint, "linha": ogr.wkbMultiLineString,
            "poligono": ogr.wkbMultiPolygon}.get(geometria, ogr.wkbNone)


def copia_seguranca(caminho):
    """Copia o arquivo/pasta do plano para <nome>_backup_AAAAMMDD_HHMMSS."""
    base, ext = os.path.splitext(caminho.rstrip("/\\"))
    destino = f"{base}_backup_{datetime.datetime.now():%Y%m%d_%H%M%S}{ext}"
    if os.path.isdir(caminho):
        shutil.copytree(caminho, destino)
    else:
        shutil.copy2(caminho, destino)
    return destino


@com_excecoes
def o_que_falta(p, caminho, servicos=None):
    """Sem gravar: {"camadas": [nomes], "campos": {camada: [nomes]}}."""
    servicos = servicos if servicos is not None else servicos_do_arquivo(p, caminho)
    est = ler(caminho)
    existentes = {norm(c["nome"]): c for c in est["camadas"]}
    falta = {"camadas": [], "campos": {}, "servicos": servicos}
    for cam in camadas_exigidas(p, servicos):
        e = existentes.get(norm(cam["nome"]))
        if e is None:
            falta["camadas"].append(cam["nome"])
            continue
        tem = {norm(f["nome"]) for f in e["campos"]}
        faltam = [f["nome"] for f in cam["campos"] if norm(f["nome"]) not in tem]
        if faltam:
            falta["campos"][e["nome"]] = faltam
    falta["vazios"] = vazios_com_padrao(p, caminho, servicos)
    return falta


def _campos_com_padrao(p, servicos):
    """{nome norm da camada: [(campo do perfil, valor)]} dos campos com valor_padrao."""
    out = {}
    for cam in camadas_exigidas(p, servicos):
        cs = [(f, f["valor_padrao"]) for f in cam["campos"]
              if str(f.get("valor_padrao") or "").strip() != ""]
        if cs:
            out[norm(cam["nome"])] = cs
    return out


def _valor_padrao(f, ogr_tipo=None):
    """Texto do perfil -> valor do tipo do campo ('0' -> 0 em inteiro)."""
    v = codigo_valor(str(f["valor_padrao"]).strip())
    _, ogr, _ = _ogr()
    tipo = ogr_tipo if ogr_tipo is not None else _tipo_campo_ogr(f["tipo"])
    try:
        if tipo in (ogr.OFTInteger, ogr.OFTInteger64):
            return int(float(v.replace(",", ".")))
        if tipo == ogr.OFTReal:
            return float(v.replace(",", "."))
    except ValueError:
        return None
    return v


def _vazio(feat, idx, tipo, ogr):
    if not feat.IsFieldSetAndNotNull(idx):
        return True
    return tipo == ogr.OFTString and not str(feat.GetField(idx) or "").strip()


def _percorrer_vazios(ds, p, servicos, gravar=False):
    """Conta (e, se gravar, preenche) os registros vazios dos campos com valor padrão.
    Devolve {camada: {campo: {"valor": v, "registros": n}}}."""
    _, ogr, _ = _ogr()
    alvo = _campos_com_padrao(p, servicos)
    out = {}
    for i in range(ds.GetLayerCount()):
        lyr = ds.GetLayerByIndex(i)
        cs = alvo.get(norm(lyr.GetName()))
        if not cs:
            continue
        defn = lyr.GetLayerDefn()
        nomes = {norm(defn.GetFieldDefn(j).GetName()): j for j in range(defn.GetFieldCount())}
        campos = []
        for f, _v in cs:
            j = nomes.get(norm(f["nome"]))
            if j is None:
                continue
            tipo = defn.GetFieldDefn(j).GetType()
            val = _valor_padrao(f, tipo)
            if val is not None:
                campos.append((defn.GetFieldDefn(j).GetName(), j, tipo, val))
        if not campos:
            continue
        cont = {c[0]: 0 for c in campos}
        lyr.ResetReading()
        mudadas = []
        for feat in lyr:
            mudou = False
            for nome, j, tipo, val in campos:
                if _vazio(feat, j, tipo, ogr):
                    cont[nome] += 1
                    if gravar:
                        feat.SetField(j, val)
                        mudou = True
            if mudou:
                mudadas.append(feat)
        if gravar and mudadas:
            lyr.StartTransaction() if lyr.TestCapability(ogr.OLCTransactions) else None
            for feat in mudadas:
                lyr.SetFeature(feat)
            lyr.CommitTransaction() if lyr.TestCapability(ogr.OLCTransactions) else None
        res = {nome: {"valor": val, "registros": cont[nome]}
               for nome, _j, _t, val in campos if cont[nome]}
        if res:
            out[lyr.GetName()] = res
    return out


@com_excecoes
def vazios_com_padrao(p, caminho, servicos=None):
    """Sem gravar: registros vazios em campos que têm valor padrão no perfil."""
    servicos = servicos if servicos is not None else servicos_do_arquivo(p, caminho)
    if not _campos_com_padrao(p, servicos):
        return {}
    ds = abrir(caminho)
    if ds is None:
        raise ValueError(f"Não consegui abrir {caminho}")
    return _percorrer_vazios(ds, p, servicos)


@com_excecoes
def completar_plano(p, caminho, servicos=None, backup=True):
    """Cria no plano existente as camadas e campos que faltam. Devolve o relatório."""
    gdal, ogr, osr = _ogr()
    falta = o_que_falta(p, caminho, servicos)
    rel = {"plano": caminho, "servicos": falta["servicos"], "backup": None,
           "camadas_criadas": [], "campos_criados": {}, "preenchidos": {}, "avisos": []}
    if not falta["camadas"] and not falta["campos"] and not falta["vazios"]:
        return rel
    if backup:
        rel["backup"] = copia_seguranca(caminho)
    ds = abrir(caminho, gravar=True)
    if ds is None:
        raise ValueError(f"Não consegui abrir {caminho} para gravar.")
    from .perfil import epsg as _epsg
    srs = None
    cod = _epsg(p)
    if cod is None:  # usa o sistema das camadas que já existem
        for i in range(ds.GetLayerCount()):
            s = ds.GetLayerByIndex(i).GetSpatialRef()
            if s is not None:
                srs = s.Clone()
                break
    else:
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(cod)
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    doms = set(ds.GetFieldDomainNames() or []) if hasattr(ds, "GetFieldDomainNames") else set()
    por_nome = {norm(c["nome"]): c for c in camadas_exigidas(p, falta["servicos"])}

    def campo_def(f):
        fd = ogr.FieldDefn(f["nome"], _tipo_campo_ogr(f["tipo"]))
        if f["tipo"] == "texto":
            fd.SetWidth(int(f.get("tamanho") or 255))
        if f.get("descricao") and hasattr(fd, "SetAlternativeName"):
            fd.SetAlternativeName(f["descricao"][:255])
        if str(f.get("valor_padrao") or "").strip() != "":
            v = _valor_padrao(f)
            if v is not None:
                fd.SetDefault(str(v) if not isinstance(v, str) else "'" + v.replace("'", "''") + "'")
        vals = f.get("valores_permitidos") or []
        if vals and hasattr(ds, "AddFieldDomain"):
            nome_dom = f["nome"] if f["nome"] not in doms else None
            if f["nome"] in doms:
                fd.SetDomainName(f["nome"])
            elif nome_dom:
                inteiro = f["tipo"] == "inteiro"
                enum = {}
                for v in vals:
                    c = codigo_valor(v)
                    desc = str(v)[len(c):].lstrip(" -–") or c
                    if inteiro and not re.fullmatch(r"-?\d+", c):
                        enum = None
                        break
                    enum[c] = desc
                if enum:
                    dom = ogr.CreateCodedFieldDomain(
                        nome_dom, f.get("descricao", "")[:255],
                        ogr.OFTInteger if inteiro else ogr.OFTString,
                        ogr.OFSTNone, enum)
                    try:
                        if ds.AddFieldDomain(dom):
                            doms.add(nome_dom)
                            fd.SetDomainName(nome_dom)
                    except Exception as e:
                        rel["avisos"].append(f"domínio {nome_dom}: {e}")
        return fd

    for nome in falta["camadas"]:
        cam = por_nome[norm(nome)]
        opcoes = ["TARGET_ARCGIS_VERSION=ARCGIS_PRO_3_2_OR_LATER"] if \
            ds.GetDriver().ShortName == "OpenFileGDB" else []
        lyr = ds.CreateLayer(cam["nome"], srs if cam["geometria"] != "tabela" else None,
                             _geom_ogr(cam["geometria"]), options=opcoes)
        for f in cam["campos"]:
            lyr.CreateField(campo_def(f))
        rel["camadas_criadas"].append(cam["nome"])
    for nome_lyr, campos in falta["campos"].items():
        lyr = ds.GetLayerByName(nome_lyr)
        cam = por_nome[norm(nome_lyr)]
        defs = {norm(f["nome"]): f for f in cam["campos"]}
        for nf in campos:
            try:
                lyr.CreateField(campo_def(defs[norm(nf)]))
                rel["campos_criados"].setdefault(nome_lyr, []).append(nf)
            except Exception as e:
                rel["avisos"].append(f"{nome_lyr}.{nf}: {e}")
    try:
        rel["preenchidos"] = _percorrer_vazios(ds, p, falta["servicos"], gravar=True)
    except Exception as e:
        rel["avisos"].append(f"valor padrão: {e}")
    ds = None
    return rel
