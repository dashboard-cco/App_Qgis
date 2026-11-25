# -*- coding: utf-8 -*-
"""
Testes do app "Planos do Contrato" (documentos, perfil, checklist e janela).
Não chama a IA (não gasta nada).

    "C:\\Program Files\\QGIS 3.44.15\\bin\\python-qgis-ltr.bat" tests\\test_planos.py
"""
import json
import os
import shutil
import sys
import tempfile
import zipfile

AQUI = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(AQUI, "..", "src")
PLUGIN = os.path.join(SRC, "qgis_ia")
EDITAL = os.path.join(AQUI, "..", "Edital")
sys.path.insert(0, PLUGIN)

from planos import checklist, config_ia, documentos, extracao, perfil  # noqa: E402

FALHAS = []


def check(cond, msg):
    if not cond:
        FALHAS.append(msg)
        print("FALHOU:", msg)


# ------------------------------------------------------------ esquema
def percorre(o, caminho="raiz"):
    if o.get("type") == "object":
        check(o.get("additionalProperties") is False, f"{caminho}: additionalProperties")
        check(sorted(o["required"]) == sorted(o["properties"]), f"{caminho}: required")
        for k, v in o["properties"].items():
            percorre(v, f"{caminho}.{k}")
    elif o.get("type") == "array":
        percorre(o["items"], caminho + "[]")


percorre(perfil.ESQUEMA)
check(set(perfil.LISTAS) <= set(perfil.ESQUEMA["properties"]), "LISTAS no esquema")


def valida(dado, esq, caminho="raiz"):
    """Validação simples do perfil contra o esquema (tipos, enums, chaves)."""
    t = esq.get("type")
    if t == "object":
        check(isinstance(dado, dict), f"{caminho} não é objeto")
        for k in esq["required"]:
            check(k in dado, f"{caminho}: falta {k}")
            if k in dado:
                valida(dado[k], esq["properties"][k], f"{caminho}.{k}")
    elif t == "array":
        check(isinstance(dado, list), f"{caminho} não é lista")
        for i, x in enumerate(dado):
            valida(x, esq["items"], f"{caminho}[{i}]")
    elif t == "string":
        check(isinstance(dado, str), f"{caminho} não é texto: {dado!r}")
        if "enum" in esq:
            check(dado in esq["enum"], f"{caminho}: {dado!r} fora de {esq['enum']}")
    elif t == "boolean":
        check(isinstance(dado, bool), f"{caminho} não é booleano")


# ------------------------------------------------------------ perfil pronto SLU-DF
p = perfil.perfil_slu_df()
sem_meta = {k: v for k, v in p.items() if k != "_meta"}
valida(sem_meta, perfil.ESQUEMA)
check(len(p["servicos"]) == 12, f"12 serviços: {len(p['servicos'])}")
check(len(p["lotes"]) == 3, "3 lotes")
nomes = {c["nome"] for c in p["camadas"]}
check({"st_circuito_inicio_fim", "st_circuito_planejado", "st_conteiner", "st_quantificacao",
       "lm_area_circuito_planejado"} <= nomes, f"camadas: {nomes}")
area_coleta = next(c for c in p["camadas"]
                   if c["nome"] == "lm_area_circuito_planejado" and "P1" in c["servicos"])
check("local_pesagem" in [f["nome"] for f in area_coleta["campos"]], "local_pesagem na coleta")
ra = next(f for f in area_coleta["campos"] if f["nome"] == "codigo_ra")
check("1 - Plano Piloto" in ra["valores_permitidos"], "domínio de RA")
check(any(e["formato"].startswith("File Geodatabase") for e in p["entregaveis"]), "entregável gdb")

tmp = tempfile.mkdtemp(prefix="planos_")
try:
    arq = os.path.join(tmp, "sub", "contrato.json")
    perfil.salvar(p, arq)
    p2 = perfil.carregar(arq)
    check(p2["servicos"] == p["servicos"], "salvar/carregar")
    with open(arq, "w", encoding="utf-8") as f:
        json.dump({"contrato": {"titulo": "X"}, "servicos": []}, f)
    p3 = perfil.carregar(arq)
    check(p3["camadas"] == [] and p3["contrato"]["orgao"] == "", "normaliza perfil incompleto")
    check("12 serviços" in perfil.resumo(p), perfil.resumo(p))
    check(perfil.fonte_txt({"fonte": {"documento": "Ed", "paginas": "3"}}) == "Ed, p. 3", "fonte_txt")

    # ------------------------------------------------------------ documentos
    anexo_r = [f for f in os.listdir(EDITAL) if "Anexo-R" in f]
    if anexo_r:
        cache = os.path.join(tmp, "textos")
        d = documentos.ler(os.path.join(EDITAL, anexo_r[0]), cache)
        check(len(d["paginas"]) == 21, f"Anexo R 21 páginas: {len(d['paginas'])}")
        check(d["chars"] > 10000, "Anexo R tem texto")
        check(documentos.aviso_sem_texto(d) == "", "não é escaneado")
        check(len(os.listdir(cache)) == 1, "cache gravado")
        d2 = documentos.ler(os.path.join(EDITAL, anexo_r[0]), cache)
        check(d2 == d, "cache lido")
        txt = documentos.texto_para_ia([d])
        check(txt.startswith(f'<documento nome="{d["nome"]}"') and "[pág. 21]" in txt, "marcadores")
        t, custo = extracao.estimativa([d])
        check(3000 < t < 10000 and 0 < custo < 2, f"estimativa {t} {custo}")
    else:
        print("aviso: Anexo R não encontrado, pulando leitura de PDF")

    docx = os.path.join(tmp, "espec.docx")
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml",
                   "<w:document><w:body><w:p><w:r><w:t>Camada st_rota &amp; campos</w:t></w:r></w:p>"
                   "<w:p><w:r><w:t>Segunda linha</w:t></w:r></w:p></w:body></w:document>")
    d = documentos.ler(docx)
    check("Camada st_rota & campos\nSegunda linha" in d["paginas"][0], f"docx: {d['paginas']}")
    txt = os.path.join(tmp, "nota.txt")
    with open(txt, "w", encoding="cp1252") as f:
        f.write("Especificação técnica\n" + "x" * 7000)
    d = documentos.ler(txt)
    check(d["paginas"][0].startswith("Especificação") and len(d["paginas"]) >= 2, "txt cp1252 fatiado")
    try:
        documentos.ler(os.path.join(tmp, "a.xls"))
        check(False, "xls deveria falhar")
    except ValueError:
        pass
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ------------------------------------------------------------ checklist
check(checklist.norm("Região_Administrativa  2") == "regiao_administrativa_2", "norm")
camadas_prj = [
    {"id": "v", "nome": "Vias DF", "tabela": "eixos_vias", "geometria": "linha",
     "campos": ["nome"], "feicoes": 100},
    {"id": "r", "nome": "regioes_administrativas", "tabela": "", "geometria": "poligono",
     "campos": ["ra"], "feicoes": 35},
    {"id": "c", "nome": "st_circuito_planejado", "tabela": "st_circuito_planejado",
     "geometria": "linha", "campos": ["lote", "codigo_circuito", "codigo_ra", "deslocamento"],
     "feicoes": 10},
    {"id": "i", "nome": "st_circuito_inicio_fim", "tabela": "st_circuito_inicio_fim",
     "geometria": "ponto", "campos": ["lote"], "feicoes": 0},
]


def contar(id_, campos):
    return {c: (5 if c == "codigo_ra" else 10) for c in campos}


estado = {"servicos": ["P1"], "manuais": {}}
itens = checklist.gerar(p, camadas_prj, estado, contar)
por = {i["titulo"]: i for i in itens}
check(por["Rede viária (eixos de vias)"]["status"] == checklist.OK, "vias achadas")
check("Vias DF" in por["Rede viária (eixos de vias)"]["detalhe"], "nome da camada de vias")
check(por["Limites das Regiões Administrativas e lotes"]["status"] == checklist.OK, "RAs achadas")
check(por["Veículos e placas"]["status"] == checklist.CONFIRMAR, "informação a confirmar")
check(por["Frota por lote e turno (Anexo R)"]["status"] == checklist.FALTA, "frota falta")
check("contratante" in por["Frota por lote e turno (Anexo R)"]["acao"], "dica do contratante")
cp = [i for i in itens if i["titulo"].startswith("st_circuito_planejado")]
check(len(cp) == 1, f"só a camada da coleta (filtro P1): {[i['titulo'] for i in cp]}")
check(cp[0]["status"] == checklist.PARCIAL and "codigo_ra (5 de 10)" in cp[0]["detalhe"],
      f"campo vazio: {cp[0]['detalhe']}")
ini = [i for i in itens if i["titulo"].startswith("st_circuito_inicio_fim")][0]
check(ini["status"] == checklist.PARCIAL and "camada vazia" in ini["detalhe"]
      and "faltam campos" in ini["detalhe"], ini["detalhe"])
check(not any(i["titulo"].startswith("st_quantificacao") for i in itens), "varrição filtrada")
check(any(i["titulo"].startswith("st_conteiner") and i["status"] == checklist.FALTA for i in itens),
      "conteiner falta")
check(not checklist.pronto(itens), "não está pronto (frota falta)")
grupos = [i["grupo"] for i in itens]
check(grupos == sorted(grupos, key=checklist.GRUPOS.index), "ordem dos grupos")

estado["manuais"]["insumo|Frota por lote e turno (Anexo R)"] = True
itens = checklist.gerar(p, camadas_prj, estado, contar)
check(checklist.pronto(itens), "pronto depois de confirmar a frota")
n = checklist.placar(itens)
check(n["falta"] >= 1 and n["ok"] >= 3, f"placar {n}")
todos = checklist.gerar(p, camadas_prj, {"servicos": []})
check(any(i["titulo"].startswith("st_quantificacao") for i in todos), "sem filtro mostra tudo")
p_pend = dict(p, pendencias=["Prazo do plano não informado"])
it = [i for i in checklist.gerar(p_pend, [], {}) if i["grupo"] == checklist.GRUPOS[3]]
check(it and it[0]["status"] == checklist.CONFIRMAR, "pendência a confirmar")
it = [i for i in checklist.gerar(p_pend, [], {"manuais": {"pendencia|0": True}})
      if i["grupo"] == checklist.GRUPOS[3]]
check(it[0]["status"] == checklist.OK, "pendência resolvida")

# ------------------------------------------------------------ conta da IA
check(config_ia.mascarar("sk-ant-api03-abcdefghijklmnop") == "sk-ant-api…mnop", "mascarar")

# ------------------------------------------------------------ validação do perfil
check(perfil.valida(sem_meta) == [], f"perfil pronto válido: {perfil.valida(sem_meta)[:3]}")
err = perfil.valida([{"nome": "x", "geometria": "círculo"}],
                    perfil.ESQUEMA["properties"]["camadas"], "camadas")
check(any("círculo" in e for e in err) and any("campos: faltando" in e for e in err), f"erros: {err}")
check(perfil.valida({"titulo": 1}, perfil.ESQUEMA["properties"]["contrato"], "contrato"),
      "contrato inválido")

# ------------------------------------------------------------ índice e busca
doc_fake = {"nome": "Edital X", "paginas": [
    "PREGÃO ELETRÔNICO\ntexto qualquer de abertura do edital\n1. DO OBJETO\nContratação...",
    "4.6 Os dados deverão estar em SIRGAS 2000\nTabela 3 - Campos\nO plano de serviço será entregue",
    "sem títulos aqui só texto corrido e mais texto"]}
ind = documentos.indice(doc_fake)
check([i["pagina"] for i in ind] == [1, 2], f"índice páginas {ind}")
check("1. DO OBJETO" in ind[0]["linhas"] and "PREGÃO ELETRÔNICO" in ind[0]["linhas"], f"{ind[0]}")
check(any(l.startswith("Tabela 3") for l in ind[1]["linhas"]), "tabela no índice")
ach = documentos.buscar([doc_fake], "plano de servico|sirgas")
check(len(ach) == 2 and ach[0]["pagina"] == 2, f"busca {ach}")
check("serviço" in ach[-1]["trecho"] or "serviço" in ach[0]["trecho"], "trecho com acento original")
lp = documentos.ler_paginas(doc_fake, 2, 99)
check(lp["de"] == 2 and lp["ate"] == 3 and "[pág. 3]" in lp["texto"], f"ler_paginas {lp['ate']}")

# ------------------------------------------------------------ leitor Claude (sem chamar)
from planos import leitor_claude as LC  # noqa: E402
env = LC.ambiente({"ANTHROPIC_API_KEY": "x", "PATH": "p"})
check(env == {"PATH": "p"}, "ambiente sem chave de API")
args = LC.argumentos("C:/x/.mcp.json")
check(args[args.index("--tools") + 1] == "" and "--strict-mcp-config" in args
      and args[args.index("--allowedTools") + 1] == "mcp__qgis-planos", f"args {args}")
cfg = LC.config_mcp("py.exe", "ponte.py", "127.0.0.1", 9876, "tok")
check(cfg["mcpServers"]["qgis-planos"]["env"]["QGIS_IA_FERRAMENTAS"] == "planos_", "filtro")
ev = LC.interpretar(json.dumps({"type": "assistant", "message": {"content": [
    {"type": "tool_use", "name": "mcp__qgis-planos__planos_ler_paginas",
     "input": {"documento": "Edital", "de": 1, "ate": 30}}]}}))
check(ev == {"tipo": "passo", "texto": "Lendo Edital, p. 1-30"}, f"evento {ev}")
ev = LC.interpretar(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                                "result": "Pronto", "total_cost_usd": 1.2, "num_turns": 9}))
check(ev["tipo"] == "fim" and ev["ok"] and ev["texto"] == "Pronto", f"fim {ev}")
ev = LC.interpretar(json.dumps({"type": "system", "subtype": "init",
                                "mcp_servers": [{"name": "qgis-planos", "status": "failed"}]}))
check(ev["tipo"] == "fim" and not ev["ok"], "mcp falhou")
check(LC.interpretar("lixo") is None, "linha inválida")
check(isinstance(LC.achar_claude(), str), "achar_claude")

# ------------------------------------------------------------ janela (QGIS sem tela)
try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from qgis.core import QgsApplication, QgsProject, QgsVectorLayer
    qgs = QgsApplication([], False)
    qgs.initQgis()
except ImportError:
    qgs = None
    print("aviso: QGIS não disponível, pulando teste da janela")

if qgs:
    from unittest import mock
    from planos import janela as J

    class Iface:
        def mainWindow(self):
            return None

    tmp = tempfile.mkdtemp(prefix="planos_ui_")
    try:
        with mock.patch.object(J.QgsSettings, "value", return_value=""):
            jan = J.JanelaPlanos(Iface())
        jan._abrir_pasta(tmp)
        check(jan.perfil is None, "pasta nova sem perfil")
        with mock.patch.object(J.QMessageBox, "question",
                               return_value=J.QMessageBox.StandardButton.Yes):
            jan.cb_pronto.setCurrentIndex(1)
            jan._usar_pronto(1)
        check(jan.perfil and len(jan.perfil["servicos"]) == 12, "perfil pronto carregado")
        check(os.path.exists(os.path.join(tmp, "contrato.json")), "contrato.json gravado")
        raiz = jan.arv_req.topLevelItemCount()
        check(raiz >= 8, f"árvore de requisitos {raiz}")
        # marca P1 na árvore
        serv = next(jan.arv_req.topLevelItem(i) for i in range(raiz)
                    if jan.arv_req.topLevelItem(i).text(0).startswith("Serviços"))
        serv.child(0).setCheckState(0, J._MARCADO)
        check(jan.estado["servicos"] == ["P1"], f"serviço marcado: {jan.estado['servicos']}")

        vias = QgsVectorLayer("LineString?crs=EPSG:31983&field=nome:string", "malha viaria", "memory")
        QgsProject.instance().addMapLayer(vias)
        cp = QgsVectorLayer("MultiLineString?crs=EPSG:31983&field=lote:string&field=codigo_ra:integer",
                            "st_circuito_planejado", "memory")
        QgsProject.instance().addMapLayer(cp)
        f = J.contar_preenchidos(cp.id(), ["lote"])
        check(f == {"lote": 0}, f"contar em camada vazia {f}")
        descr = {c["nome"]: c for c in J.camadas_do_projeto()}
        check(descr["st_circuito_planejado"]["geometria"] == "linha", "geometria linha")
        jan._atualizar_checklist()
        # perfil pronto não tem pendências: insumos, camadas e entregáveis
        check(jan.arv_chk.topLevelItemCount() == 3, f"grupos {jan.arv_chk.topLevelItemCount()}")
        texto = []
        for gi in range(jan.arv_chk.topLevelItemCount()):
            g = jan.arv_chk.topLevelItem(gi)
            for k in range(g.childCount()):
                texto.append(g.child(k).text(0) + " | " + g.child(k).text(1))
        check(any("🟢 Rede viária" in t and "malha viaria" in t for t in texto), "vias verdes na janela")
        check(any(t.startswith("🟡 st_circuito_planejado") for t in texto), "camada incompleta amarela")
        # confirma um insumo pela caixa
        g0 = jan.arv_chk.topLevelItem(0)
        alvo = next(g0.child(k) for k in range(g0.childCount())
                    if "Veículos e placas" in g0.child(k).text(0))
        alvo.setCheckState(0, J._MARCADO)
        check(jan.estado["manuais"].get("insumo|Veículos e placas") is True, "manual gravado")
        with open(os.path.join(tmp, "estado.json"), encoding="utf-8") as fh:
            check(json.load(fh)["manuais"].get("insumo|Veículos e placas") is True, "estado.json")
        check("Ainda falta" in jan.lb_placar.text() or "Pronto" in jan.lb_placar.text(), "placar")

        # ferramentas MCP planos_* (o que o Claude chama)
        from planos import ferramentas as F
        check(F.JANELA is jan, "janela registrada")
        anexo = [f for f in os.listdir(EDITAL) if "Anexo-R" in f]
        if anexo:
            jan.estado["documentos"] = [os.path.normpath(os.path.join(EDITAL, anexo[0]))]
            jan._salvar_estado()
            sit = F.planos_situacao()
            check(sit["documentos"][0]["paginas"] == 21, f"situação {sit['documentos']}")
            nome = sit["documentos"][0]["nome"]
            check(F.planos_indice(nome)["total_paginas"] == 21, "índice")
            check(F.planos_ler_paginas("Anexo-R", 1, 2)["ate"] == 2, "ler por trecho do nome")
            b = F.planos_buscar("caminhao|compactador")
            check(b["ocorrencias"] > 0, "buscar no Anexo R")
        F.planos_iniciar_perfil()
        check(os.path.exists(os.path.join(tmp, "contrato_anterior.json")), "backup do perfil")
        r = F.planos_salvar_secao("servicos", [{"codigo": "P1"}])
        check(r["ok"] is False and r["erros"], "seção inválida não grava")
        s1 = perfil.perfil_slu_df()["servicos"][:2]
        r = F.planos_salvar_secao("servicos", s1)
        check(r["ok"] and r["itens"] == 2, f"grava serviços {r}")
        r = F.planos_salvar_secao("servicos", json.dumps(s1[:1]), acrescentar=True)
        check(r["ok"] and r["itens"] == 3, "acrescentar (dados em texto JSON)")
        QgsApplication.processEvents()
        jan._recarregar_perfil_silencioso()
        check(len(jan.perfil["servicos"]) == 3, "janela recarregou o perfil")
        check(F.planos_ler_perfil("servicos")[0]["codigo"] == "P1", "ler perfil")
        check("pronto_para_gerar" in F.planos_checklist(), "checklist por MCP")
        try:
            F.planos_salvar_secao("xyz", [])
            check(False, "seção desconhecida deveria falhar")
        except ValueError:
            pass
        jan.desligar()
        check(F.JANELA is None, "janela desregistrada")
        QgsProject.instance().removeAllMapLayers()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

print("OK" if not FALHAS else f"{len(FALHAS)} FALHA(S)")
sys.exit(1 if FALHAS else 0)
