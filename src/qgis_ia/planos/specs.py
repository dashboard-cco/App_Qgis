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
                                     "turnos", "pendencias"]}

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
        "Propõe como o plano fica como o edital pede: horários dos turnos do edital, muda de "
        "turno (ou troca) o equipamento que o edital não tem no turno, tira circuitos "
        "juntando-os a um vizinho ou dividindo-os entre vizinhos (mesmo turno/dias) e, com o "
        "histórico de operação (planilha de RDs: peso e tempo por circuito), respeita a jornada "
        "do edital (7h20): quem recebe tem de caber nela e circuitos acima dela passam linhas a "
        "vizinhos com folga; mostra as horas por dia que faltam. Pode passar circuitos para "
        "outro equipamento (equipar) e desdobrar: a sobra de munk vira circuitos novos mistos "
        "que saem de uma base e recebem circuitos do turno que falta e a parte acima da "
        "jornada. Redimensionar ao máximo (padrão): o que ainda passa do edital é repartido "
        "entre mais vizinhos, mais longe e também do outro turno, até a jornada; o que não "
        "couber volta em 'pontos' (o que levar ao órgão depois de ganhar a licitação). "
        "Com aplicar=true grava numa "
        "CÓPIA do plano (<nome>_adequado). [aplicar grava arquivo]",
        _obj({"plano": _s("caminho do .gdb/.gpkg do plano"),
              "metodo": {"type": "string", "enum": ["auto", "juntar", "dividir"]},
              "distancia": {"type": "number", "description": "vizinhos até (m); padrão 1500"},
              "max_receptores": _i("dividir entre no máximo N vizinhos (2 a 4)"),
              "historico": _s("opcional: planilha de RDs (.xlsx); padrão = a escolhida na aba "
                              "Frota e equipe"),
              "horarios": {"type": "boolean",
                           "description": "pôr o horário do turno do edital (padrão true)"},
              "mudar_turno": {"type": "boolean",
                              "description": "mudar de turno o equipamento que o edital não "
                                             "tem no turno, se houver sobra no outro (padrão true)"},
              "outra_regiao": {"type": "boolean",
                               "description": "em último caso, aceitar vizinho de outra região"},
              "equipar": {"type": "object",
                          "description": "circuitos que passam para outro equipamento antes de "
                                         "tudo: {codigo_circuito: codigo_equipamento}, ex.: "
                                         "{'182501': '1'} (munk faz o Noroeste); padrão = o "
                                         "escolhido na aba Frota e equipe"},
              "desdobrar": _s("base (DL/garagem/local de pesagem) de onde saem os circuitos "
                              "NOVOS mistos feitos com a sobra de equipamento, ex.: "
                              "'Sobradinho'; '' = não desdobrar; padrão = o escolhido na aba"),
              "equip_desdobrar": _s("código do equipamento cuja sobra vira circuitos novos "
                                    "(padrão: o munk)"),
              "redimensionar": {"type": "boolean",
                                "description": "redimensionar ao máximo para caber no edital "
                                               "(padrão: o escolhido na aba; precisa do "
                                               "histórico)"},
              "fechar": {"type": "boolean",
                         "description": "fechar a frota do edital com horas a mais: o turno que "
                                        "passa dos veículos fecha no número do edital e cada "
                                        "circuito vai até jornada_max; as horas a mais voltam "
                                        "em 'horas_a_mais' (padrão: o escolhido na aba)"},
              "jornada_max": {"type": "number",
                              "description": "limite por circuito ao fechar a frota, em horas "
                                             "(padrão 8.8333 = 8h50)"},
              "aplicar": {"type": "boolean", "description": "gravar numa cópia do plano"},
              "saida": _s("opcional: caminho da cópia")}, ["plano"])),
    "planos_o_que_falta": (
        "Camadas e campos que o perfil exige e que o plano existente ainda não tem, e registros "
        "vazios em campos com valor padrão no perfil (ex.: ciclo = 0).",
        _obj({"plano": _s("caminho do .gdb/.gpkg do plano")}, ["plano"])),
    "planos_importar_ligar": (
        "Trazer dados: liga automaticamente uma camada sua (shp, gpkg, gdb, geojson, kml, csv) a "
        "uma camada do plano (escolhe a camada pela geometria e campos, se não for dada). Devolve "
        "a ligação, os campos do destino (descrição, valores permitidos) e amostras da origem, "
        "para completar com planos_importar.",
        _obj({"origem": _s("caminho do arquivo/.gdb de origem"),
              "camada_origem": _s("nome da camada na origem (shapefile: nome do arquivo sem .shp)"),
              "plano": _s("caminho do .gdb/.gpkg do plano"),
              "camada_destino": _s("opcional: camada do plano")},
             ["origem", "camada_origem", "plano"])),
    "planos_importar": (
        "Trazer dados: prévia (aplicar=false) ou cópia das feições de uma camada sua para a "
        "camada do plano, convertendo tipos e valores para os códigos do contrato, reprojetando "
        "e ajustando a geometria. Antes de gravar faz cópia de segurança do plano. [aplicar grava arquivo]",
        _obj({"origem": _s("caminho do arquivo/.gdb de origem"),
              "camada_origem": _s("nome da camada na origem"),
              "plano": _s("caminho do .gdb/.gpkg do plano"),
              "camada_destino": _s("camada do plano"),
              "campos": {"type": "object",
                         "description": "correções da ligação automática: {campo_destino: "
                                        "{origem: campo da origem ou '', fixo: valor para todos, "
                                        "valores: {valor da origem: código permitido}}}"},
              "substituir": {"type": "boolean",
                             "description": "apagar antes as feições da camada do plano "
                                            "(padrão: acrescentar)"},
              "aplicar": {"type": "boolean", "description": "gravar (senão só prévia)"}},
             ["origem", "camada_origem", "plano", "camada_destino"])),
}
