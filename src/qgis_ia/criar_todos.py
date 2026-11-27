# -*- coding: utf-8 -*-
""""Criar Todos": a partir de uma pasta com os arquivos do contrato (mesmo que seja só o
edital), descobre os planos que o contrato pede (serviço × lote, com os arquivos, nomes e
seções que o edital exige), aponta os problemas com a solução e cria todos de uma vez.

Vale para qualquer licitação: tudo sai do PERFIL do contrato (contrato.json, montado pelo
Claude a partir do edital). Se o edital é o do SLU-DF (Pregão 90005/2026), usa o perfil pronto
e o gerador do Anexo G.

    analisar(pasta)  → perfil, planos propostos e problemas
    criar(analise, ids, pasta_saida) → arquivos de cada plano + relatório .xlsx

Etapas de cada plano (o que o usuário escolher):
    base: plano atual da pasta (copiado; o original não muda) ou, sem plano, vias do
          OpenStreetMap baixadas para o município (Base/), com o limite do IBGE;
    adequação de frota e jornada (com o histórico de operação da pasta);
    correção automática dos campos calculáveis; conferência com as regras do edital;
    tabela .xlsx e texto .docx com as seções exigidas, preenchidas com o edital e a
    planilha da empresa (planilha_modelo_empresa).

Sem interface (testável fora do QGIS); a janela fica em inicio.py.
"""
import datetime as _dt
import json
import os
import re
import shutil
import unicodedata

try:
    from . import base_dados as BD
    from . import pastas as PA
    from . import edital_slu as E
    from . import empresa as EMP
    from . import projetos as P
    from .planos import documentos, estrutura, importacao, perfil as PF, validacao as V
except ImportError:  # testes
    import base_dados as BD
    import pastas as PA
    import edital_slu as E
    import empresa as EMP
    import projetos as P
    from planos import documentos, estrutura, importacao, perfil as PF, validacao as V

PASTA_TEXTOS = "textos"          # mesmo cache dos Planos do Contrato
ARQ_PERFIL = "contrato.json"
ARQ_ESCOLHAS = "criar_todos.json"

BLOQUEIA, ATENCAO, INFO = "bloqueia", "atenção", "info"
ICONE = {BLOQUEIA: "⛔", ATENCAO: "⚠️", INFO: "ℹ️"}

SECOES_PADRAO = ["Descrição do serviço", "Planejamento das rotas e frequências",
                 "Veículos utilizados", "Pessoal da operação", "Horários",
                 "Procedimentos operacionais", "Equipe e contatos-chave"]


def _mod(nome):
    """Módulo de planos/ (dentro do plugin ou nos testes)."""
    import importlib
    try:
        return importlib.import_module(f"{__package__}.planos.{nome}") if __package__ \
            else importlib.import_module(f"planos.{nome}")
    except ImportError:
        return importlib.import_module(f"planos.{nome}")


def _mod_raiz(nome):
    """Módulo da raiz do plugin (dentro do plugin ou nos testes)."""
    import importlib
    if __package__:
        return importlib.import_module(f"{__package__}.{nome}")
    return importlib.import_module(nome)


def _sa(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()


def _lote(v):
    """'Lote 01' → '1'; 'I' → 'I'."""
    s = str(v or "").strip()
    m = re.search(r"\d+", s)
    return str(int(m.group())) if m else s.replace("Lote", "").strip() or "1"


def _lote2(lote):
    return f"{int(lote):02d}" if str(lote).isdigit() else str(lote)


# ====================================================================== perfil
def eh_slu(p):
    if not p:
        return False
    c = json.dumps(p.get("contrato", {}), ensure_ascii=False)
    cods = [s.get("codigo") for s in p.get("servicos") or []]
    return "90005" in c and cods and all(x in E.SERVICOS for x in cods)


def _eh_edital_slu(textos):
    t = _sa(textos[:3_000_000])
    return "90005" in t and ("slu" in t or "limpeza urbana" in t)


def _ler_documentos(pasta, caminhos, progresso=None, cancelado=None):
    docs, erros = [], []
    cache = PA.arquivo(pasta, PASTA_TEXTOS, criar=True)
    for i, c in enumerate(caminhos):
        if cancelado and cancelado():
            break
        if progresso:
            progresso(f"Lendo {os.path.basename(c)} ({i + 1}/{len(caminhos)})…")
        if not c.lower().endswith(documentos.EXTENSOES):
            erros.append((c, "formato não lido (use PDF, DOCX ou TXT)"))
            continue
        try:
            docs.append(documentos.ler(c, cache))
        except Exception as e:
            erros.append((c, str(e)))
    return docs, erros


def escolhas(pasta):
    try:
        with open(PA.arquivo(pasta, ARQ_ESCOLHAS), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def guardar_escolhas(pasta, d):
    """Grava as escolhas (mescla com as que já estão no arquivo)."""
    tudo = escolhas(pasta)
    tudo.update(d)
    try:
        with open(PA.arquivo(pasta, ARQ_ESCOLHAS, criar=True), "w", encoding="utf-8") as f:
            json.dump(tudo, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ====================================================================== entregáveis
def entregaveis(p, servico):
    return [e for e in p.get("entregaveis") or []
            if not e.get("servicos") or servico in e["servicos"]]


def _ext(e):
    t = _sa((e.get("formato") or "") + " " + (e.get("nome_arquivo") or "") + " " + e.get("nome", ""))
    for ext, chaves in ((".gdb", ("gdb", "geodatabase")), (".gpkg", ("gpkg", "geopackage")),
                        (".shp", ("shp", "shapefile")), (".kml", ("kml", "kmz")),
                        (".docx", ("docx", "word", "texto")), (".xlsx", ("xlsx", "excel", "planilha")),
                        (".pdf", ("pdf",))):
        if any(c in t for c in chaves):
            return ext
    return ""


def arquivos_do_plano(p, servico, lote, sigla):
    """[(entregável, extensão, nome do arquivo)] que o edital pede para o plano."""
    out = []
    for e in entregaveis(p, servico):
        ext = _ext(e)
        if not ext:
            continue
        padrao = e.get("nome_arquivo") or ""
        if padrao:
            nome = (padrao.replace("{sigla}", sigla or servico).replace("{lote}", _lote2(lote))
                    .replace("{codigo}", servico).replace("{servico}", servico))
            if not os.path.splitext(nome)[1]:
                nome += ext
        else:
            base = f"{sigla or servico}{_lote2(lote)}"
            nome = {".docx": f"{servico}_{base}_plano_de_servico.docx",
                    ".xlsx": f"{base}_{_arq(e['nome'])}.xlsx"}.get(ext, base + ext)
        out.append((e, ext, nome))
    return out


def _arq(s):
    return "_".join(w for w in re.split(r"[^a-z0-9]+", _sa(s)) if w)[:40]


# ====================================================================== análise
def analisar(pasta, progresso=None, cancelado=None):
    esc = escolhas(pasta)
    # o que o app gera (planos criados, cache de textos) não é arquivo de entrada
    pular = [PA.raiz(pasta), os.path.join(pasta, "Planos"), os.path.join(pasta, PASTA_TEXTOS)]
    if esc.get("pasta_saida"):
        pular.append(esc["pasta_saida"])
    leitura = P.ler_pasta(pasta, pular=pular)
    A = {"pasta": pasta, "leitura": leitura, "edital": None, "perfil": None, "slu": False,
         "perfil_origem": "", "servicos": [], "lotes": [], "lotes_origem": "", "planos": [],
         "problemas": [], "documentos": [], "limite_df": _limite_local(leitura),
         "historico": _historico_candidatos(leitura), "empresa": None, "escaneados": [],
         "municipio": "", "uf": ""}
    prob = A["problemas"]

    def problema(nivel, codigo, titulo, detalhe, solucao, planos=None, acao=""):
        prob.append({"nivel": nivel, "codigo": codigo, "titulo": titulo, "detalhe": detalhe,
                     "solucao": solucao, "planos": planos or [], "acao": acao})

    # ------------------------------------------------------------ documentos
    docs, erros = _ler_documentos(pasta, leitura["documentos"], progresso, cancelado)
    for c, e in erros:
        if os.path.basename(c).lower().startswith(EMP.NOME):
            continue
        problema(ATENCAO, "documento_ilegivel", f"Não consegui ler {os.path.basename(c)}", e,
                 "Salve o arquivo em PDF ou DOCX (o .doc antigo não é lido).")
    escaneados = [d for d in docs if documentos.aviso_sem_texto(d)]
    for d in escaneados:
        nivel = BLOQUEIA if len(escaneados) == len(docs) else \
            (INFO if len(d["paginas"]) <= 3 else ATENCAO)
        problema(nivel, "escaneado", f"{d['nome']} parece escaneado (sem texto)",
                 f"{d['paginas_sem_texto']} de {len(d['paginas'])} páginas sem texto.",
                 "Clique em 'Ler escaneados com o Claude': ele lê as páginas como imagem "
                 "(≈ 10 s por página) e o texto passa a valer como o resto do edital.",
                 acao="ocr")
    A["escaneados"] = [d["caminho"] for d in escaneados]
    A["documentos"] = [{"caminho": d["caminho"], "paginas": len(d["paginas"]),
                        "sem_texto": bool(documentos.aviso_sem_texto(d))} for d in docs]
    textos = "\n".join("\n".join(d["paginas"]) for d in docs)

    # ------------------------------------------------------------ perfil do contrato
    arq_perfil = PA.arquivo(pasta, ARQ_PERFIL)
    p = None
    if os.path.exists(arq_perfil):
        try:
            p = PF.carregar(arq_perfil)
            A["perfil_origem"] = "contrato.json da pasta (lido do edital)"
        except (OSError, ValueError) as e:
            problema(ATENCAO, "perfil_com_erro", "contrato.json com erro", str(e),
                     "Ler o edital de novo com o Claude.", acao="ler_ia")
    if p is None and textos.strip() and _eh_edital_slu(textos):
        p = PF.perfil_slu_df()
        PA.contrato(pasta, criar=True)
        PF.salvar(p, arq_perfil)
        A["perfil_origem"] = "perfil pronto do SLU-DF (Pregão 90005/2026)"
    if p is None:
        if docs:
            problema(BLOQUEIA, "sem_perfil", "O edital ainda não foi lido",
                     "Para saber os planos que o contrato pede (serviços, lotes, arquivos, "
                     "camadas, frota e pessoal), o Claude precisa ler o edital e montar o "
                     "perfil do contrato. Leva de 5 a 20 minutos.",
                     "Clique em 'Ler o edital com o Claude' e depois em 'Analisar de novo'.",
                     acao="ler_ia")
        else:
            problema(BLOQUEIA, "sem_edital", "Não há edital na pasta",
                     "Sem o edital não dá para saber o que o contrato pede.",
                     "Coloque o edital e os anexos (PDF, DOCX ou TXT) na pasta.")
        return _fim(A)
    A["perfil"] = p
    A["slu"] = eh_slu(p)
    A["edital"] = p["contrato"].get("titulo") or p["contrato"].get("numero") or "Contrato"
    A["municipio"] = p["contrato"].get("municipio", "")
    A["uf"] = p["contrato"].get("uf", "")
    if A["slu"] and not A["municipio"]:           # perfil antigo do SLU, sem município
        A["municipio"], A["uf"] = "Brasília", "DF"

    # ------------------------------------------------------------ planos atuais da pasta
    bancos = [b for b in leitura["bancos"] if not b["erro"]]
    for b in leitura["bancos"]:
        if b["erro"]:
            problema(ATENCAO, "plano_ilegivel", f"{b['nome']} não abriu", b["erro"],
                     "Confira se o arquivo está inteiro (no .gdb, copiar a pasta toda).")
        b["servicos_perfil"] = estrutura.servicos_do_arquivo(p, b["caminho"])
        if not b.get("lote"):
            b["lote"] = _lote_do_nome(p, b)
        if b["circuitos"] and not b["servicos_perfil"]:
            problema(INFO, "plano_sem_servico", f"{b['nome']}: não sei de qual serviço é",
                     "O nome não começa com a sigla de um serviço do contrato.",
                     "Renomeie com a sigla e o lote (ex.: " + _exemplo_nome(p) + ").")

    # ------------------------------------------------------------ serviços e lotes
    lotes_perfil = [_lote(l["codigo"]) for l in p.get("lotes") or []] or ["1"]
    lotes_planos = sorted({str(b["lote"]) for b in bancos if b.get("lote") and b["circuitos"]})
    lotes_marcados = esc.get("lotes") or lotes_planos or lotes_perfil
    A["lotes"] = lotes_perfil
    A["lotes_marcados"] = lotes_marcados
    A["lotes_origem"] = ("sua escolha anterior" if esc.get("lotes") else
                         "planos atuais da pasta" if lotes_planos else "edital (todos os lotes)")
    if not esc.get("lotes") and not lotes_planos and len(lotes_perfil) > 1:
        problema(ATENCAO, "lote_indefinido", "Qual lote a empresa vai disputar?",
                 f"O edital tem {len(lotes_perfil)} lotes e a pasta não tem plano atual que "
                 "diga o lote. Estão todos marcados.",
                 "Desmarque os lotes que não vai disputar; a escolha fica guardada na pasta.")

    desmarcados = set(esc.get("desmarcados") or [])
    hoje = _dt.date.today()
    por_documento = not A["slu"] and bool(p.get("entregaveis"))
    if por_documento:
        # qualquer edital: um plano por DOCUMENTO exigido (que junta os serviços dele)
        _planos_por_entregavel(A, p, lotes_perfil, lotes_marcados, desmarcados, bancos, problema)
    for s in (p.get("servicos") or []) if not por_documento else []:
        cod, sigla = s["codigo"], s.get("sigla") or ""
        lotes_s = [_lote(x) for x in s.get("lotes") or []] or lotes_perfil
        arqs_base = arquivos_do_plano(p, cod, "1", sigla)
        exts = {ext for _, ext, _ in arqs_base}
        geo = next((x for x in (".gdb", ".gpkg", ".shp") if x in exts), "")
        cams = estrutura.camadas_exigidas(p, [cod])
        if A["slu"] and E.SERVICOS.get(cod, {}).get("grupo") != "sem_gdb":
            geo = geo or ".gdb"
        if not geo and cams:
            geo = ".gpkg"           # o edital pede camadas mas não diz o formato
        for lote in lotes_s:
            pid = f"{cod}-{lote}"
            mesmos = [b for b in bancos if cod in b["servicos_perfil"] and b["circuitos"]
                      and (str(b.get("lote") or "") == lote or len(lotes_s) == 1)]
            atual = max(mesmos, key=lambda b: (_modificado(b["caminho"]), b["circuitos"])) \
                if mesmos else None
            turnos = [t for t in ("Diurno", "Noturno") if atual and t in atual["turnos"]] or \
                sorted({t["nome"] for t in p.get("turnos") or [] if t.get("servico") == cod}) \
                or ["Diurno"]
            ruas = any(c["geometria"] == "linha" for c in cams) and not s.get("sob_demanda")
            pl = {"id": pid, "servico": cod, "sigla": sigla, "nome": s["nome"], "lote": lote,
                  "plano_existente": atual["caminho"] if atual else "",
                  "circuitos": atual["circuitos"] if atual else 0, "turnos": turnos,
                  "geo": geo, "osm": bool(geo and ruas and not atual),
                  "arquivos": [n for _, _, n in arquivos_do_plano(p, cod, lote, sigla)],
                  "marcado": lote in lotes_marcados and pid not in desmarcados,
                  "problemas": []}
            if not geo:
                pl["origem"] = "só documentos (o edital não pede camadas)"
            elif atual:
                pl["origem"] = f"plano atual {os.path.relpath(atual['caminho'], pasta)}"
            elif pl["osm"]:
                pl["origem"] = "vias do OpenStreetMap (sem circuitos ainda)"
            else:
                pl["origem"] = "novo, com as camadas do edital"
            if A["slu"] and cod in E.SERVICOS_TRIMESTRAIS:
                pl["origem"] += f" + programação {hoje.year} T{(hoje.month - 1) // 3 + 1}"
            A["planos"].append(pl)
            if len(mesmos) > 1:
                rel = lambda b: os.path.relpath(b["caminho"], pasta)  # noqa: E731
                problema(ATENCAO, "planos_repetidos",
                         f"{s['nome']} lote {lote}: {len(mesmos)} planos na pasta",
                         "; ".join(f"{rel(b)} ({b['circuitos']} circuitos, alterado em "
                                   f"{_dt.datetime.fromtimestamp(_modificado(b['caminho'])):%d/%m/%Y %H:%M})"
                                   for b in mesmos) + f". Vou usar o mais recente: {rel(atual)}.",
                         "Confira o escolhido ou deixe na pasta só o plano certo.", [pid])
    A["servicos"] = [s["codigo"] for s in p.get("servicos") or []]
    A["servicos_origem"] = A["perfil_origem"]

    # ------------------------------------------------------------ problemas gerais
    osm = [x["id"] for x in A["planos"] if x["osm"]]
    if osm:
        problema(ATENCAO, "sem_circuitos", "Planos sem plano atual: base do OpenStreetMap",
                 f"{len(osm)} plano(s) não têm plano atual na pasta. O app baixa as vias do "
                 "OpenStreetMap do município (com o limite do IBGE) e divide as vias em "
                 "setores automaticamente: um setor por veículo do edital, com a mesma carga "
                 "(km de vias). Ainda não há ordem de passagem (roteirização).",
                 "Revisar os setores no QGIS (limites, turno e frequência); colocar na pasta o "
                 "plano atual, se houver, para partir dele.",
                 osm)
        if not A["municipio"] or not A["uf"]:
            problema(ATENCAO, "sem_municipio", "Município do contrato não informado",
                     "Sem município e UF não dá para baixar o limite nem as vias.",
                     "Informe o município e a UF aqui embaixo.", osm, acao="municipio")
    dem = [x["id"] for x in A["planos"] if A["slu"]
           and E.SERVICOS.get(x["servico"], {}).get("grupo") == "demanda"]
    if dem and not A["limite_df"]:
        problema(INFO, "limite_baixado", "Planos sob demanda: limite do município",
                 "Os serviços sob demanda levam 1 polígono por turno cobrindo a área; sem a "
                 "camada das RAs na pasta, uso o limite do município baixado do IBGE.",
                 "Para dividir por lote, coloque na pasta a camada das RAs com o lote.", dem)

    A["empresa"] = EMP.arquivo(pasta)
    if not A["empresa"]:
        problema(ATENCAO, "sem_planilha_empresa", "Planilha da empresa não encontrada",
                 f"Sem a {EMP.NOME}, o texto sai com a frota e o pessoal do edital (veículos "
                 "identificados por código, ex.: CC01-D01) e sem contatos e procedimentos.",
                 "Clique em 'Planilha da empresa': o app monta a planilha com o que já está no "
                 "edital (veículos com código, pessoal, procedimentos de cada serviço, locais e "
                 "funções responsáveis). Depois complete os dados da empresa e salve.",
                 acao="empresa")
    com_base = [x["id"] for x in A["planos"] if x["plano_existente"]
                and any(r.get("servico") == x["servico"] and r.get("categoria") == "equipamento"
                        for r in p.get("recursos") or [])]
    if com_base:
        if A["historico"]:
            problema(INFO, "frota_jornada", "Frota e jornada serão adequadas ao edital",
                     f"Histórico de operação: {', '.join(os.path.basename(h) for h in A['historico'][:3])}. "
                     "Os planos atuais passam pela adequação (juntar/dividir circuitos, "
                     "turnos, jornada) antes de criar.",
                     "Confira o relatório de frota de cada plano.", com_base)
        else:
            problema(INFO, "frota_sem_historico", "Frota e jornada: sem histórico de operação",
                     "Sem a planilha de RDs (tempos e pesos por circuito) só dá para conferir o "
                     "número de veículos, não a jornada.",
                     "Coloque na pasta o histórico (ex.: TabelaPadrão.xlsx).", com_base)
    return _fim(A)


GEO_CHAVES = ("setoriz", "rota", "roteir", "mapa", "mapeamento", "georrefer", "trecho")
DOC_EMPRESA = ("documentacao", "licenca", "certid", "autorizac", "alvara", "atestado")
CAMADAS_GENERICAS = [
    ("setores", "MultiPolygon", ["codigo", "nome", "servico", "frequencia", "turno", "dias",
                                 "observacao"]),
    ("rotas", "MultiLineString", ["codigo", "setor", "servico", "turno", "ordem", "observacao"]),
    ("pontos", "Point", ["codigo", "tipo", "servico", "endereco", "observacao"]),
]


def tipo_entregavel(e):
    """('texto' | 'mapa' | 'planilha' | 'documentos', pede_mapa)."""
    nome = _sa(e.get("nome"))
    t = _sa(" ".join([e.get("nome") or "", e.get("formato") or "", e.get("descricao") or "",
                      e.get("como_fazer") or "", " ".join(e.get("secoes") or [])]))
    ext = _ext(e)
    geo = ext in (".gdb", ".gpkg", ".shp", ".kml")
    mapa = geo or any(k in t for k in GEO_CHAVES)
    if any(k in nome for k in DOC_EMPRESA):
        return "documentos", False
    if geo and not e.get("secoes"):
        return "mapa", True
    if ext == ".xlsx" or "planilha" in t or "arquivo editavel" in t or \
            nome.startswith(("relacao", "lista", "cadastro", "tabela")):
        return "planilha", mapa
    return "texto", mapa


def sigla_auto(s):
    """Sigla do serviço, ou um código a partir do item do edital (1.1 → S1.1)."""
    return (s.get("sigla") or "").strip() or f"S{s['codigo']}"


def _nome_arquivo(e, sigla, lote, padrao):
    pad = (e.get("nome_arquivo") or "").strip()
    if not pad:
        return padrao
    return (pad.replace("{sigla}", sigla).replace("{lote}", _lote2(lote))
            .replace("{codigo}", sigla).replace("{servico}", sigla))


ROTULO_VARRICAO = {"varricao": ("varricao_manual", "Varrição manual"),
                   "varricao_mec": ("varricao_mecanizada", "Varrição mecanizada")}


def _partes_por_lote(lotes, servs, lotes_de, serv):
    """(lote, serviços, parte) de cada plano. A varrição sempre sai em arquivos próprios
    (manual e mecanizada separadas), mesmo quando o edital pede um documento só para
    vários serviços; parte = (sufixo do arquivo, rótulo) ou None."""
    DMx = _mod_raiz("dimensionamento")
    for lote in lotes:
        sl = [c for c in servs if lote in lotes_de[c]]
        tipos = {c: DMx.tipo_servico(serv[c].get("nome")) for c in sl}
        varr = [c for c in sl if tipos[c] in ROTULO_VARRICAO]
        if not varr or len(sl) == 1:
            yield lote, sl, None
            continue
        outros = [c for c in sl if c not in varr]
        if outros:
            yield lote, outros, None
        repetido = len({tipos[c] for c in varr}) < len(varr)
        for c in varr:
            suf, rot = ROTULO_VARRICAO[tipos[c]]
            if repetido:
                suf, rot = f"{suf}_{_arq(c)}", f"{rot} ({c})"
            yield lote, [c], (suf, rot)


def _planos_por_entregavel(A, p, lotes_perfil, lotes_marcados, desmarcados, bancos, problema):
    """Um plano por conjunto de serviços dos documentos exigidos: os arquivos do edital para
    os mesmos serviços (texto, mapa, tabela) ficam juntos no mesmo plano."""
    serv = {s["codigo"]: s for s in p.get("servicos") or []}
    lotes_de = {c: [_lote(x) for x in s.get("lotes") or []] or lotes_perfil
                for c, s in serv.items()}
    grupos, cobertos, empresa_docs = {}, set(), []
    for k, e in enumerate(p.get("entregaveis") or []):
        tipo, mapa = tipo_entregavel(e)
        servs = [c for c in (e.get("servicos") or list(serv)) if c in serv] or list(serv)
        cobertos |= set(servs)
        if tipo == "documentos":
            empresa_docs.append(e["nome"])
            continue
        grupos.setdefault(tuple(sorted(servs, key=list(serv).index)), []).append((k, tipo, mapa))
    for gi, (servs, itens) in enumerate(grupos.items(), start=1):
        textos = [k for k, t, _ in itens if t == "texto"]
        nome = p["entregaveis"][(textos or [itens[0][0]])[0]]["nome"]
        pede_mapa = any(m for _, _, m in itens)
        lotes = sorted({lt for c in servs for lt in lotes_de[c]}, key=lambda x: (len(x), x))
        for lote, sl, parte in _partes_por_lote(lotes, servs, lotes_de, serv):
            pid = f"E{gi}-{lote}" + (f"-{parte[0]}" if parte else "")
            nome_pasta = (f"{gi:02d}_{parte[0]}_L{lote}" if parte
                          else f"{gi:02d}_{_arq(nome)[:45]}_L{lote}")
            sigla = sigla_auto(serv[sl[0]])
            atual = next((b for b in bancos if b["circuitos"] and
                          set(b.get("servicos_perfil") or []) & set(sl)), None)
            turnos = sorted({t["nome"] for t in p.get("turnos") or [] if t.get("servico") in sl}) \
                or ["Diurno"]
            arqs = []
            for k, t, _ in itens:
                e = p["entregaveis"][k]
                ext = {"texto": ".docx", "planilha": ".xlsx", "mapa": ".gpkg"}[t]
                a_ = _nome_arquivo(e, sigla, lote, f"{nome_pasta}{ext}"
                                   if t != "planilha" or len(itens) == 1 else
                                   f"{nome_pasta}_{_arq(e['nome'])[:30]}.xlsx")
                if parte and parte[0] not in a_:
                    b_, x_ = os.path.splitext(a_)
                    a_ = f"{b_}_{parte[0]}{x_}"
                arqs.append(a_)
            mapa_arq = next((a for a in arqs if a.lower().endswith(".gpkg")), None)
            if pede_mapa and not mapa_arq:
                mapa_arq = f"{nome_pasta}.gpkg"
                arqs.append(mapa_arq)
            pl = {"id": pid, "servico": sl[0], "servicos": sl, "sigla": "",
                  "nome": nome + (f" — {parte[1]}" if parte else ""),
                  "lote": lote, "plano_existente": atual["caminho"] if atual else "",
                  "circuitos": atual["circuitos"] if atual else 0, "turnos": turnos,
                  "geo": ".gpkg" if pede_mapa else "", "osm": bool(pede_mapa and not atual),
                  "entregaveis": [k for k, _, _ in itens], "entregavel": itens[0][0],
                  "tipos": {k: t for k, t, _ in itens}, "tipo": "texto" if textos else itens[0][1],
                  "pasta_nome": nome_pasta, "arquivos": arqs, "mapa_arquivo": mapa_arq,
                  "parte": parte[1] if parte else "",
                  "marcado": lote in lotes_marcados and pid not in desmarcados,
                  "problemas": []}
            partes = sorted({{"texto": "texto redigido do edital", "planilha": "planilha",
                              "mapa": "mapa"}[t] for _, t, _ in itens})
            itens_txt = ", ".join(sl[:6]) + ("…" if len(sl) > 6 else "")
            pl["origem"] = (" + ".join(partes)
                            + (" (vias do OpenStreetMap)" if pl["osm"] else "")
                            + f" · itens {itens_txt}")
            A["planos"].append(pl)
    fora = [c for c in serv if c not in cobertos]
    if fora:
        problema(INFO, "servicos_sem_documento", "Serviços sem documento exigido",
                 "O edital não pede plano/documento próprio para: "
                 + "; ".join(f"{c} {serv[c]['nome']}" for c in fora[:12])
                 + ("…" if len(fora) > 12 else "") + ".",
                 "Nada a fazer, a não ser que o órgão peça depois (entram no plano geral).")
    if empresa_docs:
        problema(INFO, "documentos_da_empresa", "Documentos que a empresa providencia",
                 "O edital também pede: " + "; ".join(empresa_docs) + ". Não são gerados pelo "
                 "app (licenças, autorizações, certidões).",
                 "Separe esses documentos com o setor administrativo.")


def _fim(A):
    for x in A["planos"]:
        x["problemas"] = [p["codigo"] for p in A["problemas"] if x["id"] in p["planos"]]
    ordem = {BLOQUEIA: 0, ATENCAO: 1, INFO: 2}
    A["problemas"].sort(key=lambda p: ordem[p["nivel"]])
    if not A["planos"] and not bloqueado(A):
        A["problemas"].insert(0, {"nivel": BLOQUEIA, "codigo": "nada_a_criar",
                                  "titulo": "O perfil não tem serviços",
                                  "detalhe": "Não há serviços no contrato.json.",
                                  "solucao": "Ler o edital de novo com o Claude.",
                                  "planos": [], "acao": "ler_ia"})
    return A


def _exemplo_nome(p):
    s = next((x for x in p.get("servicos") or [] if x.get("sigla")), None)
    return f"{s['sigla']}01.gdb" if s else "SIGLA01.gdb"


def _lote_do_nome(p, b):
    base = _sa(os.path.splitext(os.path.basename(b["caminho"]))[0])
    for s in p.get("servicos") or []:
        sig = _sa(s.get("sigla") or "")
        m = re.match(re.escape(sig) + r"[_\- ]?0*(\d+)", base) if sig else None
        if m:
            return str(int(m.group(1)))
    return None


def _limite_local(leitura):
    """Camada de limite/RAs da pasta (para os planos sob demanda)."""
    for b in leitura["bancos"]:
        n = _sa(os.path.basename(b["caminho"]))
        if not b["caminho"].lower().endswith(".gdb") and \
                any(k in n for k in ("regioes_administrativas", "limite", "municipio")):
            return b["caminho"]
    return None


def _historico_candidatos(leitura):
    out = []
    for c in leitura["planilhas"]:
        n = _sa(os.path.basename(c))
        if n.startswith(EMP.NOME) or n.startswith("criar_todos") or "conferencia" in n:
            continue
        if any(k in n for k in ("tabelapadrao", "tabela_padrao", "historico", "rds", "relatorio_diario", "operacao")):
            out.append(c)
    return out


def _modificado(caminho):
    try:
        if os.path.isdir(caminho):
            return max([os.path.getmtime(os.path.join(caminho, f)) for f in os.listdir(caminho)]
                       or [os.path.getmtime(caminho)])
        return os.path.getmtime(caminho)
    except OSError:
        return 0


def bloqueado(A):
    return any(p["nivel"] == BLOQUEIA for p in A["problemas"])


def preparar_planilha(A, progresso=None, cancelado=None, usar_claude=True, executar=None):
    """Planilha da empresa montada com o edital (o Claude lê procedimentos, locais e
    responsáveis nos trechos citados no perfil). Ver empresa.preencher_do_edital."""
    pasta = A["pasta"]
    cache = PA.arquivo(pasta, PASTA_TEXTOS, criar=True)
    docs = []
    for d in A.get("documentos") or []:
        try:
            docs.append(documentos.ler(d["caminho"], cache))
        except Exception:
            pass
    return EMP.preencher_do_edital(pasta, A["perfil"], docs, usar_claude=usar_claude,
                                   executar=executar,
                                   progresso=(lambda t: progresso(t)) if progresso else None)


def ler_escaneados(A, progresso=None, cancelado=None, executar=None):
    """OCR pelo Claude das páginas sem texto dos documentos escaneados da análise."""
    ocr = _mod("ocr")
    cache = PA.arquivo(A["pasta"], PASTA_TEXTOS, criar=True)
    res = []
    for c in A.get("escaneados") or []:
        if cancelado and cancelado():
            break
        r = ocr.ocr_documento(c, cache, progresso=progresso, cancelado=cancelado,
                              executar=executar)
        r.pop("doc", None)
        res.append(r)
    return res


# ====================================================================== criar
def criar(A, ids, pasta_saida, empresa="", validar=True, corrigir=True, frota=True,
          baixar=True, municipio=None, uf=None, progresso=None, cancelado=None,
          baixar_fn=None, redigir=True, executar_redacao=None):
    """Cria os planos escolhidos. Um erro num plano não para os outros."""
    if bloqueado(A):
        raise ValueError("Há problema que impede criar os planos: "
                         + "; ".join(p["titulo"] for p in A["problemas"] if p["nivel"] == BLOQUEIA))
    p, pasta = A["perfil"], A["pasta"]
    planos = [x for x in A["planos"] if x["id"] in set(ids)]
    guardar_escolhas(pasta, {"lotes": sorted({x["lote"] for x in planos}),
                             "pasta_saida": pasta_saida,
                             "desmarcados": [x["id"] for x in A["planos"] if x["id"] not in set(ids)
                                             and x["lote"] in {y["lote"] for y in planos}]})
    municipio = (municipio if municipio is not None else A.get("municipio")) or ""
    uf = (uf if uf is not None else A.get("uf")) or ""
    if (municipio, uf) != (p["contrato"].get("municipio"), p["contrato"].get("uf")) and \
            municipio and uf:
        p["contrato"]["municipio"], p["contrato"]["uf"] = municipio, uf
        PF.salvar(p, PA.arquivo(pasta, ARQ_PERFIL, criar=True))
    novos = []

    def aviso(nivel, codigo, titulo, detalhe, solucao, ids_=None):
        A["problemas"] = [x for x in A["problemas"] if x["codigo"] != codigo]
        novos.append({"nivel": nivel, "codigo": codigo, "titulo": titulo, "detalhe": detalhe,
                      "solucao": solucao, "planos": ids_ or [], "acao": ""})

    def prog(txt, i=0, n=0):
        if progresso:
            progresso(txt, i, n)

    # ------------------------------------------------------------ empresa
    if not EMP.arquivo(pasta) and not A["slu"]:
        # qualquer edital: a planilha sai do edital (frota, pessoal, procedimentos, locais)
        prog("Montando a planilha da empresa com o edital…")
        try:
            preparar_planilha(A, progresso=prog,
                              usar_claude=redigir and executar_redacao is None)
        except Exception:
            pass
    if not EMP.arquivo(pasta):
        serv = {s["codigo"]: s for s in p.get("servicos") or []}
        pares = []
        for x in planos:
            for c in x.get("servicos") or [x["servico"]]:
                par = (c, x["lote"], x["sigla"] or sigla_auto(serv.get(c, {"codigo": c})))
                if par not in pares:
                    pares.append(par)
        EMP.criar_modelo(pasta, p, pares)
    if EMP.arquivo(pasta):
        EMP.completar_empresa_na_planilha(EMP.arquivo(pasta))
    emp = EMP.ler(pasta)
    EMP.aprender_empresa(emp)
    if not emp["contatos"] and not emp["procedimentos"]:
        aviso(ATENCAO, "planilha_empresa_vazia", "Planilha da empresa sem contatos e procedimentos",
              f"O texto saiu sem essas seções. Arquivo: {os.path.basename(emp['arquivo'] or '')}.",
              "Preencha as abas Contatos e Procedimentos e crie de novo.",
              [x["id"] for x in planos])
    empresa = empresa or EMP.nome_empresa(emp)

    # ------------------------------------------------------------ base (IBGE / OSM)
    A["_cancelado"] = cancelado
    A["_baixar_fn"] = baixar_fn
    A["_baixar"] = baixar
    limite, vias = _baixar_base(A, planos, municipio, uf, baixar, baixar_fn, prog, cancelado,
                                aviso)

    # ------------------------------------------------------------ histórico (frota/jornada)
    hist, hist_arq = None, ""
    if frota and A.get("historico") and any(x["plano_existente"] for x in planos):
        H = _mod("historico")
        for c in A["historico"]:
            prog(f"Lendo o histórico de operação {os.path.basename(c)}…")
            try:
                h = H.ler(c, cache=PA.arquivo(pasta, "historico_cache.json", criar=True))
                if h and h.get("circuitos"):
                    hist, hist_arq = h, c
                    break
            except Exception:
                continue

    # ------------------------------------------------------------ textos do edital (redação)
    docs = []
    if any(x.get("entregavel") is not None for x in planos):
        cache = PA.arquivo(pasta, PASTA_TEXTOS, criar=True)
        for d in A.get("documentos") or []:
            try:
                docs.append(documentos.ler(d["caminho"], cache))
            except Exception:
                pass

    # ------------------------------------------------------------ cada plano
    res = []
    for i, pl in enumerate(planos):
        if cancelado and cancelado():
            break
        prog(f"Criando {pl['nome']} lote {pl['lote']} ({i + 1}/{len(planos)})…", i, len(planos))
        r = {"id": pl["id"], "servico": pl["servico"], "nome": pl["nome"], "lote": pl["lote"],
             "origem": pl["origem"]}
        try:
            if pl.get("entregavel") is not None:
                out = _criar_entregavel(A, pl, pasta_saida, empresa, emp, docs, redigir,
                                        executar_redacao, validar, corrigir, prog, limite)
            elif A["slu"]:
                out = _criar_slu(A, pl, pasta_saida, empresa, emp, validar, corrigir,
                                 hist if frota else None, limite)
            else:
                out = _criar_generico(A, pl, pasta_saida, empresa, emp, validar, corrigir,
                                      hist if frota else None)
            if vias and pl["osm"]:
                out.setdefault("arquivos", {})["base_vias_osm"] = vias["arquivo"]
            r.update(ok=True, **{k: out.get(k) for k in ("pasta", "arquivos", "validacao",
                                                         "correcao", "frota", "aviso",
                                                         "a_definir", "redigido", "setores",
                                                         "setores_total", "dimensionamento")},
                     pendentes=out.get("secoes_docx_a_preencher") or [])
        except Exception as e:
            r.update(ok=False, erro=f"{type(e).__name__}: {e}")
        res.append(r)

    com_erro = [r for r in res if r.get("ok") and (r.get("validacao") or {}).get("erros")]
    if com_erro:
        aviso(ATENCAO, "conferencia_com_erros", "Planos com erros na conferência do edital",
              "; ".join(f"{r['nome']} lote {r['lote']}: {r['validacao']['erros']} erros"
                        for r in com_erro) + ". Os planos foram criados assim mesmo.",
              "Abrir a planilha de conferência de cada plano e corrigir o que a correção "
              "automática não resolveu (geometria, circuito fora do lote, sobreposição…).",
              [r["id"] for r in com_erro])
    sem_red = [r for r in res if r.get("ok") and r.get("redigido") is False]
    if sem_red:
        aviso(ATENCAO, "redacao_falhou", "O Claude não redigiu alguns textos",
              f"{len(sem_red)} documento(s) saíram só com o que dá por regras (frota, pessoal). "
              + (sem_red[0].get("aviso") or ""),
              "Confira a conta Claude (Configurar IA) e crie de novo esses planos.",
              [r["id"] for r in sem_red])
    a_def = sum(r.get("a_definir") or 0 for r in res)
    if a_def:
        aviso(INFO, "a_definir", f"{a_def} ponto(s) [A DEFINIR] nos textos",
              "São informações que o edital não traz (horários, garagem, responsáveis, "
              "cronograma da contratante…). Estão em vermelho no .docx.",
              "Complete na planilha da empresa (contatos, procedimentos) ou direto no .docx.",
              [r["id"] for r in res if r.get("a_definir")])
    if vias:
        aviso(INFO, "vias_baixadas", "Vias do OpenStreetMap baixadas",
              f"{vias['vias']} trechos, {vias['km']} km, em {os.path.relpath(vias['arquivo'], pasta)}.",
              "Base dos circuitos (setores e ordem de passagem).",
              [x["id"] for x in planos if x["osm"]])
    if hist_arq:
        aviso(INFO, "frota_feita", "Frota e jornada adequadas com o histórico",
              f"Histórico: {os.path.basename(hist_arq)}.",
              "Veja a planilha de frota em cada plano (pontos para levar ao órgão).",
              [r["id"] for r in res if r.get("frota")])
    A["problemas"] += novos
    rel = relatorio(A, res, PA.relatorios(pasta, criar=True))
    return {"planos": res, "relatorio": rel, "empresa": emp.get("arquivo"),
            "ok": sum(1 for r in res if r.get("ok")),
            "falhas": sum(1 for r in res if not r.get("ok"))}


# ------------------------------------------------------------------ frota
def _frota(A, pl, origem, destino, hist, pasta_plano):
    """Adequação de frota e jornada do plano atual, gravada direto na cópia do plano."""
    F = _mod("frota")
    p = A["perfil"]
    pr = F.propor(p, origem, [pl["servico"]], historico=hist, redimensionar=True)
    gravado = F.aplicar(p, origem, pr, destino)
    rel = os.path.join(pasta_plano, f"frota_{pl['sigla'] or pl['servico']}{_lote2(pl['lote'])}.xlsx")
    F.relatorio_xlsx(pr, rel)
    cab = pr.get("cabe")
    return {"relatorio": rel, "cabe": cab, "pontos": len(pr.get("pontos") or []),
            "operacoes": gravado.get("operacoes") if isinstance(gravado, dict) else None}


# ------------------------------------------------------------------ SLU (Anexo G)
def _criar_slu(A, pl, pasta_saida, empresa, emp, validar, corrigir, hist, limite):
    s, lote = pl["servico"], int(pl["lote"])
    p = A["perfil"]
    banco = next((b for b in A["leitura"]["bancos"] if b["caminho"] == pl["plano_existente"]),
                 None)
    textos = P.textos_sugeridos(s, lote, pl["turnos"], banco)
    da_empresa = EMP.textos(p, s, lote, pl["sigla"], pl["turnos"], emp,
                            [t for t, _ in E.SECOES_DOCX])
    textos.update({t: v for t, v in da_empresa.items()       # o resto já vem do Anexo G/R
                   if EMP.secao_chave(t) in ("veiculos", "pessoal", "contatos", "procedimentos",
                                             "horarios")})
    pe = pl["plano_existente"]
    info_frota = None
    if pe and E.SERVICOS[s]["grupo"] != "sem_gdb":
        rot = E.lote_codigo(s, lote)
        pasta_plano = os.path.join(pasta_saida, f"{s}_{rot}")
        destino = os.path.join(pasta_plano, f"{rot}.gdb")
        if not os.path.exists(destino):
            os.makedirs(pasta_plano, exist_ok=True)
            if hist is not None and (s, lote) in E.FROTA_ANEXO_R:
                try:
                    info_frota = _frota(A, pl, pe, destino, hist, pasta_plano)
                except Exception as e:
                    info_frota = {"falhou": str(e)}
                    if os.path.exists(destino):
                        shutil.rmtree(destino, ignore_errors=True)
            if not os.path.exists(destino):
                shutil.copytree(pe, destino, ignore=shutil.ignore_patterns("*.lock"))
        pe = destino
    det = {"servico": s, "nome": pl["nome"], "lote": lote, "empresa": empresa,
           "plano_existente": pe, "turnos": pl["turnos"], "pasta_saida": pasta_saida,
           "validar": validar and bool(pe), "corrigir": corrigir, "textos": textos}
    out = P.criar_plano(det, carregar=False,
                        limite_df=limite if E.SERVICOS[s]["grupo"] == "demanda" else None)
    out["frota"] = info_frota
    return out


# ------------------------------------------------------------------ qualquer edital
def _criar_generico(A, pl, pasta_saida, empresa, emp, validar, corrigir, hist):
    p = A["perfil"]
    s, lote, sigla = pl["servico"], pl["lote"], pl["sigla"]
    pasta_plano = os.path.join(pasta_saida, f"{s}_{sigla or s}{_lote2(lote)}")
    os.makedirs(pasta_plano, exist_ok=True)
    arqs = {}
    out = {"pasta": pasta_plano, "arquivos": arqs, "validacao": None, "correcao": None,
           "frota": None}
    lista = arquivos_do_plano(p, s, lote, sigla)
    geo_nome = next((n for _, ext, n in lista if ext in (".gdb", ".gpkg", ".shp")), None)
    if pl["geo"] and not geo_nome:
        geo_nome = f"{sigla or s}{_lote2(lote)}{pl['geo']}"
    plano = None
    if geo_nome:
        ext = os.path.splitext(geo_nome)[1].lower()
        trabalho = os.path.join(pasta_plano, os.path.splitext(geo_nome)[0]
                                + (".gpkg" if ext == ".shp" else ext))
        if not os.path.exists(trabalho):
            base = pl["plano_existente"]
            if base and os.path.splitext(base)[1].lower() == os.path.splitext(trabalho)[1].lower():
                if hist is not None:
                    try:
                        out["frota"] = _frota(A, pl, base, trabalho, hist, pasta_plano)
                    except Exception as e:
                        out["frota"] = {"falhou": str(e)}
                if not os.path.exists(trabalho):
                    (shutil.copytree if os.path.isdir(base) else shutil.copy2)(base, trabalho)
            elif base:
                importacao.criar_plano(p, trabalho, [s])
                out["aviso"] = (f"O plano atual {os.path.basename(base)} está em outro formato; "
                                "o plano saiu vazio — traga os dados em Planos do Contrato → "
                                "5. Trazer dados.")
            else:
                importacao.criar_plano(p, trabalho, [s])
        else:
            out["aviso"] = f"Já havia {os.path.basename(trabalho)}; foi mantido."
        plano = trabalho
        if corrigir:
            rel = estrutura.completar_plano(p, plano, [s], backup=False)
            out["correcao"] = {"camadas_criadas": rel["camadas_criadas"],
                               "campos_criados": rel["campos_criados"],
                               "preenchidos": rel["preenchidos"]}
        arqs["plano"] = plano
        if ext == ".shp":
            arqs["shapefile"] = _exportar_shp(plano, os.path.join(pasta_plano, "shapefile"))
        if validar:
            v = V.validar(p, plano, [s])
            rv = os.path.join(pasta_plano, f"{sigla or s}{_lote2(lote)}_conferencia.xlsx")
            V.relatorio_xlsx(v, rv)
            arqs["xlsx_conferencia"] = rv
            out["validacao"] = {"erros": v["resumo"]["erros"], "avisos": v["resumo"]["avisos"],
                                "circuitos": v["resumo"].get("feicoes_lidas"), "relatorio": rv}
    pend = []
    for e, ext, nome in lista:
        destino = os.path.join(pasta_plano, nome)
        if ext == ".xlsx" and plano:
            _tabela_atributos(plano, destino)
            arqs[f"xlsx:{e['nome']}"] = destino
        elif ext == ".docx":
            secoes = e.get("secoes") or SECOES_PADRAO
            txt = EMP.textos(p, s, lote, sigla, pl["turnos"], emp, secoes)
            pend += [t for t in secoes if not txt.get(t)]
            _docx(destino, p, pl, empresa, secoes, txt, e.get("como_fazer") or "", plano)
            arqs[f"docx:{e['nome']}"] = destino
    if not any(k.startswith("docx") for k in arqs):          # o texto sempre acompanha
        destino = os.path.join(pasta_plano, f"{s}_{sigla or s}{_lote2(lote)}_plano.docx")
        txt = EMP.textos(p, s, lote, sigla, pl["turnos"], emp, SECOES_PADRAO)
        pend += [t for t in SECOES_PADRAO if not txt.get(t)]
        _docx(destino, p, pl, empresa, SECOES_PADRAO, txt, "", plano)
        arqs["docx"] = destino
    out["secoes_docx_a_preencher"] = pend
    return out



# ====================================================================== base do município
def _baixar_base(A, planos, municipio, uf, baixar=True, baixar_fn=None, prog=None,
                 cancelado=None, aviso=None):
    """Limite (IBGE) e vias (OSM) quando algum plano precisa. Devolve (limite, vias)."""
    prog = prog or (lambda *a, **k: None)
    aviso = aviso or (lambda *a, **k: None)
    pasta = A["pasta"]
    p = A["perfil"]
    limite, vias = A.get("limite_df"), None
    precisa_osm = [x for x in planos if x["osm"]]
    precisa_lim = precisa_osm or [x for x in planos if A["slu"] and
                                  E.SERVICOS.get(x["servico"], {}).get("grupo") == "demanda"]
    if baixar and precisa_lim and not limite:
        if municipio and uf:
            prog(f"Baixando o limite de {municipio}/{uf} (IBGE)…")
            try:
                kw = {"baixar": baixar_fn} if baixar_fn else {}
                limite = BD.limite_municipio(pasta, municipio.split(";")[0].strip(), uf, **kw)
            except Exception as e:
                aviso(ATENCAO, "falha_ibge", "Não consegui baixar o limite do IBGE", str(e),
                      "Confira o município/UF e a internet, ou coloque o limite na pasta.",
                      [x["id"] for x in precisa_lim])
    if baixar and precisa_osm and limite:
        try:
            kw = {"baixar": baixar_fn} if baixar_fn else {}
            vias = BD.vias_osm(pasta, limite, epsg=PF.epsg(p), progresso=prog,
                               cancelado=cancelado, **kw)
        except Exception as e:
            aviso(ATENCAO, "falha_osm", "Não consegui baixar as vias do OpenStreetMap", str(e),
                  "Tente de novo mais tarde (o servidor do OSM às vezes fica ocupado).",
                  [x["id"] for x in precisa_osm])
    A["_vias"] = vias["arquivo"] if vias else None
    A["_limite"] = limite
    return limite, vias


def territorio(A, baixar=True, baixar_fn=None, progresso=None, aviso=None, setores_fonte=None):
    """Território (vias em trechos, setores do IBGE com população, bairros) para a
    setorização. Baixa os setores do IBGE e os bairros do OSM na 1ª vez. Fica em
    A["_territorio"]."""
    if A.get("_territorio") is not None:
        return A["_territorio"]
    baixar_fn = baixar_fn or A.get("_baixar_fn")
    baixar = baixar and A.get("_baixar", True)
    vias, limite = A.get("_vias"), A.get("_limite")
    if not vias or not limite:
        return None
    prog = progresso or (lambda *a, **k: None)
    aviso = aviso or (lambda *a, **k: None)
    TE = _mod_raiz("territorio")
    pasta = A["pasta"]
    epsg = TE.epsg_de(vias)
    base = PA.base(pasta, criar=True)
    setores = os.path.join(base, "setores_ibge.gpkg")
    # (com um baixador de teste no lugar da internet, os setores só vêm de setores_fonte)
    if baixar and not os.path.exists(setores) and (baixar_fn is None or setores_fonte):
        prog("Baixando os setores censitários do IBGE (população por quarteirão)…")
        try:
            BD.setores_ibge(pasta, limite, epsg=epsg, fonte=setores_fonte)
        except Exception as e:
            aviso(INFO, "falha_setores", "Sem a população do IBGE",
                  f"Não consegui baixar os setores censitários: {e}",
                  "A divisão usa só os km de vias (sem a população de cada bairro).")
    pontos = os.path.join(base, "bairros_osm.gpkg")
    if baixar and not os.path.exists(pontos):
        prog("Baixando os bairros do OpenStreetMap…")
        try:
            kw = {"baixar": baixar_fn} if baixar_fn else {}
            BD.bairros_osm(pasta, limite, epsg=epsg, **kw)
        except Exception as e:
            aviso(INFO, "falha_bairros", "Sem os bairros do OpenStreetMap", str(e),
                  "Os circuitos são divididos sem seguir bairros.")
    prog("Montando bairros e vias do município…")
    p = A["perfil"]
    textos = " ; ".join((s_.get("frequencia") or "") for s_ in p.get("servicos") or []
                        if "domicil" in _sa(s_.get("nome")))
    T = TE.Territorio(vias, limite, setores if os.path.exists(setores) else None,
                      os.path.join(base, "bairros.gpkg"),
                      pontos if os.path.exists(pontos) else None,
                      municipio=p["contrato"].get("municipio") or "", texto_frequencia=textos)
    A["_territorio"] = T
    return T


def servicos_setorizaveis(A, ids=None):
    """[(servico, lote, nome)] dos planos marcados que terão circuitos (mapa sem camadas
    definidas pelo edital, vias do OSM)."""
    DM = _mod_raiz("dimensionamento")
    p = A["perfil"]
    serv = {s_["codigo"]: s_ for s_ in p.get("servicos") or []}
    out = []
    for x in A["planos"]:
        if ids is not None and x["id"] not in set(ids):
            continue
        if x.get("entregavel") is None or not x.get("osm"):
            continue
        servs = x.get("servicos") or [x["servico"]]
        if estrutura.camadas_exigidas(p, servs):
            continue
        for c in servs:
            if DM.tipo_servico(serv.get(c, {}).get("nome")) and \
                    (c, x["lote"]) not in [(a, b) for a, b, _ in out]:
                out.append((c, x["lote"], serv.get(c, {}).get("nome", "")))
    return out


def dimensionamento_salvo(pasta):
    return escolhas(pasta).get("dimensionamento") or {}


def guardar_dimensionamento(pasta, params):
    guardar_escolhas(pasta, {"dimensionamento": params})


def parametros(A, servico, lote):
    """Parâmetros do serviço: os salvos pelo usuário ou os do edital."""
    DM = _mod_raiz("dimensionamento")
    salvo = dimensionamento_salvo(A["pasta"]).get(f"{servico}|{lote}")
    if salvo:
        return DM.converter(salvo)
    if "_qtds" not in A:
        A["_qtds"] = DM.quantidades_edital(A["pasta"])
    return DM.padrao(A["perfil"], servico, lote, qtds=A["_qtds"])


def dimensionar(A, ids=None, municipio=None, uf=None, params=None, baixar=True, baixar_fn=None,
                progresso=None, cancelado=None, setores_fonte=None):
    """A análise ANTES de criar: baixa a base (se precisar) e calcula, para cada serviço,
    o nº de circuitos por bairro com os parâmetros (os da tela, os salvos ou os do
    edital). Devolve {"servicos": [...], "avisos": [...], "bairros": arquivo}."""
    SZ = _mod_raiz("setorizacao")
    DM = _mod_raiz("dimensionamento")
    avisos = []

    def aviso(nivel, codigo, titulo, detalhe, solucao, ids_=None):
        avisos.append(f"{titulo}: {detalhe} — {solucao}")

    p = A["perfil"]
    municipio = municipio or A.get("municipio") or p["contrato"].get("municipio") or ""
    uf = uf or A.get("uf") or p["contrato"].get("uf") or ""
    planos = [x for x in A["planos"] if ids is None or x["id"] in set(ids)]
    if not A.get("_vias"):
        _baixar_base(A, planos, municipio, uf, baixar, baixar_fn, progresso, cancelado, aviso)
    T = territorio(A, baixar, baixar_fn, progresso, aviso, setores_fonte)
    out = []
    for c, lote, nome in servicos_setorizaveis(A, ids):
        chave = f"{c}|{lote}"
        par = (params or {}).get(chave) or parametros(A, c, lote)
        if not par:
            continue
        par = DM.converter(par)
        item = {"chave": chave, "servico": c, "lote": lote, "nome": nome, "par": par,
                "conta": DM.resumo_parametros(par), "plano": None}
        if T is not None:
            pl = SZ.planejar(T, par["tipo"], par)
            item["plano"] = {
                "circuitos": pl["circuitos"], "slots": pl["slots"],
                "slots_usados": pl.get("slots_usados"), "km_vias": pl["km_vias"],
                "cap_km": pl["cap_km"], "cap_t": pl["cap_t"], "alertas": pl["alertas"],
                "ocupacao": pl.get("ocupacao"),
                "grupos": [{"bairros": g["nomes"], "freq": g["freq"], "n": g["n"],
                            "km": g["km"], "km_circ": g["km"] / max(1, g["n"]),
                            "t_circ": g.get("t_circ")} for g in pl["grupos"]]}
        out.append(item)
    return {"servicos": out, "avisos": avisos, "territorio": T is not None,
            "bairros": os.path.join(PA.base(A["pasta"]), "bairros.gpkg"),
            "fonte_bairros": getattr(T, "fonte_bairros", "") if T is not None else ""}


# ------------------------------------------------------------------ documento do edital
def _criar_entregavel(A, pl, pasta_saida, empresa, emp, docs, redigir, executar, validar,
                      corrigir, prog, limite):
    """Os documentos que o edital pede para um conjunto de serviços (ex.: Plano de Trabalho
    Operacional dos itens 1.1 a 1.5): texto .docx com as seções do edital (redigido pelo
    Claude), mapa .gpkg (camadas do edital ou setores/rotas/pontos) e planilhas .xlsx."""
    p = A["perfil"]
    serv = {s["codigo"]: s for s in p.get("servicos") or []}
    servs, lote = pl["servicos"], pl["lote"]
    pasta_plano = os.path.join(pasta_saida, pl["pasta_nome"])
    os.makedirs(pasta_plano, exist_ok=True)
    arqs = {}
    out = {"pasta": pasta_plano, "arquivos": arqs, "validacao": None, "correcao": None,
           "frota": None, "secoes_docx_a_preencher": [], "redigido": None, "a_definir": 0}
    nomes = dict(zip(pl["entregaveis"], pl["arquivos"]))

    # mapa: camadas do edital para estes serviços, ou setores/rotas/pontos
    plano, cams = None, []
    if pl.get("mapa_arquivo"):
        plano = os.path.join(pasta_plano, pl["mapa_arquivo"])
        if os.path.splitext(plano)[1].lower() not in (".gpkg", ".gdb"):
            plano = os.path.splitext(plano)[0] + ".gpkg"
        cams = estrutura.camadas_exigidas(p, servs)
        if not os.path.exists(plano):
            base = pl.get("plano_existente")
            if base and os.path.splitext(base)[1].lower() == os.path.splitext(plano)[1].lower():
                (shutil.copytree if os.path.isdir(base) else shutil.copy2)(base, plano)
            elif cams:
                importacao.criar_plano(p, plano, servs)
            else:
                _gpkg_generico(plano, _epsg_area(p, limite))
        if not cams and A.get("_vias") and limite:
            out.update(_circuitos(A, pl, plano, pasta_plano, prog))
            if out.get("xlsx_circuitos"):
                arqs["xlsx_circuitos"] = out.pop("xlsx_circuitos")
        if cams and corrigir:
            rel = estrutura.completar_plano(p, plano, servs, backup=False)
            out["correcao"] = {"camadas_criadas": rel["camadas_criadas"],
                               "preenchidos": rel["preenchidos"]}
        if cams and validar:
            v = V.validar(p, plano, servs)
            rv = os.path.join(pasta_plano, os.path.splitext(os.path.basename(plano))[0]
                              + "_conferencia.xlsx")
            V.relatorio_xlsx(v, rv)
            arqs["xlsx_conferencia"] = rv
            out["validacao"] = {"erros": v["resumo"]["erros"], "avisos": v["resumo"]["avisos"]}
        arqs["mapa"] = plano

    veic = []
    for c in servs:
        veic += EMP.veiculos_do_edital(p, c, lote, sigla_auto(serv[c]))
    pend, a_def = [], 0
    for k in pl["entregaveis"]:
        e = p["entregaveis"][k]
        tipo = pl["tipos"][k]
        destino = os.path.join(pasta_plano, nomes[k])
        if tipo == "mapa":
            continue
        if tipo == "planilha":
            destino = os.path.splitext(destino)[0] + ".xlsx"
            if plano and cams:
                _tabela_atributos(plano, destino)          # tabela das camadas do plano
            else:
                _planilha_entregavel(destino, e, [serv[c] for c in servs])
            arqs[f"xlsx:{e['nome']}"] = destino
            continue
        # texto: seções do edital; o Claude redige a partir das páginas do edital
        secoes = e.get("secoes") or SECOES_PADRAO
        txt = {}
        for c in servs:                    # base por regras (frota, pessoal, horários…)
            for t, v in EMP.textos(p, c, lote, sigla_auto(serv[c]), pl["turnos"], emp,
                                   secoes).items():
                bloco = f"{c} {serv[c]['nome']}:\n{v}" if len(servs) > 1 else v
                txt[t] = (txt[t] + "\n\n" + bloco) if t in txt else bloco
        if redigir:
            prog(f"Claude redigindo \"{e['nome'][:60]}\" (lote {lote})…")
            try:
                red = _mod("redacao").redigir(
                    p, e, servs, lote, docs, emp, secoes,
                    veiculos=[{x: v[x] for x in ("identificacao", "tipo", "turno")}
                              for v in veic],
                    nome_empresa=empresa, executar=executar)
                txt.update(red)
                out["redigido"] = True
            except Exception as ex:
                out["redigido"] = False
                out["aviso"] = (f"O Claude não redigiu o texto ({ex}); saiu só o que dá por "
                                "regras.")
        destino = os.path.splitext(destino)[0] + ".docx"
        sub = f"Lote {lote}" + (f" — {empresa}" if empresa else "")
        itens = "Serviços: " + "; ".join(f"{c} {serv[c]['nome']}" for c in servs) + "."
        res_c = {c: A["_setorizados"][(c, lote)] for c in servs
                 if (A.get("_setorizados") or {}).get((c, lote))}
        _docx(destino, p, pl, empresa, secoes, txt, e.get("como_fazer") or "", plano,
              titulo=e["nome"] + (f" — {pl['parte']}" if pl.get("parte") else ""),
              subtitulo=sub, abertura=itens, circuitos=res_c,
              nomes_servicos={c: serv[c]["nome"] for c in servs})
        arqs[f"docx:{e['nome']}"] = destino
        pend += [t for t in secoes if not str(txt.get(t) or "").strip()]
        a_def += sum(str(v).count("[A DEFINIR") for v in txt.values())
    out["secoes_docx_a_preencher"] = pend
    out["a_definir"] = a_def
    return out


def _circuitos(A, pl, plano, pasta_plano, prog=None):
    """Dimensionamento → circuitos por bairro → ordem de passagem, gravados no mapa do
    plano (camadas setores e rotas) + planilha <plano>_circuitos.xlsx."""
    prog = prog or (lambda *a, **k: None)
    p = A["perfil"]
    serv = {s_["codigo"]: s_ for s_ in p.get("servicos") or []}
    servs, lote = pl.get("servicos") or [pl["servico"]], pl["lote"]
    out = {}
    prog(f"Dimensionando e dividindo os circuitos ({pl['nome'][:50]}, lote {lote})…")
    try:
        SZ = _mod_raiz("setorizacao")
        T = territorio(A, progresso=prog)
        if T is None:
            raise ValueError("sem vias/limite do município")
        params = {c: parametros(A, c, lote) for c in servs}
        params = {c: v for c, v in params.items() if v}
        # o mesmo serviço pode estar em mais de um documento: calcula uma vez só
        cache = A.setdefault("_setorizados", {})
        faltam = [c for c in params if (c, lote) not in cache]
        if faltam:
            novos = SZ.setorizar(p, faltam, lote, T, params, rotear=True,
                                 progresso=prog, cancelado=A.get("_cancelado"))
            for c in faltam:
                cache[(c, lote)] = novos.get(c)
        res = {c: cache[(c, lote)] for c in params if cache.get((c, lote))}
        n = SZ.gravar(plano, p, res) if res else 0
        if res:
            xl = os.path.join(pasta_plano, os.path.splitext(os.path.basename(plano))[0]
                              + "_circuitos.xlsx")
            SZ.planilha(xl, res, {c: serv[c]["nome"] for c in res})
            out["xlsx_circuitos"] = xl
        out["setores"] = {c: len(r["circuitos"]) for c, r in res.items()}
        out["setores_total"] = n
        out["dimensionamento"] = SZ.resumo(res)
        al = [f"{c}: {x}" for c, r in res.items() for x in r["plano"]["alertas"]]
        if al:
            out["aviso"] = " | ".join(al)
    except InterruptedError:
        raise
    except Exception as ex:
        out["aviso"] = f"Não consegui dividir em circuitos: {ex}"
    return out


def refazer_circuitos(A, ids=None, municipio=None, uf=None, progresso=None, cancelado=None):
    """Refaz só os circuitos (setores, rotas, planilha de circuitos) nos mapas dos planos
    já criados, sem mexer nos textos. Usa o dimensionamento salvo."""
    p = A["perfil"]
    municipio = municipio or A.get("municipio") or p["contrato"].get("municipio") or ""
    uf = uf or A.get("uf") or p["contrato"].get("uf") or ""
    planos = [x for x in A["planos"] if ids is None or x["id"] in set(ids)]
    A["_cancelado"] = cancelado
    A.pop("_setorizados", None)
    if not A.get("_vias"):
        _baixar_base(A, planos, municipio, uf, True, None, progresso, cancelado)
    pasta_saida = escolhas(A["pasta"]).get("pasta_saida") or PA.planos(A["pasta"])
    res = []
    for pl in planos:
        if pl.get("entregavel") is None or not pl.get("mapa_arquivo"):
            continue
        servs = pl.get("servicos") or [pl["servico"]]
        if estrutura.camadas_exigidas(p, servs):
            continue
        pasta_plano = os.path.join(pasta_saida, pl["pasta_nome"])
        plano = os.path.join(pasta_plano, pl["mapa_arquivo"])
        if os.path.splitext(plano)[1].lower() != ".gpkg":
            plano = os.path.splitext(plano)[0] + ".gpkg"
        if not os.path.exists(plano):
            continue
        r = _circuitos(A, pl, plano, pasta_plano, progresso)
        r.update(id=pl["id"], nome=pl["nome"], mapa=plano)
        res.append(r)
    return res


def _epsg_area(p, limite):
    e = PF.epsg(p)
    if e:
        return e
    if limite:
        try:
            g = BD.geometria_limite(limite)
            c = g.Centroid()
            return BD.utm_sirgas(c.GetX(), c.GetY())
        except Exception:
            pass
    return 31983


def _gpkg_generico(caminho, epsg):
    """Mapa do plano quando o edital não define camadas: setores, rotas e pontos."""
    from osgeo import ogr, osr
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(int(epsg))
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(caminho)
    tipos = {"MultiPolygon": ogr.wkbMultiPolygon, "MultiLineString": ogr.wkbMultiLineString,
             "Point": ogr.wkbPoint}
    for nome, geom, campos in CAMADAS_GENERICAS:
        lyr = ds.CreateLayer(nome, srs, tipos[geom])
        for c in campos:
            lyr.CreateField(ogr.FieldDefn(c, ogr.OFTInteger if c == "ordem" else ogr.OFTString))
    ds = None


def _planilha_entregavel(destino, e, servicos):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Relação"
    cols = ["Item", "Serviço", "Endereço", "Bairro", "Latitude", "Longitude", "Foto (arquivo)",
            "Data", "Situação", "Observação"]
    ws.append(cols)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E78")
    for col, w in zip("ABCDEFGHIJ", (8, 30, 40, 20, 12, 12, 22, 12, 14, 40)):
        ws.column_dimensions[col].width = w
    info = wb.create_sheet("Como o edital pede")
    for linha in (("Documento", e.get("nome")), ("Formato", e.get("formato")),
                  ("Descrição", e.get("descricao")), ("Como fazer", e.get("como_fazer")),
                  ("Serviços", "; ".join(f"{s['codigo']} {s['nome']}" for s in servicos)),
                  ("Fonte", PF.fonte_txt(e))):
        info.append(list(linha))
    info.column_dimensions["A"].width = 14
    info.column_dimensions["B"].width = 110
    for row in info.iter_rows():
        row[1].alignment = Alignment(wrap_text=True, vertical="top")
    wb.save(destino)


def _exportar_shp(plano, pasta):
    from osgeo import gdal
    os.makedirs(pasta, exist_ok=True)
    with gdal.ExceptionMgr(useExceptions=True):
        gdal.VectorTranslate(pasta, plano, format="ESRI Shapefile",
                             layerCreationOptions=["ENCODING=UTF-8"])
    return pasta


def _tabela_atributos(plano, destino):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from osgeo import ogr
    wb = Workbook()
    wb.remove(wb.active)
    ds = ogr.Open(plano)
    for lyr in ds:
        ws = wb.create_sheet(lyr.GetName()[:31])
        d = lyr.GetLayerDefn()
        nomes = [d.GetFieldDefn(i).GetName() for i in range(d.GetFieldCount())]
        ws.append(nomes)
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="1F4E78")
        for f in lyr:
            ws.append([f.GetField(i) for i in range(len(nomes))])
    if not wb.sheetnames:
        wb.create_sheet("vazio")
    wb.save(destino)


def _blocos_texto(texto):
    """Texto redigido → blocos do padrão VA (linhas com "- " ou "• " viram lista)."""
    out, itens = [], []
    for par in str(texto).split("\n"):
        t = par.strip()
        if not t:
            continue
        m = re.match(r"^(?:[-•*▪]\s+)(.+)$", t)
        if m:
            itens.append(m.group(1))
            continue
        if itens:
            out.append({"tipo": "lista", "itens": itens})
            itens = []
        out.append({"tipo": "paragrafo", "texto": t})
    if itens:
        out.append({"tipo": "lista", "itens": itens})
    return out


def _f1(x):
    return f"{x:.1f}".replace(".", ",")


def _blocos_circuitos(res, nomes):
    """Anexo do documento: a conta do dimensionamento e a tabela dos circuitos."""
    try:
        from . import dimensionamento as DMx
    except ImportError:
        import dimensionamento as DMx
    blocos = [{"tipo": "anexo", "texto": "Anexo A | Dimensionamento e circuitos"},
              {"tipo": "paragrafo", "texto": "Circuitos gerados pelo App_Qgis a partir do edital, "
               "das vias do OpenStreetMap e dos setores censitários do IBGE (Censo 2022). O mapa "
               "do plano tem os circuitos (camada *setores*) e a ordem de passagem (camada "
               "*rotas*); a planilha de circuitos traz o itinerário rua a rua."}]
    for c, r in res.items():
        pl, circ = r["plano"], r["circuitos"]
        par = pl["par"]
        blocos.append({"tipo": "secao", "texto": f"{c} {nomes.get(c, '')}".strip()})
        blocos.append({"tipo": "lista", "itens": DMx.resumo_parametros(par) + [
            f"Vias do serviço: {_f1(pl['km_vias'])} km → **{len(circ)} circuitos**."]})
        if pl.get("alertas"):
            blocos.append({"tipo": "quadro", "cor": "amarelo",
                           "texto": "**Atenção:** " + " ".join(pl["alertas"])})
        tipo = r["tipo"]
        if tipo == "coleta":
            cols = ["Código", "Bairros", "Frequência / dias", "Turno", "km", "Desloc. km",
                    "t por coleta"]
            larg = [3.6, None, 3.2, 1.6, 1.3, 1.6, 1.6]
        elif tipo == "varricao":
            cols = ["Código", "Bairros", "Frequência / dias", "km de rua", "Desloc. km (a pé)",
                    "Duplas"]
            larg = [3.6, None, 3.2, 1.6, 2.0, 1.4]
        else:
            cols = ["Código", "Área / vias", "Frequência", "Turno", "km", "Desloc. km"]
            larg = [3.6, None, 3.2, 1.6, 1.3, 1.6]
        linhas = []
        for ci in circ:
            freq = " — ".join(x for x in (ci.get("frequencia") or "", ci.get("dias") or "") if x)
            base = [ci.get("codigo", ""), ci.get("nome") or "", freq]
            if tipo == "coleta":
                linhas.append(base + [ci.get("turno", ""), _f1(ci["km"]),
                                      _f1(ci.get("km_desloc", 0)), _f1(ci.get("t", 0))])
            elif tipo == "varricao":
                dup = {it.get("dupla") for it in ci.get("itinerario") or [] if it.get("dupla")}
                linhas.append(base + [_f1(ci["km"]), _f1(ci.get("km_desloc", 0)),
                                      str(len(dup) or 1)])
            else:
                linhas.append(base + [ci.get("turno", ""), _f1(ci["km"]),
                                      _f1(ci.get("km_desloc", 0))])
        tot_km = sum(ci["km"] for ci in circ)
        tot = ["Total", f"{len(circ)} circuitos", ""]
        if tipo == "coleta":
            tot += ["", _f1(tot_km), _f1(sum(ci.get("km_desloc", 0) for ci in circ)), ""]
        elif tipo == "varricao":
            tot += [_f1(tot_km), _f1(sum(ci.get("km_desloc", 0) for ci in circ)), ""]
        else:
            tot += ["", _f1(tot_km), _f1(sum(ci.get("km_desloc", 0) for ci in circ))]
        blocos.append({"tipo": "tabela", "colunas": cols, "linhas": linhas + [tot],
                       "larguras": larg, "direita": list(range(len(cols) - 3, len(cols))),
                       "total": True, "manter_junto": False,
                       "nota": "km = vias do circuito; Desloc. = trechos percorridos sem serviço "
                               "(ligação entre ruas e retorno ao início)."})
    return blocos


def _curto(t, n):
    """Corta o texto numa palavra inteira (cabeçalho e rodapé em uma linha)."""
    t = " ".join(str(t or "").split())
    if len(t) <= n:
        return t
    c = t[:n - 1].rsplit(" ", 1)[0].rstrip(" –-,(")
    return c + "…"


def _docx(destino, p, pl, empresa, secoes, txt, como_fazer, plano, titulo=None,
          subtitulo=None, abertura=None, circuitos=None, nomes_servicos=None):
    """Texto do plano no padrão visual Valor Ambiental / CCIO (docx_va)."""
    try:
        from . import docx_va as DV
    except ImportError:
        import docx_va as DV
    c = p["contrato"]
    titulo = titulo or f"Plano de Serviço — {pl['servico']} - {pl['nome']}"
    hoje = _dt.date.today().strftime("%d/%m/%Y")
    blocos = [{"tipo": "titulo", "texto": titulo},
              {"tipo": "subtitulo", "texto": subtitulo or (f"Lote {pl['lote']}"
                                                          + (f" — {empresa}" if empresa else ""))},
              {"tipo": "paragrafo", "texto": f"Elaborado conforme {c.get('titulo') or 'o edital'}"
               + (f" ({c['orgao']})" if c.get("orgao") else "") + "."}]
    if abertura:
        blocos.append({"tipo": "paragrafo", "texto": abertura})
    if como_fazer:
        blocos.append({"tipo": "quadro", "cor": "cinza", "texto": f"**Como o edital pede:** {como_fazer}"})
    if plano:
        blocos.append({"tipo": "paragrafo", "texto": f"*Mapa do plano: {os.path.basename(plano)} "
                       "(circuitos, ordem de passagem e pontos).*"})
    for n, t in enumerate(secoes, start=1):
        blocos.append({"tipo": "secao", "texto": f"{n}. {t}"})
        if txt.get(t) and str(txt[t]).strip():
            blocos += _blocos_texto(txt[t])
        else:
            blocos.append({"tipo": "paragrafo", "texto": "[A DEFINIR: preencher esta seção]"})
    if circuitos:
        blocos += _blocos_circuitos(circuitos, nomes_servicos or {})
    orgao = c.get("orgao") or c.get("titulo") or "Licitação"
    spec = {"saida": destino, "orientacao": "retrato",
            "cabecalho": {"linha1": _curto(orgao, 75), "linha2": _curto(titulo, 70),
                          "linha3": " | ".join(x for x in (empresa, f"Lote {pl['lote']}", hoje) if x)},
            "rodape": f"{_curto(titulo, 80)} | Versão 1.0",
            "metadados": {"titulo": titulo, "autor": empresa or ""},
            "blocos": blocos}
    return DV.gerar(spec)


# ====================================================================== relatório
def relatorio(A, res, pasta_saida):
    """Planilha com o que foi criado e os problemas (para levar à reunião), em
    App_Qgis\\Relatorios."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    os.makedirs(pasta_saida, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Planos"
    ws.append(["Serviço", "Nome", "Lote", "Origem", "Criado", "Pasta", "Erros na conferência",
               "Avisos", "Frota/jornada", "Seções do texto a completar", "Erro"])
    for r in res:
        v = r.get("validacao") or {}
        fr = r.get("frota") or {}
        ws.append([r["servico"], r["nome"], r["lote"], r["origem"],
                   "sim" if r.get("ok") else "não", r.get("pasta", ""),
                   v.get("erros", ""), v.get("avisos", ""),
                   ("falhou: " + fr["falhou"]) if fr.get("falhou") else
                   (os.path.basename(fr["relatorio"]) if fr.get("relatorio") else ""),
                   len(r.get("pendentes") or []), r.get("erro", "") or v.get("falhou", "")])
    ws2 = wb.create_sheet("Problemas")
    ws2.append(["Nível", "Problema", "Detalhe", "Solução sugerida", "Planos"])
    for p in A["problemas"]:
        ws2.append([p["nivel"], p["titulo"], p["detalhe"], p["solucao"], ", ".join(p["planos"])])
    for w in (ws, ws2):
        for c in w[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="1F4E78")
        for col in w.columns:
            w.column_dimensions[col[0].column_letter].width = min(
                60, max(10, max(len(str(c.value or "")) for c in col) + 2))
    for row in ws2.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    arq = os.path.join(pasta_saida, f"Criar_Todos_{_dt.datetime.now():%Y%m%d_%H%M}.xlsx")
    wb.save(arq)
    return arq
