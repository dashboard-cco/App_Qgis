# -*- coding: utf-8 -*-
"""Ferramentas planos_* chamadas pelo Claude via MCP (rodam dentro do QGIS).

Trabalham na pasta do contrato aberta na janela "Planos do Contrato" (ou na última usada).
Assim o Claude Code / Claude Desktop, com a conta claude.ai da máquina, lê o edital e monta
o perfil do contrato sem precisar de chave de API.
"""
import json
import os

from . import checklist, documentos, perfil

JANELA = None          # janela aberta (registrada por JanelaPlanos)
ARQ_PERFIL = "contrato.json"
ARQ_ESTADO = "estado.json"
PASTA_TEXTOS = "textos"


# ------------------------------------------------------------------ contexto
def _pasta():
    if JANELA is not None:
        return JANELA.pasta
    try:
        from qgis.core import QgsProject, QgsSettings
        p = QgsProject.instance().readEntry("qgis_ia", "pasta_contrato", "")[0]
        if p and os.path.isdir(p):
            return p
        p = QgsSettings().value("qgis_ia/planos_pasta", "")
        if p and os.path.isdir(p):
            return p
    except ImportError:
        pass
    raise RuntimeError("Nenhum contrato aberto. Abra QGIS_IA → Planos do Contrato e escolha a pasta.")


def _estado(pasta):
    try:
        with open(os.path.join(pasta, ARQ_ESTADO), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"documentos": [], "servicos": [], "manuais": {}}


def _docs(pasta):
    cache = os.path.join(pasta, PASTA_TEXTOS)
    out = []
    for c in _estado(pasta).get("documentos", []):
        if os.path.exists(c):
            out.append(documentos.ler(c, cache))
    return out


def _doc(pasta, nome):
    docs = _docs(pasta)
    for d in docs:
        if d["nome"] == nome:
            return d
    alvo = checklist.norm(nome)
    for d in docs:
        if alvo and alvo in checklist.norm(d["nome"]):
            return d
    raise ValueError(f"Documento '{nome}' não encontrado. Disponíveis: {[d['nome'] for d in docs]}")


def _perfil(pasta):
    arq = os.path.join(pasta, ARQ_PERFIL)
    return perfil.carregar(arq) if os.path.exists(arq) else None


def _avisar_janela():
    if JANELA is not None:
        try:
            JANELA.perfil_alterado_externamente()
        except Exception:
            pass


# ------------------------------------------------------------------ ferramentas
def planos_situacao():
    pasta = _pasta()
    docs = _docs(pasta)
    p = _perfil(pasta)
    return {
        "pasta": pasta,
        "documentos": [{"nome": d["nome"], "paginas": len(d["paginas"]),
                        "tokens_aprox": documentos.tokens_estimados([d]),
                        "aviso": documentos.aviso_sem_texto(d)} for d in docs],
        "perfil": None if p is None else {
            "resumo": perfil.resumo(p),
            "secoes": {s: (len(p[s]) if s != "contrato" else
                           sum(1 for v in p["contrato"].values() if v)) for s in perfil.SECOES}},
        "servicos_escolhidos": _estado(pasta).get("servicos", []),
    }


def planos_indice(documento):
    d = _doc(_pasta(), documento)
    return {"documento": d["nome"], "total_paginas": len(d["paginas"]),
            "indice": documentos.indice(d)}


def planos_ler_paginas(documento, de, ate):
    return documentos.ler_paginas(_doc(_pasta(), documento), de, ate)


def planos_buscar(termos, documento=""):
    pasta = _pasta()
    docs = [_doc(pasta, documento)] if documento else _docs(pasta)
    achados = documentos.buscar(docs, termos)
    return {"termos": termos, "ocorrencias": len(achados), "achados": achados}


def planos_esquema(secao=""):
    if secao:
        if secao not in perfil.SECOES:
            raise ValueError(f"Seção inválida. Use uma de {list(perfil.SECOES)}")
        return perfil.ESQUEMA["properties"][secao]
    return perfil.ESQUEMA


def planos_ler_perfil(secao=""):
    p = _perfil(_pasta())
    if p is None:
        return {"perfil": None, "aviso": "Ainda não há perfil. Use planos_iniciar_perfil."}
    return p[secao] if secao else p


def planos_iniciar_perfil():
    pasta = _pasta()
    arq = os.path.join(pasta, ARQ_PERFIL)
    if os.path.exists(arq):
        os.replace(arq, os.path.join(pasta, "contrato_anterior.json"))
    p = perfil.vazio()
    p["_meta"]["origem"] = "Claude (MCP)"
    p["_meta"]["documentos"] = [d["nome"] for d in _docs(pasta)]
    perfil.salvar(p, arq)
    _avisar_janela()
    return {"ok": True, "arquivo": arq}


def planos_salvar_secao(secao, dados, acrescentar=False):
    if secao not in perfil.SECOES:
        raise ValueError(f"Seção inválida. Use uma de {list(perfil.SECOES)}")
    if isinstance(dados, str):
        try:
            dados = json.loads(dados)
        except ValueError:
            raise ValueError("'dados' deve ser JSON (objeto ou lista).")
    if secao == "camadas" and isinstance(dados, list):  # valor_padrao é opcional na prática
        for cam in dados:
            for f in (cam.get("campos") or []) if isinstance(cam, dict) else []:
                if isinstance(f, dict):
                    f.setdefault("valor_padrao", "")
    erros = perfil.valida(dados, perfil.ESQUEMA["properties"][secao], secao)
    if erros:
        return {"ok": False, "gravado": False, "erros": erros[:40],
                "total_erros": len(erros)}
    pasta = _pasta()
    arq = os.path.join(pasta, ARQ_PERFIL)
    p = _perfil(pasta) or perfil.vazio()
    p.setdefault("_meta", {}).setdefault("origem", "Claude (MCP)")
    if secao != "contrato" and acrescentar:
        p[secao] = list(p.get(secao) or []) + list(dados)
    else:
        p[secao] = dados
    perfil.salvar(p, arq)
    _avisar_janela()
    return {"ok": True, "gravado": True, "secao": secao,
            "itens": len(p[secao]) if secao != "contrato" else 1, "resumo": perfil.resumo(p)}


def planos_checklist():
    pasta = _pasta()
    p = _perfil(pasta)
    if p is None:
        raise RuntimeError("Ainda não há perfil do contrato.")
    from .janela import camadas_do_projeto, contar_preenchidos
    itens = checklist.gerar(p, camadas_do_projeto(), _estado(pasta), contar=contar_preenchidos)
    return {"pronto_para_gerar": checklist.pronto(itens), "placar": checklist.placar(itens),
            "itens": [{k: i[k] for k in ("grupo", "titulo", "status", "detalhe", "acao")}
                      for i in itens]}


def planos_validar(plano):
    """Valida um plano (.gdb/.gpkg) contra o perfil; resumo e problemas agrupados."""
    from . import estrutura, validacao
    pasta = _pasta()
    p = _perfil(pasta)
    if p is None:
        raise RuntimeError("Ainda não há perfil do contrato.")
    srv = estrutura.servicos_do_arquivo(p, plano) or _estado(pasta).get("servicos", [])
    r = validacao.validar(p, plano, srv, max_fids=20)
    return {"plano": r["plano"], "servicos": r["servicos"], "resumo": r["resumo"],
            "problemas": [{k: g[k] for k in ("severidade", "camada", "campo", "regra", "mensagem",
                                             "quantidade")} for g in r["erros"][:80]]}


def planos_o_que_falta(plano):
    """Camadas e campos que o perfil exige e o plano existente não tem."""
    from . import estrutura
    pasta = _pasta()
    p = _perfil(pasta)
    if p is None:
        raise RuntimeError("Ainda não há perfil do contrato.")
    srv = estrutura.servicos_do_arquivo(p, plano) or _estado(pasta).get("servicos", [])
    return estrutura.o_que_falta(p, plano, srv)


def planos_frota(plano):
    """Veículos e pessoal que o plano usa (pico por dia e turno) × o que o edital dá."""
    from . import frota
    pasta = _pasta()
    p = _perfil(pasta)
    if p is None:
        raise RuntimeError("Ainda não há perfil do contrato.")
    srv = estrutura_servicos(p, plano, pasta)
    r = frota.comparar(p, plano, srv)
    r["avisos"] = r["avisos"][:30]
    return r


def planos_adequar_frota(plano, metodo="auto", distancia=1500, max_receptores=3,
                         outra_regiao=False, aplicar=False, saida=""):
    """Proposta (ou gravação numa cópia) para o plano caber na frota do edital."""
    from . import frota
    pasta = _pasta()
    p = _perfil(pasta)
    if p is None:
        raise RuntimeError("Ainda não há perfil do contrato.")
    srv = estrutura_servicos(p, plano, pasta)
    pr = frota.propor(p, plano, srv, metodo=metodo, distancia=float(distancia),
                      max_receptores=int(max_receptores), outra_regiao=bool(outra_regiao))
    resumo = {k: pr[k] for k in ("plano", "servicos", "lote", "cabe", "nao_coube", "depois")}
    resumo["trocas"] = [{k: t[k] for k in ("nome_de", "turno", "nome_para", "circuitos")}
                        for t in pr["trocas"]]
    resumo["operacoes"] = [{"tipo": o["tipo"], "circuito": o["circuito"], "turno": o["turno"],
                            "km": o["carga"],
                            "vai_para": [{k: r[k] for k in ("codigo", "km", "carga_depois",
                                                            "dias_a_mais", "outra_regiao")}
                                         for r in o["recebem"]]} for o in pr["operacoes"]]
    if aplicar:
        resumo["gravado"] = frota.aplicar(p, plano, pr, saida or None)
    return resumo


def estrutura_servicos(p, plano, pasta):
    from . import estrutura
    return estrutura.servicos_do_arquivo(p, plano) or _estado(pasta).get("servicos", [])


TOOLS = {
    "planos_frota": planos_frota,
    "planos_adequar_frota": planos_adequar_frota,
    "planos_validar": planos_validar,
    "planos_o_que_falta": planos_o_que_falta,
    "planos_situacao": planos_situacao,
    "planos_indice": planos_indice,
    "planos_ler_paginas": planos_ler_paginas,
    "planos_buscar": planos_buscar,
    "planos_esquema": planos_esquema,
    "planos_ler_perfil": planos_ler_perfil,
    "planos_iniciar_perfil": planos_iniciar_perfil,
    "planos_salvar_secao": planos_salvar_secao,
    "planos_checklist": planos_checklist,
}
