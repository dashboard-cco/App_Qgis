# -*- coding: utf-8 -*-
"""
Janela inicial do QGIS_IA: quatro tipos de projeto → pasta → detalhes → criar plano.
Usa cópia de Gdb/VE01.gdb (o original não muda).

    "C:\\Program Files\\QGIS 3.44.15\\bin\\python-qgis-ltr.bat" tests\\test_projetos.py
"""
import faulthandler
import os
import shutil
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.join(AQUI, "..", "src", "qgis_ia")
GDB = os.path.join(AQUI, "..", "Gdb")
sys.path.insert(0, PLUGIN)
sys.path.insert(0, os.path.join(PLUGIN, "actions"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# dados guardados da empresa: arquivo temporário (nunca o do usuário)
os.environ["APP_QGIS_EMPRESA"] = os.path.join(tempfile.gettempdir(),
                                              f"app_qgis_empresa_teste_{os.getpid()}.json")

import pastas as PA  # noqa: E402
import projetos as P  # noqa: E402

FALHAS = []
faulthandler.dump_traceback_later(int(os.environ.get("TESTE_LIMITE", "600")), exit=True)


def check(cond, msg):
    if not cond:
        FALHAS.append(msg)
        print("FALHOU:", msg)


tmp = tempfile.mkdtemp(prefix="qgisia_projetos_")
try:
    # ------------------------------------------------------------ tipos
    check([t["servico"] for t in P.TIPOS] == ["P1", "P2", "P5", "P6"], "4 tipos de projeto")
    check([t["nome"] for t in P.TIPOS] == ["Coleta Convencional", "Coleta Seletiva",
                                           "Varrição Manual", "Varrição Mecanizada"], "nomes")

    # ------------------------------------------------------------ ler a pasta
    pasta = os.path.join(tmp, "VE")
    os.makedirs(os.path.join(pasta, "edital"))
    shutil.copytree(os.path.join(GDB, "VE01.gdb"), os.path.join(pasta, "dados", "VE01.gdb"))
    open(os.path.join(pasta, "edital", "Edital.pdf"), "wb").write(b"%PDF-1.4\n")
    open(os.path.join(pasta, "Historico.xlsx"), "wb").write(b"x")
    open(os.path.join(pasta, "~$Historico.xlsx"), "wb").write(b"x")
    L = P.ler_pasta(pasta)
    check(len(L["documentos"]) == 1 and L["documentos"][0].endswith("Edital.pdf"), "documento")
    check(len(L["planilhas"]) == 1, "planilha (sem o arquivo temporário ~$)")
    check(len(L["bancos"]) == 1, "um .gdb (sem entrar nele)")
    b = L["bancos"][0]
    check(b["servico"] == "P6" and b["lote"] == 1, f"VE01 = P6 lote 1: {b['servico']} {b['lote']}")
    check(b["circuitos"] == 27, f"27 circuitos: {b['circuitos']}")
    check(b["km_linhas"] > 0 and b["ras"], "km e RAs")
    check(not any(c["nome"].startswith("T_1_") for c in b["camadas"]), "sem camadas de topologia")
    check(P.banco_do_servico(L, "P6") is b and P.banco_do_servico(L, "P1") is None,
          "plano do serviço")

    # ------------------------------------------------------------ detalhes
    d = P.detalhes_sugeridos(L, "P6")
    check(d["lote"] == 1 and d["plano_existente"] == b["caminho"], "sugere lote e plano")
    check(d["turnos"], "turnos")
    check(d["pasta_saida"] == os.path.join(pasta, "App_Qgis", "Planos"), "pasta de saída")
    check("O que é o serviço" in d["textos"] and "Horários" in d["textos"]
          and "27 circuitos" in d["textos"]["Planejamento das rotas e frequências"],
          "textos sugeridos")
    check(P.faltando(d) == [], f"nada falta: {P.faltando(d)}")
    check("lote" in P.faltando(dict(d, lote=None)) and "turno" in P.faltando(dict(d, turnos=[])),
          "falta lote/turno")
    t1 = P.textos_sugeridos("P1", 1, ["Diurno", "Noturno"])
    check("32 diurno" in t1["Tipos de caminhões utilizados"]
          and "16h00 às 00h20" in t1["Horários"], "P1: frota do Anexo R e horários")

    P.salvar_projeto(pasta, d)
    check(P.carregar_projeto(pasta, "P6")["lote"] == 1 and P.carregar_projeto(pasta, "P1") is None,
          "projeto salvo")
    check(len(P.ler_pasta(pasta)["documentos"]) == 1, "o projeto salvo não conta como arquivo")

    # ------------------------------------------------------------ criar plano
    r = P.criar_plano(dict(d, empresa="Empresa Teste"), carregar=False)
    arq = r["arquivos"]
    check(arq["gdb"] == os.path.join(pasta, "App_Qgis", "Planos", "P6_VE01", "VE01.gdb")
          and os.path.isdir(arq["gdb"]) and os.path.isdir(b["caminho"]),
          f"copia o plano existente para a pasta do plano: {arq['gdb']}")
    r_de_novo = P.criar_plano(dict(d, validar=False), carregar=False)
    check("mantido" in (r_de_novo.get("aviso") or ""), "cópia existente é mantida")
    for k in ("xlsx_atributos", "docx", "xlsx_conferencia"):
        check(k in arq and os.path.exists(arq[k]), f"gerou {k}")
    v = r["validacao"]
    check(v and v.get("circuitos") == 27 and "erros" in v, f"conferência: {v}")
    check("O que é o serviço" not in r["secoes_docx_a_preencher"], "seção preenchida no docx")
    L2 = P.ler_pasta(pasta)
    check(len(L2["documentos"]) == 1 and len(L2["planilhas"]) == 1,
          "o plano gerado (pasta de saída) não entra como arquivo de entrada")

    d5 = dict(P.detalhes_sugeridos(P.ler_pasta(os.path.join(tmp, "vazia")), "P5"),
              pasta_saida=os.path.join(tmp, "novo"), lote=2)
    r5 = P.criar_plano(d5, carregar=False)
    check(os.path.isdir(r5["arquivos"]["gdb"]) and r5["arquivos"]["gdb"].endswith("VA02.gdb"),
          f"plano novo vazio: {r5['arquivos'].get('gdb')}")
    try:
        P.criar_plano(dict(d5, lote=None), carregar=False)
        check(False, "devia recusar sem lote")
    except ValueError:
        pass

    # ------------------------------------------------------------ criar todos (SLU)
    import json as _json
    import criar_todos as CT
    import empresa as EMP
    so_edital = os.path.join(tmp, "so_edital")
    os.makedirs(so_edital)
    with open(os.path.join(so_edital, "Edital.txt"), "w", encoding="utf-8") as fh:
        fh.write("Pregão Presencial nº 90005/2026 — SLU/DF. Serviço de Limpeza Urbana.\n"
                 "Lote 1, Lote 2 e Lote 3. Coleta Convencional, Varrição Manual.\n" * 20)
    A = CT.analisar(so_edital)
    cods = {p["codigo"] for p in A["problemas"]}
    check(A["slu"] and A["servicos"] == list(CT.E.SERVICOS), "só edital SLU: perfil pronto")
    check(os.path.exists(os.path.join(so_edital, "App_Qgis", "Contrato", "contrato.json"))
          and not os.path.exists(os.path.join(so_edital, "contrato.json"))
          and os.path.isdir(os.path.join(so_edital, "App_Qgis", "Contrato", "textos")),
          "perfil e cache em App_Qgis\\Contrato")
    check(A["lotes"] == ["1", "2", "3"] and len(A["planos"]) == 36, f"36 planos: {len(A['planos'])}")
    check({"lote_indefinido", "sem_circuitos", "sem_planilha_empresa", "limite_baixado"} <= cods,
          f"problemas do só edital: {cods}")
    check(A["municipio"] == "Brasília" and A["uf"] == "DF", "município do SLU")
    check(not CT.bloqueado(A), "só edital não bloqueia")
    check(all(p["origem"].startswith("só documentos") for p in A["planos"] if p["servico"] == "P9"),
          "P9 só documentos")
    check(all(p["osm"] for p in A["planos"] if p["servico"] in ("P1", "P5")), "coleta/varrição: OSM")

    outro = os.path.join(tmp, "outro")
    os.makedirs(outro)
    with open(os.path.join(outro, "Edital.txt"), "w", encoding="utf-8") as fh:
        fh.write("Prefeitura de Exemplo. Contratação de serviços de jardinagem.\n" * 20)
    B = CT.analisar(outro)
    check(CT.bloqueado(B) and "sem_perfil" in {p["codigo"] for p in B["problemas"]}
          and any(p["acao"] == "ler_ia" for p in B["problemas"]), "edital desconhecido: ler com IA")
    try:
        CT.criar(B, [], os.path.join(tmp, "x"))
        check(False, "criar devia recusar")
    except ValueError:
        pass

    shutil.copy(os.path.join(so_edital, "Edital.txt"), os.path.join(pasta, "edital"))
    A = CT.analisar(pasta)                       # edital + VE01.gdb
    marc = [p for p in A["planos"] if p["marcado"]]
    check(A["lotes_marcados"] == ["1"] and len(marc) == 12, f"lote do plano atual: {A['lotes_marcados']}")
    p6 = next(p for p in A["planos"] if p["id"] == "P6-1")
    check(p6["plano_existente"] == b["caminho"] and p6["circuitos"] == 27 and not p6["osm"],
          "P6 usa o VE01")
    saida = os.path.join(tmp, "todos")
    R = CT.criar(A, ["P6-1", "P5-1", "P9-1", "P3-1", "P2-1"], saida, validar=True, baixar=False)
    check(R["ok"] == 5 and R["falhas"] == 0, f"criou 5: {[r.get('erro') for r in R['planos']]}")
    check(os.path.exists(R["relatorio"]) and os.path.dirname(R["relatorio"]) ==
          os.path.join(pasta, "App_Qgis", "Relatorios"), "relatório em App_Qgis\\Relatorios")
    check(os.path.exists(os.path.join(pasta, "App_Qgis", "LEIA-ME.txt")), "LEIA-ME da estrutura")
    check(R["empresa"] and os.path.basename(R["empresa"]) == "planilha_modelo_empresa.xlsx",
          "criou o modelo da planilha da empresa")
    por = {r["id"]: r for r in R["planos"]}
    check(por["P6-1"]["arquivos"]["gdb"] == os.path.join(saida, "P6_VE01", "VE01.gdb"),
          "P6 com a cópia do plano atual")
    check((por["P6-1"]["correcao"] or {}).get("linhas_divididas") is not None,
          f"correção automática: {por['P6-1']['correcao']}")
    check("gdb" not in por["P9-1"]["arquivos"] and "docx" in por["P9-1"]["arquivos"], "P9 sem gdb")
    check("xlsx_programacao" in por["P3-1"]["arquivos"], "P3 com programação trimestral")
    check(por["P5-1"]["arquivos"]["gdb"].endswith("VA01.gdb"), "P5 novo vazio")
    emp = EMP.ler(pasta)
    ids_v = [v["identificacao"] for v in emp["veiculos"] if v["servico"] == "P2"]
    check(ids_v[:2] == ["CS01-D01", "CS01-D02"] and any(i.startswith("CS01-N") for i in ids_v),
          f"veículos identificados: {ids_v[:3]}")
    esc = CT.escolhas(pasta)
    check(esc.get("lotes") == ["1"] and esc.get("pasta_saida") == saida, "escolhas guardadas")
    check(not any(d.startswith(saida) for d in CT.analisar(pasta)["leitura"]["documentos"]),
          "planos criados não entram como documentos")

    # ------------------------------------------------------------ andamento da leitura
    from planos import leitor_claude as LC
    an = LC.Andamento(paginas_total=300)
    pcts = [an.passo({"texto": "x", "ferramenta": "planos_ler_paginas",
                      "entrada": {"de": 1, "ate": 30}}) for _ in range(4)]
    check(pcts == sorted(pcts) and 3 < pcts[-1] < 45, f"leitura sobe sem passar de 45%: {pcts}")
    for s in ("contrato", "documentos", "lotes"):
        p_ = an.passo({"texto": "g", "ferramenta": "planos_salvar_secao", "entrada": {"secao": s}})
    check(45 < p_ < 70, f"seções gravadas: {p_}")
    for s in ("servicos", "camadas", "entregaveis", "insumos", "regras", "recursos", "equipes",
              "turnos", "pendencias"):
        p_ = an.passo({"texto": "g", "ferramenta": "planos_salvar_secao", "entrada": {"secao": s}})
    check(p_ == 98, f"12 seções = 98%: {p_}")
    ev = LC.interpretar('{"type":"assistant","message":{"content":[{"type":"tool_use",'
                        '"name":"mcp__qgis-planos__planos_salvar_secao","input":{"secao":"lotes"}}]}}')
    check(ev["ferramenta"] == "planos_salvar_secao" and ev["entrada"]["secao"] == "lotes",
          "evento com a ferramenta")

    # ------------------------------------------------------------ OCR pelo Claude (simulado)
    from planos import documentos as DOC, ocr as OCR
    check(OCR.separar("=== PÁGINA 2 ===\nabc\n=== PAGINA 5 ===\ndef") == {2: "abc", 5: "def"},
          "separar páginas")
    anexo_p = [f for f in os.listdir(os.path.join(AQUI, "..", "Edital"))
               if "Anexo-P" in f] if os.path.isdir(os.path.join(AQUI, "..", "Edital")) else []
    if anexo_p:
        esc = os.path.join(tmp, "escaneado")
        os.makedirs(esc)
        shutil.copy(os.path.join(AQUI, "..", "Edital", anexo_p[0]), os.path.join(esc, "AnexoP.pdf"))
        shutil.copy(os.path.join(so_edital, "Edital.txt"), esc)
        pedidos = []

        def claude_falso(args, pasta_img):
            imgs = sorted(f for f in os.listdir(pasta_img) if f.endswith(".png"))
            pedidos.append((args, imgs))
            return "=== PÁGINA 1 ===\nMODELO DE DECLARAÇÃO DE VISTORIA OU RENUNCIA\nCNPJ nº: ____"

        AE = CT.analisar(esc)
        check(AE["escaneados"] and any(p["acao"] == "ocr" for p in AE["problemas"]),
              "escaneado: ação de OCR")
        r_ocr = CT.ler_escaneados(AE, executar=claude_falso)
        check(r_ocr[0]["paginas_lidas"] == 1 and pedidos[0][1] == ["pagina_0001.png"]
              and "Read" in pedidos[0][0], f"OCR: {r_ocr} {pedidos}")
        d = DOC.ler(os.path.join(esc, "AnexoP.pdf"), PA.arquivo(esc, "textos"))
        check("VISTORIA" in d["paginas"][0] and not DOC.aviso_sem_texto(d) and d.get("ocr") == [1],
              "texto do OCR no cache do documento")
        check(not CT.analisar(esc)["escaneados"], "depois do OCR não é mais escaneado")

    # ------------------------------------------------------------ documentos do edital (Suzano)
    from planos import redacao as RED
    te = CT.tipo_entregavel
    check(te({"nome": "Plano de Trabalho Operacional", "formato": "Não especificado (documento)",
              "secoes": ["Setorização do Município", "Rotas detalhadas"]}) == ("texto", True),
          "plano de trabalho = texto com mapa")
    check(te({"nome": "Relação de locais de papeleiras", "formato": "Arquivo editável com "
              "endereços + fotos georreferenciadas"}) == ("planilha", True), "relação = planilha")
    check(te({"nome": "Documentação de início da operação", "formato": "Documentos"})[0]
          == "documentos", "licenças = documentos da empresa")
    check(RED._paginas("4-5, 30") == [4, 5, 30] and RED._paginas("") == [], "páginas citadas")
    check(RED.ler_resposta('```json\n{"secoes": {"setorizacao do municipio": "x"}}\n```',
                           ["Setorização do Município", "Rotas"]) == {"Setorização do Município": "x"},
          "resposta do Claude: título sem acento/maiúscula")
    check(EMP.eh_veiculo("Caminhão poliguindaste duplo") and EMP.eh_veiculo("Varredeira mecânica")
          and not EMP.eh_veiculo("Caçamba estacionária") and not EMP.eh_veiculo("Contêiner 1000 L")
          and EMP.eh_veiculo("Caminhão com caçamba basculante"), "veículo × equipamento")
    check(EMP.ident_veiculo("S1.1", "1", "Diurno", 3) == "S1.1-L01-D03"
          and EMP.ident_veiculo("CC", 1, "Noturno", 2) == "CC01-N02", "código dos veículos")

    # ------------------------------------------------------------ criar todos (outro edital)
    import base_dados as BD
    from planos import perfil as PF
    gen = os.path.join(tmp, "generico")
    os.makedirs(gen)
    pg = PF.vazio()
    pg["contrato"].update(titulo="Pregão 12/2026 — Coleta de lixo de Exemplo",
                          orgao="Prefeitura de Exemplo", numero="12/2026",
                          sistema_referencia="SIRGAS 2000 / UTM 23S", municipio="Exemplo", uf="SP")
    pg["lotes"] = [{"codigo": "Lote 1", "nome": "Lote 1", "regioes": ["Centro"],
                    "fonte": {"documento": "", "paginas": ""}}]
    pg["servicos"] = [{"codigo": "S1", "sigla": "CL", "nome": "Coleta de lixo domiciliar",
                       "unidade_medida": "t", "lotes": ["Lote 1"], "frequencia": "diária",
                       "sob_demanda": False, "fonte": {"documento": "", "paginas": ""}}]
    campo = lambda n, t="texto", pad="": {"nome": n, "tipo": t, "tamanho": 20,  # noqa: E731
                                           "obrigatorio": True, "descricao": "",
                                           "valores_permitidos": [], "valor_padrao": pad}
    pg["camadas"] = [
        {"nome": "rotas", "descricao": "", "geometria": "linha", "servicos": ["S1"],
         "campos": [campo("codigo"), campo("turno", pad="Diurno")],
         "fonte": {"documento": "", "paginas": ""}},
        {"nome": "setores", "descricao": "", "geometria": "poligono", "servicos": ["S1"],
         "campos": [campo("codigo"), campo("frequencia")], "fonte": {"documento": "", "paginas": ""}}]
    ent = lambda n, f, arq="", sec=None: {  # noqa: E731
        "nome": n, "formato": f, "descricao": "", "prazo": "", "servicos": ["S1"],
        "nome_arquivo": arq, "secoes": sec or [], "como_fazer": "Fonte Arial 12.",
        "fonte": {"documento": "", "paginas": ""}}
    pg["entregaveis"] = [ent("Mapa das rotas", "GeoPackage (.gpkg)", "{sigla}{lote}.gpkg"),
                         ent("Tabela das rotas", "Excel (.xlsx)"),
                         ent("Memorial", "Word (.docx)", "",
                             ["Descrição do serviço", "Frota", "Equipe", "Horários de trabalho",
                              "Contatos"])]
    pg["recursos"] = [
        {"servico": "S1", "lote": "", "categoria": "equipamento", "nome": "Compactador 15 m³",
         "codigo_no_plano": "", "diurno": 3, "noturno": 0, "domingo": False,
         "fonte": {"documento": "", "paginas": ""}},
        {"servico": "S1", "lote": "", "categoria": "pessoal", "nome": "Coletor",
         "codigo_no_plano": "", "diurno": 9, "noturno": 0, "domingo": False,
         "fonte": {"documento": "", "paginas": ""}}]
    pg["turnos"] = [{"servico": "S1", "nome": "Diurno", "inicio": "07:00", "fim": "15:20",
                     "jornada": "07:20", "equipamento": "", "observacao": "",
                     "fonte": {"documento": "", "paginas": ""}}]
    check(not PF.valida(pg), f"perfil genérico válido: {PF.valida(pg)[:3]}")
    PF.salvar(pg, os.path.join(gen, "contrato.json"))      # lugar antigo: o app move
    with open(os.path.join(gen, "Edital.txt"), "w", encoding="utf-8") as fh:
        fh.write("Pregão 12/2026. Coleta de lixo domiciliar.\n" * 20)

    quadrado = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
                "geometry": {"type": "Polygon", "coordinates": [[[-47.01, -22.01], [-46.99, -22.01],
                                                                 [-46.99, -21.99], [-47.01, -21.99],
                                                                 [-47.01, -22.01]]]}}]}
    osm = {"elements": [
        {"type": "way", "id": 1, "tags": {"highway": "residential", "name": "Rua A"},
         "geometry": [{"lat": -22.0, "lon": -47.005}, {"lat": -22.0, "lon": -46.995}]},
        {"type": "way", "id": 2, "tags": {"highway": "primary", "name": "Av. B", "oneway": "yes"},
         "geometry": [{"lat": -22.005, "lon": -47.0}, {"lat": -21.995, "lon": -47.0}]},
        {"type": "way", "id": 3, "tags": {"highway": "residential"},          # fora do município
         "geometry": [{"lat": -23.0, "lon": -48.0}, {"lat": -23.0, "lon": -48.01}]}]}
    urls = []

    def falso(url, dados=None, **_):
        urls.append(url)
        if "localidades" in url:
            return _json.dumps([{"id": 3599999, "nome": "Exemplo"}]).encode()
        if "malhas" in url:
            return _json.dumps(quadrado).encode()
        return _json.dumps(osm).encode()

    G = CT.analisar(gen)
    check(not os.path.exists(os.path.join(gen, "contrato.json")) and
          os.path.exists(os.path.join(gen, "App_Qgis", "Contrato", "contrato.json")),
          "contrato.json antigo movido para App_Qgis\\Contrato")
    check(not G["slu"] and len(G["planos"]) == 1 and G["planos"][0]["id"] == "E1-1"
          and G["planos"][0]["nome"] == "Memorial",
          f"edital genérico: 1 plano com os 3 arquivos: {[x['id'] for x in G['planos']]}")
    pl = G["planos"][0]
    check(pl["osm"] and pl["geo"] == ".gpkg" and "CL01.gpkg" in pl["arquivos"],
          f"genérico: base OSM e .gpkg do edital: {pl}")
    pedidos_red = []

    def claude_redator(entrada):
        import json as _j
        d = _j.loads(entrada)
        pedidos_red.append(d)
        return _j.dumps({"secoes": {
            "Descrição do serviço": "A coleta domiciliar será feita diariamente (Edital, p. 3).",
            "Horários de trabalho": "Turno diurno das 07:00 às 15:20.\n[A DEFINIR: horário "
                                    "do sábado, pela contratante]"}})

    RG = CT.criar(G, ["E1-1"], os.path.join(gen, "Planos"), baixar_fn=falso,
                  executar_redacao=claude_redator)
    rg = RG["planos"][0]
    check(rg.get("ok"), f"genérico criado: {rg.get('erro')}")
    arqs = rg.get("arquivos") or {}
    check(os.path.exists(arqs.get("mapa", "")) and arqs["mapa"].endswith("CL01.gpkg"),
          f"gpkg com o nome do edital: {arqs}")
    check(rg.get("redigido") and rg.get("a_definir") == 1 and pedidos_red
          and pedidos_red[0]["documento"]["secoes"][0] == "Descrição do serviço"
          and pedidos_red[0]["veiculos_identificados"][0]["identificacao"] == "CL01-D01",
          f"Claude recebeu o documento, as seções e os veículos: {rg.get('redigido')}")
    from osgeo import ogr as _ogr
    dsg = _ogr.Open(arqs["mapa"])
    check({dsg.GetLayer(i).GetName() for i in range(dsg.GetLayerCount())} >= {"rotas", "setores"},
          "camadas do edital no plano")
    dsg = None
    vias = arqs.get("base_vias_osm")
    dv = _ogr.Open(vias) if vias else None
    check(dv is not None and dv.GetLayer(0).GetFeatureCount() == 2,
          "vias do OSM baixadas e recortadas no município")
    dv = None
    check(any("malhas" in u for u in urls) and any("overpass" in u for u in urls), "IBGE e OSM")
    docx = next((v for k, v in arqs.items() if k.startswith("docx")), "")
    import zipfile as _zip
    xml = _zip.ZipFile(docx).read("word/document.xml").decode("utf-8") if docx else ""
    check("CL01-D01" in xml and "Coletor: 9" in xml and "07:00" in xml and "Arial 12" in xml
          and "diariamente (Edital, p. 3)" in xml and "[A DEFINIR" in xml,
          "texto com frota identificada, equipe, horário, como fazer e redação do Claude")
    zd = _zip.ZipFile(docx)
    hdr = zd.read("word/header1.xml").decode("utf-8")
    ftr = zd.read("word/footer1.xml").decode("utf-8")
    est = zd.read("word/styles.xml").decode("utf-8")
    check("1F5434" in hdr and "Prefeitura de Exemplo" in hdr and "Memorial" in hdr
          and " PAGE " in ftr and "Versão 1.0" in ftr and 'w:styleId="Heading1"' in est
          and 'w:val="C00000"' in xml,
          "docx no padrão Valor Ambiental: faixa verde, cabeçalho, rodapé com página, "
          "[A DEFINIR] em vermelho")
    zd = None
    check("Contatos" in rg["pendentes"], f"contatos a preencher: {rg['pendentes']}")
    # varrição: manual e mecanizada sempre em arquivos separados
    sv = {"1.5": {"nome": "Coleta seletiva"}, "1.6": {"nome": "Varrição manual de vias"},
          "1.7": {"nome": "Varrição mecanizada de vias"}}
    pt = list(CT._partes_por_lote(["1"], ["1.6", "1.7"], {"1.6": ["1"], "1.7": ["1"]}, sv))
    check([(x[1], x[2][0]) for x in pt] == [(["1.6"], "varricao_manual"),
                                           (["1.7"], "varricao_mecanizada")],
          f"varrição manual e mecanizada separadas: {pt}")
    pt = list(CT._partes_por_lote(["1"], ["1.5", "1.6"], {"1.5": ["1"], "1.6": ["1"]}, sv))
    check([(x[1], x[2] and x[2][0]) for x in pt] == [(["1.5"], None), (["1.6"], "varricao_manual")],
          f"varrição sai do documento junto com outros serviços: {pt}")
    pt = list(CT._partes_por_lote(["1"], ["1.6"], {"1.6": ["1"]}, sv))
    check(pt == [("1", ["1.6"], None)], "varrição sozinha: plano normal")
    check(any(k.startswith("xlsx") for k in arqs) and "xlsx_conferencia" in arqs, "tabela e conferência")
    # a empresa preenche os contatos na planilha e cria de novo
    from openpyxl import load_workbook
    arq_emp = EMP.arquivo(gen)
    wb = load_workbook(arq_emp)
    wb["Contatos"]["A2"] = "Fulano de Tal"
    wb["Contatos"]["C2"] = "(11) 9999-0000"
    wb.save(arq_emp)
    shutil.rmtree(os.path.join(gen, "Planos"))
    RG2 = CT.criar(CT.analisar(gen), ["E1-1"], os.path.join(gen, "Planos"), baixar_fn=falso,
                   redigir=False)
    docx = next(v for k, v in RG2["planos"][0]["arquivos"].items() if k.startswith("docx"))
    xml = _zip.ZipFile(docx).read("word/document.xml").decode("utf-8")
    check("Fulano de Tal" in xml and "Contatos" not in RG2["planos"][0]["pendentes"],
          "contatos da planilha da empresa no texto")

    # planilha da empresa montada com o edital (Claude simulado)
    def claude_planilha(entrada):
        d = _json.loads(entrada)
        check(d["servicos"][0]["codigo"] == "S1" and "trechos_do_edital" in d,
              "dados do edital para a planilha")
        return _json.dumps({
            "procedimentos": {"S1": "Os caminhões saem da garagem às 7h e coletam porta a porta "
                                    "(Edital, p. 3)."},
            "locais": [{"tipo": "aterro", "nome": "Aterro Municipal", "endereco": "Estrada X, km 5",
                        "servicos": "S1", "fonte": "Edital, p. 4"}],
            "responsaveis": [{"funcao": "Engenheiro responsável", "exigencia": "CREA ativo",
                              "fonte": "Edital, p. 9"}]})

    info = EMP.preencher_do_edital(gen, pg, [], executar=claude_planilha)
    check(info["arquivo"].endswith("planilha_modelo_empresa_sugerida.xlsx"),
          "planilha já editada pelo usuário: sugestão ao lado, nada apagado")
    check(EMP.ler(gen)["contatos"][0]["nome"] == "Fulano de Tal", "planilha do usuário intacta")
    os.remove(EMP.arquivo(gen))
    os.remove(info["arquivo"])
    info = EMP.preencher_do_edital(gen, pg, [], executar=claude_planilha)
    e2 = EMP.ler(gen)
    check(info["claude"] and info["veiculos"] == 3 and info["procedimentos"] == 1
          and e2["procedimentos"].get("S1", "").startswith("Os caminhões")
          and any(x["nome"] == "Aterro Municipal" for x in e2["locais"])
          and any(x["tipo"] == "garagem" and "A DEFINIR" in x["endereco"] for x in e2["locais"])
          and [v["identificacao"] for v in e2["veiculos"]][:1] == ["CL01-D01"],
          f"planilha com o edital: {info}")
    info2 = EMP.preencher_do_edital(gen, pg, [], executar=claude_planilha)
    check(info2["arquivo"].endswith("planilha_modelo_empresa.xlsx") and info2["substituiu"],
          "planilha do app ainda intacta: refaz e guarda a anterior")
    txt_dest = EMP.textos(pg, "S1", "1", "CL", ["Diurno"], e2, ["Local de destinação"])
    check("Aterro Municipal — Estrada X, km 5" in txt_dest.get("Local de destinação", ""),
          "locais no texto do plano")

    # ------------------------------------------------------------ setorização + roteirização
    import setorizacao as SZ
    import territorio as TE
    import dimensionamento as DMZ
    from osgeo import osr as _osr
    sz = os.path.join(tmp, "setores")
    os.makedirs(sz)
    srs = _osr.SpatialReference()
    srs.ImportFromEPSG(31983)
    dsv = _ogr.GetDriverByName("GPKG").CreateDataSource(os.path.join(sz, "vias.gpkg"))
    lv = dsv.CreateLayer("vias_osm", srs, _ogr.wkbLineString)
    for c in ("highway", "nome"):
        lv.CreateField(_ogr.FieldDefn(c, _ogr.OFTString))
    lv.CreateField(_ogr.FieldDefn("mao_unica", _ogr.OFTInteger))
    x0, y0 = 330000, 7390000
    for i in range(21):                      # malha 2 x 2 km, ruas a cada 100 m (ways inteiros)
        for (pa, pb) in (((x0 + i * 100, y0), (x0 + i * 100, y0 + 2000)),
                         ((x0, y0 + i * 100), (x0 + 2000, y0 + i * 100))):
            f = _ogr.Feature(lv.GetLayerDefn())
            pts = ",".join(f"{pa[0] + (pb[0] - pa[0]) * k / 20} {pa[1] + (pb[1] - pa[1]) * k / 20}"
                           for k in range(21))
            f.SetGeometry(_ogr.CreateGeometryFromWkt(f"LINESTRING({pts})"))
            f.SetField("highway", "residential" if i % 5 else "secondary")
            f.SetField("nome", f"Rua {i}" if pa[0] == pb[0] else f"Avenida {i}")
            lv.CreateFeature(f)
    f = _ogr.Feature(lv.GetLayerDefn())      # rodovia: não entra na coleta
    f.SetGeometry(_ogr.CreateGeometryFromWkt(f"LINESTRING({x0} {y0 + 1050},{x0 + 2000} {y0 + 1050})"))
    f.SetField("highway", "motorway")
    lv.CreateFeature(f)
    dsv = None
    dsl = _ogr.GetDriverByName("GPKG").CreateDataSource(os.path.join(sz, "limite.gpkg"))
    ll = dsl.CreateLayer("limite", srs, _ogr.wkbPolygon)
    f = _ogr.Feature(ll.GetLayerDefn())
    f.SetGeometry(_ogr.CreateGeometryFromWkt(
        f"POLYGON(({x0 - 50} {y0 - 50},{x0 + 2050} {y0 - 50},{x0 + 2050} {y0 + 2050},"
        f"{x0 - 50} {y0 + 2050},{x0 - 50} {y0 - 50}))"))
    ll.CreateFeature(f)
    dsl = None
    # 16 setores censitários (525 m) com população; o centro (canto sudoeste) mais denso
    dss = _ogr.GetDriverByName("GPKG").CreateDataSource(os.path.join(sz, "setores_ibge.gpkg"))
    ls_ = dss.CreateLayer("setores", srs, _ogr.wkbMultiPolygon)
    for c, t in (("CD_SETOR", _ogr.OFTString), ("CD_SIT", _ogr.OFTString),
                 ("NM_BAIRRO", _ogr.OFTString), ("v0001", _ogr.OFTInteger),
                 ("v0002", _ogr.OFTInteger)):
        ls_.CreateField(_ogr.FieldDefn(c, t))
    for ia in range(4):
        for ib in range(4):
            xa, ya = x0 - 50 + ia * 525, y0 - 50 + ib * 525
            f = _ogr.Feature(ls_.GetLayerDefn())
            f.SetGeometry(_ogr.ForceToMultiPolygon(_ogr.CreateGeometryFromWkt(
                f"POLYGON(({xa} {ya},{xa + 525} {ya},{xa + 525} {ya + 525},{xa} {ya + 525},{xa} {ya}))")))
            f.SetField("CD_SETOR", f"S{ia}{ib}")
            f.SetField("CD_SIT", "1")
            f.SetField("v0001", 3000 if (ia < 2 and ib < 2) else 1000)
            f.SetField("v0002", 1000 if (ia < 2 and ib < 2) else 330)
            ls_.CreateFeature(f)
    dss = None
    dsp = _ogr.GetDriverByName("GPKG").CreateDataSource(os.path.join(sz, "bairros_osm.gpkg"))
    lp = dsp.CreateLayer("bairros_osm", srs, _ogr.wkbPoint)
    lp.CreateField(_ogr.FieldDefn("nome", _ogr.OFTString))
    for nome, (px, py) in (("Centro", (500, 500)), ("Vila Leste", (1500, 500)),
                           ("Vila Norte", (500, 1500)), ("Jardim Alto", (1500, 1500)),
                           ("Teste", (1000, 1000))):
        f = _ogr.Feature(lp.GetLayerDefn())
        f.SetGeometry(_ogr.CreateGeometryFromWkt(f"POINT({x0 + px} {y0 + py})"))
        f.SetField("nome", nome)
        lp.CreateFeature(f)
    dsp = None
    check(TE.frequencia_padrao("Diária (seg. a dom.) no Centro Expandido; trissemanal nos "
                               "demais bairros") == ("trissemanal", {"centro": "diaria"}),
          "frequência do edital: diária no centro, trissemanal nos demais")
    TT = TE.Territorio(os.path.join(sz, "vias.gpkg"), os.path.join(sz, "limite.gpkg"),
                       os.path.join(sz, "setores_ibge.gpkg"), os.path.join(sz, "bairros.gpkg"),
                       os.path.join(sz, "bairros_osm.gpkg"), "Teste",
                       "Diária no Centro; trissemanal nos demais bairros")
    check(len(TT.segs) > 800 and all(s_["km"] <= 0.1001 for s_ in TT.segs
                                     if s_["highway"] != "motorway"),
          f"vias quebradas nos cruzamentos: {len(TT.segs)} trechos")
    check(sorted(b_["nome"] for b_ in TT.bairros) == ["Centro", "Jardim Alto", "Vila Leste",
                                                     "Vila Norte"],
          f"bairros pelos pontos do OSM (sem o nome do município): {[b_['nome'] for b_ in TT.bairros]}")
    fq = {b_["nome"]: b_["frequencia"] for b_ in TT.bairros}
    check(fq["Centro"] == "diaria" and fq["Vila Leste"] == "trissemanal"
          and os.path.exists(os.path.join(sz, "bairros.gpkg")),
          f"frequência por bairro gravada no arquivo de bairros: {fq}")
    check(abs(sum(b_["pop"] for b_ in TT.bairros) - 24000) < 1, "população do IBGE nos bairros")

    ps = PF.vazio()
    ps["servicos"] = [{"codigo": "1.1", "sigla": "", "nome": "Coleta de resíduos domiciliares",
                       "lotes": ["1"], "frequencia": "Diária no Centro; trissemanal nos demais"},
                      {"codigo": "1.4", "sigla": "", "nome": "Limpeza de feiras livres",
                       "lotes": ["1"], "frequencia": ""},
                      {"codigo": "1.6", "sigla": "", "nome": "Varrição manual de vias",
                       "lotes": ["1"], "frequencia": ""}]
    ps["recursos"] = [{"servico": "1.1", "lote": "1", "categoria": "equipamento",
                       "nome": "Caminhão compactador", "diurno": 2, "noturno": 2, "domingo": True},
                      {"servico": "1.1", "lote": "1", "categoria": "equipamento",
                       "nome": "Caçamba estacionária", "diurno": 50, "noturno": 0},
                      {"servico": "1.4", "lote": "1", "categoria": "equipamento",
                       "nome": "Caminhão pipa", "diurno": 2, "noturno": 0},
                      {"servico": "1.6", "lote": "1", "categoria": "pessoal",
                       "nome": "Varredor", "diurno": 8, "noturno": 0}]
    ps["regras"] = [{"descricao": "Varrição manual: 2 equipes simultâneas.", "tipo": "x"}]
    check(SZ.tipo_servico("Coleta de resíduos domiciliares") == "coleta"
          and SZ.tipo_servico("Varrição mecanizada de vias") == "varricao_mec"
          and SZ.tipo_servico("Limpeza de feiras livres") is None
          and SZ.tipo_servico("Coleta em locais de difícil acesso") is None
          and SZ.tipo_servico("Unidade de transferência (transbordo)") is None, "tipo de serviço")
    qt = [("Coleta de resíduos domiciliares", "tonelada", 600.0),
          ("Varrição manual de vias", "km eixo", 520.0)]
    pc = DMZ.padrao(ps, "1.1", "1", qtds=qt)
    check(pc["veiculos_diurno"] == 2 and pc["veiculos_noturno"] == 2 and pc["dias_semana"] == 7
          and pc["t_mes"] == 600.0 and pc["frequencia"] == "trissemanal"
          and pc["diaria_em"] == "centro", f"parâmetros do edital: {pc}")
    pv = DMZ.padrao(ps, "1.6", "1", qtds=qt)
    check(pv["equipes"] == 2 and pv["varredores"] == 8 and pv["km_mes"] == 520.0,
          f"varrição: equipes e km do edital: {pv}")
    check(DMZ.padrao(ps, "1.4", "1") is None, "feiras não têm dimensionamento")
    check(pv["lados"] == 2, "varrição: o km do edital é de sarjeta (2 lados) por padrão")
    pl2 = SZ.planejar(TT, "varricao", pv)
    pv1 = dict(pv, lados=1)
    pl1 = SZ.planejar(TT, "varricao", pv1)
    check(abs(pl1["cap_km"] - 2 * pl2["cap_km"]) < 1e-9 and abs(pl1["cap_km"] - 10.0) < 1e-9,
          f"varrição: 2 sarjetas por via = metade do km de rua ({pl2['cap_km']:.1f} km)")
    pv = pv1                                     # o resto do teste usa km de rua
    pc.update(velocidade_kmh=6.0, improdutivo_h=1.0)          # 38 km por circuito
    plc = SZ.planejar(TT, "coleta", pc)
    check(abs(plc["slots_usados"] - 4) < 1e-9 and plc["circuitos"] >= 4,
          f"a frota fecha a conta (4 veículos-turno): {plc['slots_usados']} / {plc['circuitos']}")
    rs = SZ.setorizar(ps, ["1.1", "1.4", "1.6"], "1", TT, {"1.1": pc, "1.6": pv})
    check(sorted(rs) == ["1.1", "1.6"], f"feiras não viram circuito: {list(rs)}")
    cs = rs["1.1"]["circuitos"]
    cods = [c_["codigo"] for c_ in cs]
    check(any(c_.endswith("-SQS") for c_ in cods) and any(c_.endswith("-TQS") for c_ in cods)
          and len(set(cods)) == len(cods), f"códigos por veículo e dia: {cods}")
    cen = [c_ for c_ in cs if c_["freq"] == "diaria"]
    check(cen and all(c_["nomes"] == ["Centro"] and c_["turno"] == "Noturno" for c_ in cen),
          f"centro diário com o turno noturno: {[(c_['codigo'], c_['nomes']) for c_ in cen]}")
    nomes_b = [b_["nome"] for b_ in TT.bairros]
    check(all(nomes_b[TT.segs[i]["bairro"]] in c_["nomes"] for c_ in cs for i in c_["idx"]),
          "cada circuito fica dentro dos seus bairros")
    check(abs(sum(c_["km"] for c_ in cs) - 84.0) < 0.6, f"todas as ruas, sem a rodovia: "
          f"{sum(c_['km'] for c_ in cs):.1f}")
    ok_seq = cobre = True
    for c_ in cs:                                        # percurso fechado que cobre tudo
        ps_ = c_["rota"]["passos"]
        ok_seq = all(q1[2] == q2[1] for q1, q2 in zip(ps_[:-1], ps_[1:])) and ps_[0][1] == ps_[-1][2]
        cobre = {p_[0] for p_ in ps_ if p_[3]} == set(c_["idx"])
        if not (ok_seq and cobre):
            break
    check(ok_seq and cobre, "ordem de passagem: percurso contínuo, fechado, passa por todas as vias")
    check(all(c_["itinerario"][0]["ordem"] == 1 for c_ in cs) and
          all(abs(sum(it["km"] for it in c_["itinerario"] if it["servico"]) - c_["km"]) < 1e-6
              for c_ in cs), "itinerário: km de serviço = km do circuito")
    from shapely.ops import unary_union as _uu
    uni = _uu([c_["geom"] for c_ in cs])
    sobra = sum(c_["geom"].area for c_ in cs) - uni.area
    check(sobra < 1, f"circuitos sem sobreposição: {sobra:.1f} m²")
    cv = rs["1.6"]["circuitos"]
    dia_v = [c_ for c_ in cv if c_["freq"] == "diaria"]
    check(dia_v and len(cv) == len(dia_v) + (2 - len(dia_v)) * 6,
          f"varrição: diários no centro + 1 circuito por dia da semana nas outras equipes: "
          f"{[c_['codigo'] for c_ in cv]}")
    check(all(abs(c_["km"] - 10.0) < 4.0 for c_ in cv if c_["freq"] != "diaria"),
          f"varrição: ~10 km por equipe/dia: {[round(c_['km'], 1) for c_ in cv]}")
    check({it["dupla"] for it in cv[0]["itinerario"]} == {1, 2},
          "varrição: circuito repartido entre as 2 duplas")
    check(all(c_["rota"]["contramao_km"] == 0 for c_ in cv)
          and all(c_["km_desloc"] <= 0.6 * c_["km"] for c_ in cv),
          f"varrição a pé: sem mão de direção e pouco deslocamento: "
          f"{[(round(c_['km'], 1), round(c_['km_desloc'], 1)) for c_ in cv]}")
    ini_ok = True
    for c_ in cv:              # a equipe começa no próprio circuito, não no centro da cidade
        p0 = c_["rota"]["passos"][0][1]
        from shapely.geometry import Point as _Pt
        ini_ok = ini_ok and c_["vias_geom"].distance(_Pt(p0)) < 1.0
    check(ini_ok, "varrição: o percurso começa numa rua do circuito")
    # divisas dos circuitos: nas vias, no limite do município ou na divisa do bairro
    from shapely.ops import unary_union as _uu2
    divisas = _uu2([s_["geom"] for s_ in TT.segs] + [TT.limite.boundary]
                   + [b_["geom"].boundary for b_ in TT.bairros]).buffer(1.0)
    fora = sum(c_["geom"].boundary.difference(divisas).length for c_ in cs)
    tot_b = sum(c_["geom"].boundary.length for c_ in cs)
    check(fora < 0.02 * tot_b, f"divisas dos circuitos seguem as vias: {fora:.0f} de {tot_b:.0f} m fora")
    gsz = os.path.join(sz, "mapa.gpkg")
    CT._gpkg_generico(gsz, 31983)
    n_it = sum(len(c_["itinerario"]) for r_ in rs.values() for c_ in r_["circuitos"])
    n_c = len(cs) + len(cv)
    check(SZ.gravar(gsz, ps, rs) == n_c and SZ.gravar(gsz, ps, rs) == n_c, "grava e regrava")
    dg = _ogr.Open(gsz)
    check(dg.GetLayerByName("setores").GetFeatureCount() == n_c
          and dg.GetLayerByName("rotas").GetFeatureCount() == n_it, "regravar não duplica")
    dg = None
    xl = SZ.planilha(os.path.join(sz, "circuitos.xlsx"), rs)
    wbx = load_workbook(xl)
    check(wbx.sheetnames == ["Dimensionamento", "Circuitos", "Itinerários"]
          and wbx["Itinerários"].max_row == n_it + 1, "planilha de circuitos e itinerários")

    # ------------------------------------------------------------ tratamento das vias do OSM
    import base_dados as BDX
    vt = os.path.join(sz, "vias_trat.gpkg")
    dst = _ogr.GetDriverByName("GPKG").CreateDataSource(vt)
    lt = dst.CreateLayer("vias_osm", srs, _ogr.wkbLineString)
    for c in ("highway", "nome"):
        lt.CreateField(_ogr.FieldDefn(c, _ogr.OFTString))
    for wkt, hw in (("LINESTRING(0 0,100 0,200 0)", "residential"),      # rua A (nó no 100)
                    ("LINESTRING(200 0,100 0,0 0)", "secondary"),        # A repetida, invertida
                    ("LINESTRING(100 0,100 100)", "residential"),        # cruza A no nó 100
                    ("LINESTRING(150 100,150 0.2)", "residential"),      # "T": encosta em A
                    ("LINESTRING(50 -50,50 50)", "residential"),         # viaduto: sem nó
                    ("LINESTRING(0 0,100 0)", "residential")):           # sobreposta a A
        ft = _ogr.Feature(lt.GetLayerDefn())
        ft.SetGeometry(_ogr.CreateGeometryFromWkt(wkt))
        ft.SetField("highway", hw)
        lt.CreateFeature(ft)
    dst = None
    check(not BDX.vias_tratadas(vt), "vias novas: ainda sem tratamento")
    tr = BDX.tratar_vias(vt)
    dst = _ogr.Open(vt)
    lt = dst.GetLayer(0)
    tre = sorted((round(ft.GetGeometryRef().Length()), ft.GetField("highway")) for ft in lt)
    dst = None
    check(BDX.vias_tratadas(vt) and tr["duplicadas"] == 2 and tr["quebras_t"] == 1
          and tre == [(50, "secondary"), (50, "secondary"), (100, "residential"),
                      (100, "residential"), (100, "residential"), (100, "secondary")],
          f"vias do OSM: sem duplicadas e quebradas nos encontros (T também): {tr} {tre}")

    # ------------------------------------------------------------ dados guardados da empresa
    check(EMP.arquivo_padrao() == os.environ["APP_QGIS_EMPRESA"], "teste usa arquivo temporário")
    EMP.salvar_empresa_padrao({"Razão social": "Empresa Teste Ltda", "CNPJ": "00.000.000/0001-00"})
    EMP.salvar_empresa_padrao({"CNPJ": ""})                # vazio não apaga
    check(EMP.empresa_padrao() == {"Razão social": "Empresa Teste Ltda",
                                   "CNPJ": "00.000.000/0001-00"}, "dados guardados")
    nova = os.path.join(tmp, "nova_empresa")
    os.makedirs(nova)
    arq_n = EMP.criar_modelo(nova, pg, [("S1", "1", "CL")])
    check(EMP.ler(nova)["empresa"]["CNPJ"] == "00.000.000/0001-00"
          and EMP.nome_empresa(EMP.ler(nova)) == "Empresa Teste Ltda",
          "planilha nova já vem com os dados da empresa")
    wb = load_workbook(arq_n)
    for r in wb["Empresa"].iter_rows(min_row=2):
        if r[0].value == "Telefone":
            r[1].value = "(61) 3333-0000"
        if r[0].value == "Preposto":
            r[1].value = "Beltrano"
    wb.save(arq_n)
    EMP.aprender_empresa(EMP.ler(nova))
    check(EMP.empresa_padrao().get("Telefone") == "(61) 3333-0000"
          and "Preposto" not in EMP.empresa_padrao(), "aprende os dados fixos, não o preposto")
    os.remove(EMP.arquivo_padrao())

    # ------------------------------------------------------------ janela (sem tela)
    from qgis.core import QgsApplication
    qgs = QgsApplication([], False)
    qgs.initQgis()
    from unittest import mock
    import inicio as I

    class Cfg(dict):
        def value(self, k, padrao=None, **_):
            return self.get(k, padrao)

        def setValue(self, k, v):
            self[k] = v

    cfg = Cfg()

    class Iface:
        def mainWindow(self):
            return None

    chamadas = []
    with mock.patch.object(I, "QgsSettings", return_value=cfg):
        jan = I.JanelaInicio(Iface(), abrir_chat=lambda: chamadas.append("chat"),
                             abrir_planos=lambda p, docs, ler=False: chamadas.append((p, docs, ler)))
        check(set(jan.cartoes) == {"P1", "P2", "P5", "P6"}, "4 cartões")
        with mock.patch.object(I.QFileDialog, "getExistingDirectory", return_value=pasta):
            jan.cartoes["P6"].click()
        check(jan.pilha.currentIndex() == 1 and jan.servico == "P6", "abre o projeto")
        check(jan.arv_arquivos.topLevelItemCount() >= 3, "lista os arquivos")
        check(jan.cb_plano.currentData() == b["caminho"], "plano atual escolhido")
        check(jan.bt_criar.isEnabled(), "pode criar")
        check(jan.lista_recentes.count() == 1, "recente")
        jan.ck_diurno.setChecked(False)
        jan.ck_noturno.setChecked(False)
        check(not jan.bt_criar.isEnabled() and "turno" in jan.lb_falta.text(), "falta turno")
        jan.ck_noturno.setChecked(True)
        i = [jan.cb_secao.itemData(k) for k in range(jan.cb_secao.count())].index("Horários")
        jan.cb_secao.setCurrentIndex(i)
        h = jan.ed_secao.toPlainText()
        check("noturno" in h and "diurno" not in h, f"horário segue o turno: {h!r}")
        jan.ed_secao.setPlainText("Meu horário")
        jan.ck_diurno.setChecked(True)
        check(jan.textos["Horários"] == "Meu horário", "não apaga texto do usuário")
        jan.ed_empresa.setText("Empresa X")
        jan.ed_saida.setText(os.path.join(tmp, "saida_ui"))
        original = P.criar_plano
        with mock.patch.object(I.P, "criar_plano",
                               side_effect=lambda det: original(det, carregar=False)), \
                mock.patch.object(I.QMessageBox, "warning",
                                  side_effect=lambda *a: check(False, f"aviso: {a[2]}")):
            jan._criar()
        check("Plano criado" in jan.lb_resultado.text() and jan.lista_saida.count() >= 3,
              f"criou pela janela: {jan.lb_resultado.text()[:200]}")
        salvo = P.carregar_projeto(pasta, "P6")
        check(salvo["empresa"] == "Empresa X" and salvo["textos"]["Horários"] == "Meu horário",
              "projeto salvo pela janela")
        jan._planos_contrato()
        check(chamadas and chamadas[-1][0] == pasta and len(chamadas[-1][1]) == 2,
              f"abre Planos do Contrato com os documentos: {chamadas[-1:]}")
        jan._voltar()
        check(jan.pilha.currentIndex() == 0, "volta ao início")
        jan.lista_recentes.itemDoubleClicked.emit(jan.lista_recentes.item(0))
        check(jan.pilha.currentIndex() == 1 and jan.ed_empresa.text() == "Empresa X",
              "reabre o recente com os detalhes salvos")

        # Criar Todos pela janela
        cart = list(jan.cartoes.values()) + [jan.bt_todos]
        check(all(c.objectName() == "cartao" and c.height() == cart[0].height() for c in cart)
              and jan.windowTitle() == "App_Qgis", "cartões no mesmo padrão, título App_Qgis")
        dlg = I.DialogoCriarTodos(jan, pasta)
        check(dlg.analisar(), "analisa a pasta")
        check(dlg.arv_planos.topLevelItemCount() == 36 and dlg.arv_prob.topLevelItemCount() >= 2,
              "lista planos e problemas")
        # guarda a escolha da última criação (5 planos do lote 1)
        check(dlg.bt_criar.text() == "Criar 5 plano(s)" and set(dlg.cks_lote) == {"1", "2", "3"}
              and dlg.cks_lote["1"].isChecked() and not dlg.cks_lote["2"].isChecked(),
              f"lembra a última escolha: {dlg.bt_criar.text()}")
        check(dlg.ed_mun.text() == "Brasília" and dlg.ed_uf.text() == "DF", "município")
        dlg._marcar_todos(False)
        check(not dlg.bt_criar.isEnabled(), "nada marcado")
        for pid in ("P6-1", "P2-1"):
            dlg.itens[pid].setCheckState(0, I.Qt.CheckState.Checked)
        dlg.ed_saida.setText(os.path.join(tmp, "todos_ui"))
        dlg.ck_validar.setChecked(False)
        dlg.ck_baixar.setChecked(False)
        dlg._criar()
        check(dlg.itens["P6-1"].text(4).startswith("✅") and dlg.itens["P2-1"].text(4).startswith("✅")
              and dlg.itens["P1-1"].text(4) == "", "resultado na lista")
        check("2 plano(s) criado(s)" in dlg.lb_fim.text(), dlg.lb_fim.text())
        dlg.cks_lote["1"].setChecked(False)
        check(dlg.bt_criar.text() == "Criar 0 plano(s)", "desmarca o lote")
        dlg._ler_ia()
        check(chamadas[-1][0] == pasta and chamadas[-1][2] is True, "ler o edital com o Claude")
        # barra de progresso ligada à leitura que acontece na janela Planos do Contrato
        from planos.janela import _Sinal

        class JanelaFalsa:
            _sinal = _Sinal()

        jf = JanelaFalsa()
        dlg.abrir_planos = lambda *a, **k: jf
        dlg._ler_ia()
        jf._sinal.leitura.emit(37, "Lendo Edital.pdf, p. 1-30")
        check(dlg.barra_ia.isVisibleTo(dlg) and dlg.barra_ia.barra.value() == 37
              and "Edital.pdf" in dlg.barra_ia.lb_passo.text(), "barra de progresso na tela")
        with mock.patch.object(dlg, "analisar") as an_:
            jf._sinal.leitura_fim.emit(True, "Perfil montado")
        check(an_.called and dlg.barra_ia.barra.value() == 100, "fim da leitura: analisa de novo")
        jf._sinal.leitura.emit(50, "outra")
        check(dlg.barra_ia.barra.value() == 100, "desligada depois do fim")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("OK" if not FALHAS else f"{len(FALHAS)} falha(s)")
sys.exit(1 if FALHAS else 0)
