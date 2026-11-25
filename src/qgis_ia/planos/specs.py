# -*- coding: utf-8 -*-
"""Descrição MCP das ferramentas planos_* (sem QGIS; usada pela ponte mcp_server.py)."""


def _obj(props=None, required=()):
    return {"type": "object", "properties": props or {}, "required": list(required)}


def _s(desc):
    return {"type": "string", "description": desc}


def _i(desc):
    return {"type": "integer", "description": desc}


_SECAO = {"type": "string", "enum": ["contrato", "documentos", "lotes", "servicos", "camadas",
                                     "entregaveis", "insumos", "regras", "pendencias"]}

SPECS = {
    "planos_situacao": (
        "App Planos do Contrato: pasta do contrato aberta no QGIS, documentos (nome, páginas, "
        "tokens) e o que já está no perfil do contrato.",
        _obj()),
    "planos_indice": (
        "Índice de um documento do contrato: títulos e itens numerados de cada página, para "
        "saber onde ler.",
        _obj({"documento": _s("nome do documento (como em planos_situacao)")}, ["documento"])),
    "planos_ler_paginas": (
        "Texto das páginas de um documento do contrato (até 30 páginas por chamada).",
        _obj({"documento": _s("nome do documento"), "de": _i("primeira página (1 = início)"),
              "ate": _i("última página")}, ["documento", "de", "ate"])),
    "planos_buscar": (
        "Procura termos nos documentos do contrato (sem diferenciar acento/maiúscula). Use '|' "
        "para alternativas, ex.: 'geodatabase|shapefile|gdb'. Devolve documento, página e trecho.",
        _obj({"termos": _s("texto a procurar; '|' separa alternativas"),
              "documento": _s("opcional: só neste documento")}, ["termos"])),
    "planos_esquema": (
        "Formato (JSON Schema) do perfil do contrato ou de uma seção dele.",
        _obj({"secao": dict(_SECAO, description="opcional: só esta seção")})),
    "planos_ler_perfil": (
        "Perfil do contrato atual (contrato.json), inteiro ou uma seção.",
        _obj({"secao": dict(_SECAO, description="opcional: só esta seção")})),
    "planos_iniciar_perfil": (
        "Começa um perfil do contrato vazio (o atual vira contrato_anterior.json). [grava arquivo]",
        _obj()),
    "planos_salvar_secao": (
        "Grava uma seção do perfil do contrato, validando pelo esquema. 'contrato' recebe um "
        "objeto; as demais, uma lista. Com acrescentar=true, junta a lista à que já existe "
        "(útil para salvar camadas em partes). Se houver erros, nada é gravado e eles voltam "
        "na resposta. [grava arquivo]",
        _obj({"secao": _SECAO,
              "dados": {"description": "objeto (contrato) ou lista (demais seções)"},
              "acrescentar": {"type": "boolean", "description": "juntar à lista existente"}},
             ["secao", "dados"])),
    "planos_checklist": (
        "Checklist do que falta para gerar o plano: compara o perfil com as camadas do "
        "projeto (tem / incompleto / falta / confirmar).",
        _obj()),
}
