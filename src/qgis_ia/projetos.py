# -*- coding: utf-8 -*-
"""Projetos da janela inicial do QGIS_IA: Coleta Convencional, Coleta Seletiva, Varrição
Manual e Varrição Mecanizada.

Fluxo: escolher a pasta com os arquivos → ler a pasta (documentos, planos .gdb/.gpkg/.shp,
planilhas) → detalhes do projeto (sugeridos pelo que foi lido; o usuário confirma) → criar o
plano de serviço (.gdb no padrão do Anexo G, tabela .xlsx, texto .docx e conferência).

Sem interface aqui (dá para testar fora do QGIS); a janela fica em inicio.py.
"""
import datetime as _dt
import json
import os
import shutil

from osgeo import gdal, ogr

try:
    from . import edital_slu as E
    from .actions import slu
except ImportError:  # testes: pastas do plugin e de actions no sys.path
    import edital_slu as E
    import slu

ARQ_PROJETO = "qgis_ia_projeto.json"

# código do serviço no edital → nome, ícone e descrição do cartão
TIPOS = [
    {"servico": "P1", "nome": "Coleta Convencional", "icone": "🚛",
     "descricao": "Resíduos domiciliares e comerciais, porta a porta, ponto a ponto e mista"},
    {"servico": "P2", "nome": "Coleta Seletiva", "icone": "♻️",
     "descricao": "Recicláveis secos, porta a porta e PEVs/LEVs"},
    {"servico": "P5", "nome": "Varrição Manual", "icone": "🧹",
     "descricao": "Vias e logradouros varridos por equipes com carrinho (lutocar)"},
    {"servico": "P6", "nome": "Varrição Mecanizada", "icone": "🚜",
     "descricao": "Vias varridas por varredeira mecânica"},
]
TIPO = {t["servico"]: t for t in TIPOS}

EXT_DOCS = (".pdf", ".docx", ".doc", ".txt")
EXT_PLANILHAS = (".xlsx", ".xls", ".csv")
EXT_VETOR = (".gpkg", ".shp", ".geojson", ".kml")
CAMADA_AREA = "lm_area_circuito_planejado"
CAMADA_LINHA = "st_circuito_planejado"

# Horários padrão do edital (turnos do perfil SLU-DF)
HORARIOS = {
    "coleta": {"Diurno": "06h00 às 14h20", "Noturno": "16h00 às 00h20"},
    "varricao": {"Diurno": "06h00 às 14h20", "Noturno": "16h00 às 00h20"},
}

TEXTOS_PADRAO = {
    "P1": {
        "O que é o serviço":
            "Coleta e transporte dos resíduos sólidos domiciliares e comerciais (até 120 litros "
            "por dia) nas Regiões Administrativas do lote, nas modalidades porta a porta, ponto a "
            "ponto (contêineres e semienterrados) e mista.",
        "Tipo de material coletado":
            "Resíduos sólidos domiciliares e comerciais indiferenciados.",
    },
    "P2": {
        "O que é o serviço":
            "Coleta e transporte dos resíduos recicláveis secos nas Regiões Administrativas do "
            "lote, porta a porta e em pontos de entrega voluntária (PEVs/LEVs).",
        "Tipo de material coletado":
            "Resíduos recicláveis secos (papel, papelão, plástico, metal e vidro).",
    },
    "P5": {
        "O que é o serviço":
            "Varrição manual de vias e logradouros públicos (sarjetas, calçadas, canteiros e "
            "praças), com recolhimento dos resíduos em sacos e carrinhos de varrição (lutocar).",
        "Tipo de material coletado":
            "Resíduos de varrição (areia, folhas, papéis e pequenos resíduos).",
    },
    "P6": {
        "O que é o serviço":
            "Varrição mecanizada de vias públicas pavimentadas, com varredeiras mecânicas, "
            "principalmente nas vias de maior extensão e tráfego.",
        "Tipo de material coletado":
            "Resíduos de varrição (areia, folhas e pequenos resíduos das sarjetas).",
    },
}


# ====================================================================== ler a pasta
class _sem_excecao:
    """Sem exceções e sem mensagens do GDAL (curvas do .gdb dão 'Incompatible geometry')."""

    def __enter__(self):
        self._m = gdal.ExceptionMgr(useExceptions=False)
        self._m.__enter__()
        gdal.PushErrorHandler("CPLQuietErrorHandler")

    def __exit__(self, *a):
        gdal.PopErrorHandler()
        return self._m.__exit__(*a)


def resumo_banco(caminho):
    """Lê um .gdb/.gpkg/.shp: camadas (nome, nº de feições), circuitos, turnos, RAs e km."""
    with _sem_excecao():
        return _resumo_banco(caminho)


def _resumo_banco(caminho):
    out = {"caminho": caminho, "nome": os.path.basename(caminho), "camadas": [],
           "circuitos": 0, "turnos": {}, "ras": [], "km_linhas": 0.0,
           "servico": None, "lote": None, "erro": None}
    try:
        out["servico"], out["lote"] = slu._servico_lote_de_gdb(caminho)
    except (ValueError, KeyError):
        pass
    ds = ogr.Open(caminho)
    if ds is None:
        out["erro"] = "não abriu"
        return out
    ras = set()
    for lyr in ds:
        nome = lyr.GetName()
        if nome.startswith("T_1_") or nome.lower() == "toolbox":
            continue                       # topologia/ferramentas do ArcGIS
        n = lyr.GetFeatureCount()
        out["camadas"].append({"nome": nome, "feicoes": n})
        campos = {lyr.GetLayerDefn().GetFieldDefn(i).GetName().lower(): i
                  for i in range(lyr.GetLayerDefn().GetFieldCount())}
        if nome.lower() == CAMADA_AREA:
            out["circuitos"] = n
            lyr.ResetReading()
            for f in lyr:
                if "turno" in campos:
                    t = (f.GetField(campos["turno"]) or "").strip().capitalize() or "—"
                    out["turnos"][t] = out["turnos"].get(t, 0) + 1
                if "codigo_ra" in campos and f.GetField(campos["codigo_ra"]) is not None:
                    try:
                        ras.add(int(f.GetField(campos["codigo_ra"])))
                    except (TypeError, ValueError):
                        pass
        elif nome.lower() == CAMADA_LINHA:
            lyr.ResetReading()
            tot = 0.0
            for f in lyr:
                g = f.GetGeometryRef()
                if g is not None:
                    tot += g.Length()
            out["km_linhas"] = round(tot / 1000.0, 1)
    out["ras"] = sorted(ras)
    if out["lote"] is None and ras:
        for lote, conj in E.RA_POR_LOTE.items():
            if ras <= conj:
                out["lote"] = lote
                break
    return out


def ler_pasta(pasta, profundidade=3, pular=None):
    """Procura na pasta (e subpastas) os arquivos do projeto. Pula a pasta onde o plano
    deste projeto é salvo (o que o app gerou não é arquivo de entrada) e as de 'pular'."""
    res = {"pasta": pasta, "documentos": [], "bancos": [], "planilhas": [], "outros": 0}
    if not pasta or not os.path.isdir(pasta):
        return res
    pular = {os.path.normcase(os.path.normpath(x)) for x in pular or []}
    salvo = carregar_projeto(pasta)
    if salvo and salvo.get("pasta_saida"):
        pular.add(os.path.normcase(os.path.normpath(salvo["pasta_saida"])))
    base = os.path.normpath(pasta).count(os.sep)
    for raiz, dirs, arqs in os.walk(pasta):
        nivel = os.path.normpath(raiz).count(os.sep) - base
        gdbs = [d for d in dirs if d.lower().endswith(".gdb")]
        for d in gdbs:
            res["bancos"].append(os.path.join(raiz, d))
        dirs[:] = [d for d in dirs if d not in gdbs and not d.startswith(".")
                   and d != "__pycache__" and nivel < profundidade
                   and os.path.normcase(os.path.normpath(os.path.join(raiz, d))) not in pular]
        for a in arqs:
            c = os.path.join(raiz, a)
            ext = os.path.splitext(a)[1].lower()
            if a.startswith("~$") or a == ARQ_PROJETO:
                continue
            if ext in EXT_DOCS:
                res["documentos"].append(c)
            elif ext in EXT_PLANILHAS:
                res["planilhas"].append(c)
            elif ext in EXT_VETOR:
                res["bancos"].append(c)
            else:
                res["outros"] += 1
    for k in ("documentos", "planilhas", "bancos"):
        res[k].sort(key=lambda c: c.lower())
    res["bancos"] = [resumo_banco(c) for c in res["bancos"]]
    return res


def banco_do_servico(leitura, servico):
    """O plano já feito da pasta para este serviço (pelo nome: CC01, CS01, VA01, VE01…)."""
    certos = [b for b in leitura["bancos"] if b["servico"] == servico and not b["erro"]]
    if certos:
        return max(certos, key=lambda b: b["circuitos"])
    return None


# ====================================================================== detalhes
def detalhes_sugeridos(leitura, servico):
    """Detalhes do projeto a partir do que foi lido; o usuário confere na janela."""
    b = banco_do_servico(leitura, servico)
    turnos = []
    if b and b["turnos"]:
        turnos = [t for t in ("Diurno", "Noturno") if t in b["turnos"]]
    d = {
        "servico": servico,
        "nome": TIPO[servico]["nome"],
        "lote": (b or {}).get("lote") or 1,
        "empresa": "",
        "plano_existente": b["caminho"] if b else "",
        "turnos": turnos or ["Diurno"],
        "pasta_saida": os.path.join(leitura["pasta"], "Plano") if leitura.get("pasta") else "",
        "validar": True,
        "textos": {},
    }
    d["textos"] = textos_sugeridos(servico, d["lote"], d["turnos"], b)
    return d


def textos_sugeridos(servico, lote, turnos, banco=None):
    """Seções do texto (.docx) que dá para preencher sem perguntar."""
    t = dict(TEXTOS_PADRAO.get(servico, {}))
    grupo = E.SERVICOS[servico]["grupo"]
    hs = HORARIOS.get(grupo, {})
    if turnos:
        t["Horários"] = "\n".join(f"Turno {x.lower()}: {hs.get(x, 'conforme o edital')}."
                                  for x in turnos)
    frota = E.FROTA_ANEXO_R.get((servico, int(lote)))
    if frota:
        linhas = []
        for cod, por_turno in frota.items():
            qt = ", ".join(f"{n} {tu.lower()}" for tu, n in por_turno.items() if n)
            if qt:
                linhas.append(f"{E.EQUIPAMENTOS[cod]} (código {cod} da Tabela 4): {qt}.")
        t["Tipos de caminhões utilizados"] = "\n".join(linhas)
    if banco and banco["circuitos"]:
        ras = ", ".join(E.RA.get(r, str(r)) for r in banco["ras"])
        partes = [f"O plano tem {banco['circuitos']} circuitos"]
        if banco["turnos"]:
            partes.append("(" + ", ".join(f"{n} {k.lower()}" for k, n in banco["turnos"].items())
                          + ")")
        txt = " ".join(partes)
        if ras:
            txt += f", atendendo as RAs {ras}"
        if banco["km_linhas"]:
            txt += f", com {banco['km_linhas']:.1f} km de vias planejadas"
        t["Planejamento das rotas e frequências"] = txt + "."
    return t


def faltando(det):
    """O que ainda falta informar para criar o plano."""
    f = []
    if det.get("lote") not in (1, 2, 3):
        f.append("lote")
    if not det.get("pasta_saida"):
        f.append("pasta onde salvar o plano")
    if not det.get("turnos"):
        f.append("turno")
    pe = det.get("plano_existente")
    if pe and not os.path.exists(pe):
        f.append("plano existente (arquivo não encontrado)")
    return f


# ====================================================================== projeto salvo
def salvar_projeto(pasta, det):
    d = dict(det, salvo_em=_dt.datetime.now().isoformat(timespec="seconds"))
    with open(os.path.join(pasta, ARQ_PROJETO), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def carregar_projeto(pasta, servico=None):
    arq = os.path.join(pasta, ARQ_PROJETO)
    if not os.path.exists(arq):
        return None
    try:
        with open(arq, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if servico and d.get("servico") != servico:
        return None
    return d


# ====================================================================== criar o plano
def criar_plano(det, carregar=True, limite_df=None):
    """Gera o plano de serviço (Anexo G): .gdb (o existente ou um novo vazio no padrão),
    tabela .xlsx, texto .docx e, se pedido, a conferência do .gdb (relatório .xlsx)."""
    falta = faltando(det)
    if falta:
        raise ValueError("Falta informar: " + ", ".join(falta))
    servico, lote = det["servico"], int(det["lote"])
    pe = det.get("plano_existente") or None
    if pe and not pe.lower().endswith(".gdb"):
        raise ValueError("O plano do edital é um File Geodatabase (.gdb); o arquivo "
                         f"{os.path.basename(pe)} precisa ser trazido para um .gdb primeiro "
                         "(Planos do Contrato → 5. Trazer dados).")
    textos = {k: v for k, v in (det.get("textos") or {}).items() if str(v).strip()}
    aviso_copia = ""
    if pe and det.get("copiar", True):
        # a entrega leva o .gdb junto: copia o plano atual para a pasta do plano (o original
        # não é alterado); se a cópia já existe, ela é mantida (pode ter sido editada)
        rot = E.lote_codigo(E.normaliza_servico(servico), lote)
        destino = os.path.join(det["pasta_saida"], f"{E.normaliza_servico(servico)}_{rot}",
                               f"{rot}.gdb")
        if os.path.normcase(os.path.abspath(pe)) != os.path.normcase(os.path.abspath(destino)):
            if os.path.exists(destino):
                aviso_copia = (f"Já havia {rot}.gdb na pasta do plano; foi mantido (apague-o "
                               f"para copiar de novo de {os.path.basename(pe)}).")
            else:
                os.makedirs(os.path.dirname(destino), exist_ok=True)
                shutil.copytree(pe, destino, ignore=shutil.ignore_patterns("*.lock"))
            pe = destino
    corrigido = None
    dentro_saida = pe and os.path.normcase(os.path.abspath(pe)).startswith(
        os.path.normcase(os.path.abspath(det["pasta_saida"])) + os.sep)
    if pe and det.get("corrigir") and dentro_saida:
        # só na cópia (nunca no plano original do usuário): preenche os campos calculáveis
        try:
            d = slu.slu_dividir_linhas(pe, servico, lote, backup=False)
            c = slu.slu_preencher_atributos(pe, servico, lote, sobrescrever=False, backup=False)
            corrigido = {k: v for k, v in c.items() if k not in ("success", "gdb", "backup")}
            corrigido["linhas_divididas"] = d["divididas"]
        except Exception as e:
            corrigido = {"falhou": str(e)}
    r = slu.slu_gerar_plano(servico, lote, det["pasta_saida"], gdb_existente=pe,
                            empresa=det.get("empresa") or None, dados_texto=textos,
                            turnos=det.get("turnos"), carregar=carregar and not pe,
                            limite_df=limite_df)
    if pe and carregar:
        nomes = [c["nome"] for c in E.esquema(servico, lote)]
        try:
            slu._carregar_no_projeto(pe, nomes, grupo=E.lote_codigo(servico, lote))
        except Exception:
            pass
    if aviso_copia:
        r["aviso"] = aviso_copia
    r["correcao"] = corrigido
    r["validacao"] = None
    gdb = r["arquivos"].get("gdb")
    if det.get("validar", True) and gdb:
        rel = os.path.join(r["pasta"], f"{E.lote_codigo(servico, lote)}_conferencia.xlsx")
        try:
            v = slu.slu_validar_gdb(gdb, servico, lote, relatorio_xlsx=rel)
            r["validacao"] = {"erros": v["erros"], "avisos": v["avisos"],
                              "circuitos": v["circuitos"], "relatorio": rel}
            r["arquivos"]["xlsx_conferencia"] = rel
        except Exception as e:  # a conferência não impede o plano
            r["validacao"] = {"falhou": str(e)}
    return r


def nome_arquivo(chave):
    return {"gdb": "Plano (.gdb)", "xlsx_atributos": "Tabela de atributos (.xlsx)",
            "xlsx_programacao": "Programação trimestral (.xlsx)",
            "docx": "Texto do plano (.docx)",
            "xlsx_conferencia": "Conferência do plano (.xlsx)"}.get(chave, chave)
