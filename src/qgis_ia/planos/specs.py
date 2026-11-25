# -*- coding: utf-8 -*-
"""Descrição MCP das ferramentas planos_* (sem QGIS; usada pela ponte mcp_server.py)."""


def _obj(props=None, required=()):
    return {"type": "object", "properties": props or {}, "required": list(required)}


def _s(desc):
    return {"type": "string", "description": desc}


def _i(desc):
    return {"type": "integer", "description": desc}


_SECAO = {"type": "string", "enum": ["contrato", "documentos", "lotes", "servicos", "camadas",
                                     "entregaveis", "insumos", "regras", "recursos", "equipes",
                                     "pendencias"]}

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
    "planos_validar": (
        "Valida um plano (.gdb, .gpkg) contra o perfil do contrato: camadas, geometria, "
        "sistema, campos, tipos, obrigatórios, domínios e geometrias inválidas.",
        _obj({"plano": _s("caminho do .gdb/.gpkg do plano")}, ["plano"])),
    "planos_frota": (
        "Frota e equipe: veículos que o plano usa (pico por dia e turno) e pessoal (veículos × "
        "equipe padrão) comparados com o que o edital dá (seções recursos e equipes do perfil).",
        _obj({"plano": _s("caminho do .gdb/.gpkg do plano")}, ["plano"])),
    "planos_adequar_frota": (
        "Propõe como o plano cabe na frota do edital: troca equipamento que o edital não tem e "
        "tira circuitos juntando-os a um vizinho ou dividindo-os entre 2-3 vizinhos (mesmo "
        "turno/dias). Com aplicar=true grava numa CÓPIA do plano (<nome>_adequado). "
        "[aplicar grava arquivo]",
        _obj({"plano": _s("caminho do .gdb/.gpkg do plano"),
              "metodo": {"type": "string", "enum": ["auto", "juntar", "dividir"]},
              "distancia": {"type": "number", "description": "vizinhos até (m); padrão 1500"},
              "max_receptores": _i("dividir entre no máximo N vizinhos (2 ou 3)"),
              "outra_regiao": {"type": "boolean",
                               "description": "em último caso, aceitar vizinho de outra região"},
              "aplicar": {"type": "boolean", "description": "gravar numa cópia do plano"},
              "saida": _s("opcional: caminho da cópia")}, ["plano"])),
    "planos_o_que_falta": (
        "Camadas e campos que o perfil exige e que o plano existente ainda não tem, e registros "
        "vazios em campos com valor padrão no perfil (ex.: ciclo = 0).",
        _obj({"plano": _s("caminho do .gdb/.gpkg do plano")}, ["plano"])),
}
