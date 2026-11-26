# -*- coding: utf-8 -*-
"""2.2 Trazer os seus dados: copia feições de uma camada qualquer (shapefile, GeoPackage,
File Geodatabase, GeoJSON, KML, CSV…) para uma camada do plano.

- montar_ligacao(): escolhe a camada do plano mais parecida e liga os campos pelo nome
  (nome técnico, apelido ou descrição do perfil); nos campos com valores permitidos
  (domínios), liga também os valores ("Noturno" -> "N", "Gama" -> "2").
- pedido_ia() / ler_resposta_ia(): o Claude sugere o que a ligação automática não achou.
- executar(): prévia (sem gravar) ou importação: converte os tipos, aplica os valores
  ligados, o valor fixo e o valor padrão do perfil, reprojeta e ajusta a geometria
  (simples -> multi). Antes de gravar faz uma cópia de segurança do plano.
- criar_plano(): plano novo vazio (.gdb/.gpkg) com as camadas e campos do perfil.

Sem QGIS (só osgeo): pode ser testado sozinho.

Formato da ligação (vai para o estado.json, para reaproveitar):
    {"origem": caminho, "camada_origem": nome, "plano": caminho, "camada_destino": nome,
     "substituir": False,
     "campos": {campo_destino: {"origem": campo_origem|"", "fixo": "", "valores": {de: para},
                                "como": "nome"|"parecido"|"ia"|"manual"|""}}}
"""
import datetime
import json
import os
import re

from . import estrutura
from .checklist import norm
from .perfil import codigo_valor

MAX_DISTINTOS = 40          # valores distintos guardados por campo (amostra e ligação de valores)
LOTE_GRAVACAO = 5000        # feições por transação
MAX_EXEMPLOS = 5

_FORMATOS_DATA = ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                  "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
                  "%Y/%m/%d", "%Y-%m-%d", "%d/%m/%Y")
_FORMATOS_HORA = ("%H:%M:%S", "%H:%M", "%Hh%M", "%Hh")
_DIA_SO_HORA = datetime.date(1899, 12, 30)     # convenção do ArcGIS para campo só de hora


# ------------------------------------------------------------------ utilidades
def txt(v):
    """Valor -> texto estável para comparar e guardar em JSON (1.0 -> '1')."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    s = str(v).strip()
    if re.fullmatch(r"-?\d+\.0+", s):
        s = s.split(".")[0]
    return s


def _chave(v):
    s = txt(v)
    return norm(s) or s.lower()


def _mesma(a, b):
    return os.path.normcase(os.path.normpath(a or "")) == os.path.normcase(os.path.normpath(b or ""))


def _camada(est, nome):
    for c in est["camadas"]:
        if c["nome"] == nome:
            return c
    for c in est["camadas"]:
        if norm(c["nome"]) == norm(nome):
            return c
    raise ValueError(f"Camada '{nome}' não encontrada em {os.path.basename(est['caminho'])}. "
                     f"Há: {', '.join(c['nome'] for c in est['camadas'])}")


def _permitidos(f):
    """{código: texto completo} dos valores permitidos de um campo do destino."""
    out = {}
    for v in f.get("valores_permitidos") or []:
        out.setdefault(codigo_valor(v), str(v))
    return out


# ------------------------------------------------------------------ leitura
@estrutura.com_excecoes
def camadas(caminho):
    """Camadas de um arquivo de origem (mesmo formato de estrutura.ler)."""
    return estrutura.ler(caminho)["camadas"]


def campos_destino(p, plano, camada, servicos=None, est=None):
    """Campos reais da camada do plano, com descrição, obrigatoriedade, valores permitidos
    e valor padrão vindos do perfil (e dos domínios do próprio plano)."""
    est = est or estrutura.ler(plano)
    cam = _camada(est, camada)
    perf = None
    if p:
        perf = next((c for c in estrutura.camadas_exigidas(p, servicos)
                     if norm(c["nome"]) == norm(cam["nome"])), None)
    pf = {norm(f["nome"]): f for f in (perf or {}).get("campos", [])}
    doms = est.get("dominios", {})
    campos = []
    for f in cam["campos"]:
        q = pf.get(norm(f["nome"]), {})
        vals = list(q.get("valores_permitidos") or [])
        if doms.get(f["dominio"]):
            vals = [f"{k} - {v}" if str(k) != str(v) else str(k) for k, v in doms[f["dominio"]].items()]
        campos.append({"nome": f["nome"], "alias": f["alias"], "tipo": f["tipo"],
                       "tamanho": f["tamanho"],
                       "descricao": q.get("descricao") or f["alias"] or "",
                       "obrigatorio": bool(q.get("obrigatorio")),
                       "valores_permitidos": vals,
                       "valor_padrao": str(q.get("valor_padrao") or "")})
    return {"camada": cam["nome"], "geometria": cam["geometria"], "epsg": cam["epsg"],
            "feicoes": cam["feicoes"], "campos": campos}


@estrutura.com_excecoes
def distintos(caminho, camada, campos, limite=MAX_DISTINTOS):
    """{campo: {"valores": [[valor, registros], ...] (os mais comuns), "total": n_distintos,
    "vazios": n}} lendo a camada uma vez."""
    ds = estrutura.abrir(caminho)
    if ds is None:
        raise ValueError(f"Não consegui abrir {caminho}")
    lyr = ds.GetLayerByName(camada)
    defn = lyr.GetLayerDefn()
    idx = {c: defn.GetFieldIndex(c) for c in campos if defn.GetFieldIndex(c) >= 0}
    cont = {c: {} for c in idx}
    vazios = {c: 0 for c in idx}
    lyr.ResetReading()
    for feat in lyr:
        for c, i in idx.items():
            v = txt(feat.GetField(i)) if feat.IsFieldSetAndNotNull(i) else ""
            if v == "":
                vazios[c] += 1
            else:
                cont[c][v] = cont[c].get(v, 0) + 1
    out = {}
    for c in idx:
        comuns = sorted(cont[c].items(), key=lambda kv: (-kv[1], kv[0]))
        out[c] = {"valores": [list(kv) for kv in comuns[:limite]], "total": len(comuns),
                  "vazios": vazios[c]}
    return out


# ------------------------------------------------------------------ ligação automática
def sugerir_destino(cam_origem, camadas_plano):
    """Nome da camada do plano que mais parece a de origem (mesma geometria e campos)."""
    melhor, nota_melhor = None, 0.0
    for c in camadas_plano:
        nota = estrutura._pontuacao(cam_origem, c)
        if nota > nota_melhor:
            melhor, nota_melhor = c, nota
    if melhor is not None and nota_melhor >= 0.5:
        return melhor["nome"]
    mesma_geom = [c for c in camadas_plano if c["geometria"] == cam_origem["geometria"]]
    if len(mesma_geom) == 1:
        return mesma_geom[0]["nome"]
    return None


def ligar_valores(permitidos, valores):
    """Valores da origem -> códigos permitidos. {valor: código ou ''}."""
    idx = {}
    for v in permitidos:
        c = codigo_valor(v)
        desc = str(v)[len(c):].lstrip(" -–") or c
        for k in (c, desc, v):
            idx.setdefault(_chave(k), c)
    out = {}
    for v in valores:
        k = _chave(v)
        cod = idx.get(k)
        if cod is None and k:
            cands = {c for kk, c in idx.items() if kk and estrutura._parecido(k, kk)}
            cod = cands.pop() if len(cands) == 1 else None
        out[txt(v)] = cod or ""
    return out


def ligar_campos(dest_campos, origem_campos):
    """{campo_destino: {"origem", "como"}} pelos nomes (exato primeiro, depois parecido)."""
    usados, out = set(), {}
    for exato in (True, False):
        for f in dest_campos:
            if f["nome"] in out:
                continue
            chaves = estrutura._chaves_campo(f)
            for o in origem_campos:
                if o["nome"] in usados:
                    continue
                co = estrutura._chaves_campo(o)
                if (exato and chaves & co) or (not exato and any(
                        estrutura._parecido(a, b) for a in chaves for b in co)):
                    usados.add(o["nome"])
                    out[f["nome"]] = {"origem": o["nome"], "como": "nome" if exato else "parecido"}
                    break
    return out


@estrutura.com_excecoes
def montar_ligacao(p, origem, camada_origem, plano, camada_destino=None, servicos=None,
                   anterior=None):
    """Ligação automática + o que a interface precisa mostrar.
    Devolve {"ligacao", "destino" (campos_destino), "origem" (camada com campos),
             "amostras" (distintos dos campos da origem)}.
    Com `anterior` (ligação salva para o mesmo par), mantém o que o usuário já tinha feito."""
    est_o = estrutura.ler(origem)
    cam_o = _camada(est_o, camada_origem)
    est_p = estrutura.ler(plano)
    if not camada_destino:
        camada_destino = sugerir_destino(cam_o, est_p["camadas"])
        if not camada_destino:
            raise ValueError("Não achei no plano uma camada com a mesma geometria da origem; "
                             "escolha a camada de destino.")
    dest = campos_destino(p, plano, camada_destino, servicos, est_p)
    amostras = distintos(origem, cam_o["nome"], [f["nome"] for f in cam_o["campos"]])
    auto = ligar_campos(dest["campos"], cam_o["campos"])
    ant = (anterior or {}).get("campos", {}) if anterior and \
        norm(anterior.get("camada_destino")) == norm(dest["camada"]) else {}
    nomes_o = {f["nome"] for f in cam_o["campos"]}
    campos = {}
    for f in dest["campos"]:
        a = ant.get(f["nome"])
        if a and (not a.get("origem") or a["origem"] in nomes_o):
            spec = {"origem": a.get("origem", ""), "fixo": a.get("fixo", ""),
                    "valores": dict(a.get("valores") or {}), "como": a.get("como", "manual")}
        else:
            l = auto.get(f["nome"], {})
            spec = {"origem": l.get("origem", ""), "fixo": "", "valores": {},
                    "como": l.get("como", "")}
        completar_valores(spec, f, amostras)
        campos[f["nome"]] = spec
    lig = {"origem": os.path.normpath(origem), "camada_origem": cam_o["nome"],
           "plano": os.path.normpath(plano), "camada_destino": dest["camada"],
           "substituir": bool((anterior or {}).get("substituir", False)), "campos": campos}
    return {"ligacao": lig, "destino": dest, "origem": cam_o, "amostras": amostras}


def completar_valores(spec, campo_dest, amostras):
    """Liga automaticamente os valores da amostra ainda sem destino (campo com domínio)."""
    perm = campo_dest.get("valores_permitidos") or []
    if not perm or not spec.get("origem"):
        return spec
    vals = [v for v, _n in (amostras.get(spec["origem"]) or {}).get("valores", [])]
    auto = ligar_valores(perm, vals)
    atuais = spec.setdefault("valores", {})
    for v, c in auto.items():
        if not atuais.get(v) and c:
            atuais[v] = c
    return spec


def chave_ligacao(lig):
    return tuple(os.path.normcase(os.path.normpath(lig.get(k) or "")) if k in ("origem", "plano")
                 else norm(lig.get(k)) for k in ("origem", "camada_origem", "plano", "camada_destino"))


def guardar(estado, lig):
    """Guarda a ligação no estado (substitui a do mesmo par origem/destino)."""
    lista = estado.setdefault("importacoes", [])
    k = chave_ligacao(lig)
    lista[:] = [l for l in lista if chave_ligacao(l) != k]
    lista.append(lig)
    return estado


def anterior(estado, origem, camada_origem, plano, camada_destino=None):
    """Última ligação salva para esta origem e este plano (e camada, se dada)."""
    for l in reversed(estado.get("importacoes") or []):
        if _mesma(l.get("origem"), origem) and l.get("camada_origem") == camada_origem and \
                _mesma(l.get("plano"), plano) and \
                (not camada_destino or norm(l.get("camada_destino")) == norm(camada_destino)):
            return l
    return None


# ------------------------------------------------------------------ IA
PEDIDO_IA = ("Ligue os campos da camada de ORIGEM aos campos da camada de DESTINO (plano de "
             "serviço do contrato), conforme os dados JSON recebidos. Responda só com o JSON pedido.")

INSTRUCOES_IA = """Você liga os campos de uma camada de ORIGEM (dados da empresa) aos campos da \
camada de DESTINO (plano de serviço exigido pelo contrato).

Responda SÓ com um JSON, sem texto antes ou depois:
{"campos": {"<campo do destino>": {"origem": "<campo da origem ou vazio>", \
"fixo": "<valor fixo ou vazio>", "valores": {"<valor da origem>": "<código permitido>"}}}, \
"observacoes": "<até 3 frases com dúvidas ou pendências>"}

Regras:
- Ligue um campo só quando o nome, a descrição e a amostra de valores indicarem que é o mesmo dado.
- Confira as ligações automáticas já feitas ("ja_ligado"); desfaça (origem vazia) as erradas.
- Nos campos de destino com "valores_permitidos", ligue CADA valor da amostra da origem ao código \
permitido correspondente (só o código, antes do " - "). Valor sem correspondência: não ponha.
- Use "fixo" só quando o valor é o mesmo para todos os registros e dá para saber pelo nome do \
arquivo ou da camada (ex.: lote) — senão deixe vazio.
- Não invente campos: "origem" tem que ser um nome exato da lista da origem.
- Inclua só os campos de destino em que você liga ou muda algo."""


def dados_ia(info):
    """Resumo da origem e do destino para o Claude (JSON compacto)."""
    lig = info["ligacao"]
    dest = []
    for f in info["destino"]["campos"]:
        spec = lig["campos"].get(f["nome"], {})
        d = {"nome": f["nome"], "descricao": f["descricao"], "tipo": f["tipo"],
             "obrigatorio": f["obrigatorio"]}
        if f["valores_permitidos"]:
            d["valores_permitidos"] = f["valores_permitidos"][:80]
        if spec.get("origem"):
            d["ja_ligado"] = spec["origem"]
        dest.append(d)
    orig = []
    for f in info["origem"]["campos"]:
        a = info["amostras"].get(f["nome"], {})
        orig.append({"nome": f["nome"], "apelido": f["alias"], "tipo": f["tipo"],
                     "distintos": a.get("total"), "vazios": a.get("vazios"),
                     "amostra": [v for v, _n in a.get("valores", [])[:25]]})
    return json.dumps({"origem": {"arquivo": os.path.basename(lig["origem"]),
                                  "camada": lig["camada_origem"],
                                  "geometria": info["origem"]["geometria"],
                                  "feicoes": info["origem"]["feicoes"], "campos": orig},
                       "destino": {"camada": lig["camada_destino"],
                                   "geometria": info["destino"]["geometria"], "campos": dest}},
                      ensure_ascii=False)


def argumentos_claude(modelo="sonnet"):
    """`claude -p` sem ferramentas nem MCP; os dados vão pela entrada padrão."""
    return ["-p", PEDIDO_IA, "--model", modelo, "--tools", "", "--strict-mcp-config",
            "--append-system-prompt", INSTRUCOES_IA, "--output-format", "json"]


def sugerir_api(dados, chave_api):
    """Mesma sugestão pela chave de API (alternativa à conta do Claude Code). Devolve o texto."""
    import anthropic
    from .extracao import MODELO
    cli = anthropic.Anthropic(api_key=chave_api)
    r = cli.messages.create(model=MODELO, max_tokens=8000, system=INSTRUCOES_IA,
                            messages=[{"role": "user", "content": PEDIDO_IA + "\n\n" + dados}])
    return "".join(getattr(b, "text", "") for b in r.content)


def texto_resposta_claude(saida):
    """Saída de `claude -p --output-format json` -> (ok, texto)."""
    try:
        ev = json.loads(saida)
    except ValueError:
        return False, saida.strip()[-600:]
    if isinstance(ev, list):     # algumas versões devolvem a lista de eventos
        ev = next((e for e in reversed(ev) if e.get("type") == "result"), {})
    ok = not ev.get("is_error") and ev.get("subtype", "success") == "success"
    return ok, ev.get("result") or ""


def ler_resposta_ia(texto, info):
    """Aplica a resposta do Claude à ligação de `info` (só o que for válido).
    Devolve (ligacao, observacoes, n_mudancas)."""
    m = re.search(r"\{.*\}", texto or "", re.S)
    if not m:
        raise ValueError("O Claude não devolveu a ligação em JSON.")
    resp = json.loads(m.group(0))
    lig = json.loads(json.dumps(info["ligacao"]))
    nomes_o = {f["nome"] for f in info["origem"]["campos"]}
    dest = {f["nome"]: f for f in info["destino"]["campos"]}
    mudancas = 0
    for nome, r in (resp.get("campos") or {}).items():
        f = dest.get(nome) or next((d for n, d in dest.items() if norm(n) == norm(nome)), None)
        if f is None or not isinstance(r, dict):
            continue
        spec = lig["campos"][f["nome"]]
        orig = (r.get("origem") or "").strip()
        if orig and orig not in nomes_o:
            continue
        if "origem" in r and orig != spec.get("origem", ""):
            spec["origem"] = orig
            spec["valores"] = {}
            mudancas += 1
        fixo = txt(r.get("fixo"))
        if fixo and fixo != spec.get("fixo"):
            spec["fixo"] = fixo
            mudancas += 1
        perm = _permitidos(f)
        for de, para in (r.get("valores") or {}).items():
            c = codigo_valor(txt(para))
            if perm and c not in perm:
                continue
            if spec["valores"].get(txt(de)) != c:
                spec["valores"][txt(de)] = c
                mudancas += 1
        spec["como"] = "ia"
        completar_valores(spec, f, info["amostras"])
    return lig, str(resp.get("observacoes") or ""), mudancas


# ------------------------------------------------------------------ conversão
def _data(v, so_hora_ok=True):
    """Texto/data -> 'AAAA/MM/DD HH:MM:SS' (ou None)."""
    if isinstance(v, (datetime.datetime, datetime.date)):
        d = v if isinstance(v, datetime.datetime) else datetime.datetime.combine(v, datetime.time())
        return d.strftime("%Y/%m/%d %H:%M:%S")
    s = txt(v).replace("+00", "").strip()
    s = re.sub(r"\.\d+$", "", s)
    for fmt in _FORMATOS_DATA:
        try:
            return datetime.datetime.strptime(s, fmt).strftime("%Y/%m/%d %H:%M:%S")
        except ValueError:
            pass
    if so_hora_ok:
        for fmt in _FORMATOS_HORA:
            try:
                h = datetime.datetime.strptime(s.lower(), fmt).time()
                return datetime.datetime.combine(_DIA_SO_HORA, h).strftime("%Y/%m/%d %H:%M:%S")
            except ValueError:
                pass
    return None


def converter(v, tipo_ogr, largura=0):
    """(valor convertido, problema) — problema: None, 'conversao' ou 'truncado'."""
    _, ogr, _ = estrutura._ogr()
    if v is None or txt(v) == "":
        return None, None
    if tipo_ogr in (ogr.OFTInteger, ogr.OFTInteger64):
        if isinstance(v, bool):
            return int(v), None
        if isinstance(v, int):
            return v, None
        s = txt(v).replace(",", ".")
        if s.lower() in ("sim", "s", "true", "verdadeiro", "x"):
            return 1, None
        if s.lower() in ("nao", "não", "n", "false", "falso"):
            return 0, None
        try:
            f = float(s)
        except ValueError:
            return None, "conversao"
        return (int(f), None) if f.is_integer() else (int(round(f)), "conversao")
    if tipo_ogr == ogr.OFTReal:
        if isinstance(v, (int, float)):
            return float(v), None
        s = txt(v)
        if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", s):   # 1.234,5
            s = s.replace(".", "")
        try:
            return float(s.replace(",", ".")), None
        except ValueError:
            return None, "conversao"
    if tipo_ogr in (ogr.OFTDate, ogr.OFTDateTime):
        d = _data(v, so_hora_ok=tipo_ogr == ogr.OFTDateTime)
        return (d, None) if d else (None, "conversao")
    s = txt(v)
    if largura and len(s) > largura:
        return s[:largura], "truncado"
    return s, None


def _geom_destino(g, tipo_dest, ct):
    """Reprojeta, tira Z/M se o destino não tem e força o tipo (linha -> multilinha)."""
    _, ogr, _ = estrutura._ogr()
    g = g.Clone()
    if ct is not None:
        g.Transform(ct)
    if not ogr.GT_HasZ(tipo_dest) and g.Is3D():
        g.FlattenTo2D()
    if not ogr.GT_HasM(tipo_dest) and g.IsMeasured():
        g.SetMeasured(False)
    g = ogr.ForceTo(g, tipo_dest)
    return g


def _srs_epsg(srs):
    if srs is None:
        return None
    s = srs.Clone()
    s.AutoIdentifyEPSG()
    c = s.GetAuthorityCode(None)
    return f"EPSG:{c}" if c else (s.GetName() or "?")


def _problema(rel, campo, tipo, exemplo=None):
    d = rel["problemas"].setdefault(campo, {})
    d[tipo] = d.get(tipo, 0) + 1
    if exemplo is not None:
        ex = d.setdefault("exemplos", {}).setdefault(tipo, [])
        e = txt(exemplo)
        if e not in ex and len(ex) < MAX_EXEMPLOS:
            ex.append(e)


@estrutura.com_excecoes
def executar(lig, p=None, servicos=None, gravar=False, backup=True, progresso=None,
             cancelado=None):
    """Prévia (gravar=False) ou importação. Devolve o relatório:
    {"lidas", "gravadas", "apagadas", "sem_geometria", "geometria_falhou", "reprojecao",
     "problemas": {campo: {"conversao"|"truncado"|"fora_do_dominio"|"obrigatorio_vazio": n,
                           "exemplos": {...}}},
     "sem_origem_obrigatorios": [...], "avisos": [...], "backup", "cancelado"}"""
    gdal, ogr, osr = estrutura._ogr()
    est_p = estrutura.ler(lig["plano"])
    dest = campos_destino(p, lig["plano"], lig["camada_destino"], servicos, est_p)
    cam_o = _camada(estrutura.ler(lig["origem"]), lig["camada_origem"])
    rel = {"origem": lig["origem"], "camada_origem": cam_o["nome"], "plano": lig["plano"],
           "camada_destino": dest["camada"], "lidas": 0, "gravadas": 0, "apagadas": 0,
           "sem_geometria": 0, "geometria_falhou": 0, "reprojecao": None, "problemas": {},
           "sem_origem_obrigatorios": [], "avisos": [], "backup": None, "cancelado": False,
           "gravado": bool(gravar)}

    if dest["geometria"] != "tabela" and cam_o["geometria"] != dest["geometria"]:
        raise ValueError(f"A camada de origem é {cam_o['geometria']} e a do plano é "
                         f"{dest['geometria']}; não dá para copiar a geometria.")

    # campos: (campo destino, índice origem, spec, permitidos, valor padrão)
    ds_o = estrutura.abrir(lig["origem"])
    lyr_o = ds_o.GetLayerByName(cam_o["nome"])
    defn_o = lyr_o.GetLayerDefn()
    plano_campos = []
    for f in dest["campos"]:
        spec = lig["campos"].get(f["nome"]) or {}
        i = defn_o.GetFieldIndex(spec["origem"]) if spec.get("origem") else -1
        if spec.get("origem") and i < 0:
            rel["avisos"].append(f"Campo '{spec['origem']}' não existe mais na origem.")
        perm = _permitidos(f)
        fixo = txt(spec.get("fixo"))
        padrao = txt(f.get("valor_padrao"))
        if perm:
            fixo = codigo_valor(fixo) if fixo else ""
            padrao = codigo_valor(padrao) if padrao else ""
        valores = {txt(k): (codigo_valor(v) if perm else txt(v))
                   for k, v in (spec.get("valores") or {}).items() if txt(v) != ""}
        if f["obrigatorio"] and i < 0 and not fixo and not padrao:
            rel["sem_origem_obrigatorios"].append(f["nome"])
        if i < 0 and not fixo and not padrao:
            continue
        plano_campos.append((f, i, valores, {_chave(c) for c in perm}, fixo, padrao))

    srs_o = lyr_o.GetSpatialRef()
    ds_d = estrutura.abrir(lig["plano"])
    lyr_d = ds_d.GetLayerByName(dest["camada"])
    srs_d = lyr_d.GetSpatialRef()
    ct = None
    if dest["geometria"] != "tabela":
        if srs_o is None:
            rel["avisos"].append("A origem não tem sistema de coordenadas; considerei o mesmo do plano.")
        elif srs_d is not None and not srs_o.IsSame(srs_d):
            a, b = srs_o.Clone(), srs_d.Clone()
            a.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            b.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            ct = osr.CoordinateTransformation(a, b)
            rel["reprojecao"] = f"{_srs_epsg(srs_o)} → {_srs_epsg(srs_d)}"
    tipo_geom_d = lyr_d.GetGeomType()

    if gravar:
        ds_d = lyr_d = None
        if backup:
            rel["backup"] = estrutura.copia_seguranca(lig["plano"])
        ds_d = estrutura.abrir(lig["plano"], gravar=True)
        if ds_d is None:
            raise ValueError(f"Não consegui abrir {lig['plano']} para gravar (está aberto em outro programa?).")
        lyr_d = ds_d.GetLayerByName(dest["camada"])
    defn_d = lyr_d.GetLayerDefn()
    idx_d = {f["nome"]: defn_d.GetFieldIndex(f["nome"]) for f, *_ in plano_campos}
    tipos_d = {n: defn_d.GetFieldDefn(j).GetType() for n, j in idx_d.items()}
    larg_d = {n: (defn_d.GetFieldDefn(j).GetWidth() if tipos_d[n] == ogr.OFTString else 0)
              for n, j in idx_d.items()}
    transacao = gravar and lyr_d.TestCapability(ogr.OLCTransactions)

    if gravar and lig.get("substituir"):
        fids = [ft.GetFID() for ft in lyr_d]
        if transacao:
            lyr_d.StartTransaction()
        for fid in fids:
            lyr_d.DeleteFeature(fid)
        if transacao:
            lyr_d.CommitTransaction()
        rel["apagadas"] = len(fids)

    total = lyr_o.GetFeatureCount()
    pendentes = 0
    if transacao:
        lyr_d.StartTransaction()
    lyr_o.ResetReading()
    for feat in lyr_o:
        if cancelado and cancelado():
            rel["cancelado"] = True
            break
        rel["lidas"] += 1
        if progresso and rel["lidas"] % 2000 == 0:
            progresso(f"{'Importando' if gravar else 'Conferindo'} {rel['lidas']} de {total}…")
        novo = ogr.Feature(defn_d) if gravar else None
        for f, i, valores, perm, fixo, padrao in plano_campos:
            n = f["nome"]
            bruto = None
            if i >= 0 and feat.IsFieldSetAndNotNull(i):
                bruto = feat.GetField(i)
                if txt(bruto) == "":
                    bruto = None
            if bruto is not None and valores:
                bruto = valores.get(txt(bruto), bruto)
            if bruto is None and fixo:
                bruto = fixo
            if bruto is None and padrao:
                bruto = padrao
            if bruto is None:
                if f["obrigatorio"]:
                    _problema(rel, n, "obrigatorio_vazio")
                continue
            if perm and _chave(bruto) not in perm:
                _problema(rel, n, "fora_do_dominio", bruto)
            v, prob = converter(bruto, tipos_d[n], larg_d[n])
            if prob:
                _problema(rel, n, prob, bruto)
            if v is not None and novo is not None:
                novo.SetField(idx_d[n], v)
        if dest["geometria"] != "tabela":
            g = feat.GetGeometryRef()
            if g is None or g.IsEmpty():
                rel["sem_geometria"] += 1
            else:
                try:
                    g2 = _geom_destino(g, tipo_geom_d, ct)
                    if novo is not None:
                        novo.SetGeometry(g2)
                except Exception as e:
                    rel["geometria_falhou"] += 1
                    if len(rel["avisos"]) < 20:
                        rel["avisos"].append(f"Feição {feat.GetFID()}: geometria não convertida ({e}).")
                    continue
        if novo is not None:
            lyr_d.CreateFeature(novo)
            rel["gravadas"] += 1
            pendentes += 1
            if transacao and pendentes >= LOTE_GRAVACAO:
                lyr_d.CommitTransaction()
                lyr_d.StartTransaction()
                pendentes = 0
    if transacao:
        if rel["cancelado"]:
            lyr_d.RollbackTransaction()
            rel["gravadas"] -= pendentes
        else:
            lyr_d.CommitTransaction()
    if gravar:
        lyr_d.SyncToDisk()
    ds_d = ds_o = None
    if rel["cancelado"] and gravar and rel["backup"]:
        rel["avisos"].append(f"Importação cancelada no meio; o plano antes dela está em {rel['backup']}.")
    return rel


def resumo(rel):
    """Linhas de texto para mostrar ao usuário."""
    linhas = []
    acao = "gravadas" if rel.get("gravado") else "a importar"
    linhas.append(f"{rel['lidas']} feição(ões) lida(s) de {rel['camada_origem']}; "
                  f"{rel['gravadas'] if rel.get('gravado') else rel['lidas'] - rel['geometria_falhou']} "
                  f"{acao} em {rel['camada_destino']}.")
    if rel.get("apagadas"):
        linhas.append(f"{rel['apagadas']} feição(ões) que já estavam no plano foram substituídas.")
    if rel.get("reprojecao"):
        linhas.append(f"Reprojeção: {rel['reprojecao']}.")
    if rel.get("sem_geometria"):
        linhas.append(f"⚠ {rel['sem_geometria']} sem geometria.")
    if rel.get("geometria_falhou"):
        linhas.append(f"⚠ {rel['geometria_falhou']} com geometria que não deu para converter (puladas).")
    if rel.get("sem_origem_obrigatorios"):
        linhas.append("⚠ Obrigatórios sem origem nem valor fixo: " + ", ".join(rel["sem_origem_obrigatorios"]))
    nomes = {"conversao": "não convertido", "truncado": "texto cortado",
             "fora_do_dominio": "fora dos valores permitidos", "obrigatorio_vazio": "obrigatório vazio"}
    for campo, d in rel.get("problemas", {}).items():
        for tipo, rot in nomes.items():
            if d.get(tipo):
                ex = (d.get("exemplos") or {}).get(tipo) or []
                linhas.append(f"⚠ {campo}: {d[tipo]} {rot}" + (f" (ex.: {', '.join(ex)})" if ex else ""))
    linhas += rel.get("avisos", [])
    if rel.get("backup"):
        linhas.append(f"Cópia de segurança: {rel['backup']}")
    return linhas


# ------------------------------------------------------------------ plano novo
@estrutura.com_excecoes
def criar_plano(p, caminho, servicos=None):
    """Plano novo vazio (.gdb ou .gpkg) com as camadas e campos do perfil."""
    gdal, _, _ = estrutura._ogr()
    caminho = os.path.normpath(caminho)
    ext = os.path.splitext(caminho)[1].lower()
    driver = {".gdb": "OpenFileGDB", ".gpkg": "GPKG"}.get(ext)
    if driver is None:
        raise ValueError("O plano novo tem que ser .gdb ou .gpkg.")
    if os.path.exists(caminho):
        raise ValueError(f"{caminho} já existe.")
    if not estrutura.camadas_exigidas(p, servicos):
        raise ValueError("O perfil não tem camadas para estes serviços.")
    _, ogr, _ = estrutura._ogr()
    ds = gdal.GetDriverByName(driver).Create(caminho, 0, 0, 0, gdal.GDT_Unknown)
    # .gdb sem nenhuma camada não é reconhecido ao reabrir: tabela provisória
    ds.CreateLayer(_PROVISORIA, None, ogr.wkbNone)
    ds = None
    rel = estrutura.completar_plano(p, caminho, servicos, backup=False)
    ds = estrutura.abrir(caminho, gravar=True)
    for i in range(ds.GetLayerCount()):
        if ds.GetLayerByIndex(i).GetName() == _PROVISORIA:
            ds.DeleteLayer(i)
            break
    ds = None
    rel["camadas_criadas"] = [c for c in rel["camadas_criadas"] if c != _PROVISORIA]
    return rel


_PROVISORIA = "qgis_ia_provisoria"
