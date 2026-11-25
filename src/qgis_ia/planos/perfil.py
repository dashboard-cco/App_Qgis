# -*- coding: utf-8 -*-
"""Perfil do contrato: o que o edital e as especificações exigem para gerar o plano.

É um dicionário JSON (salvo em contrato.json na pasta do contrato) com:
    contrato, documentos, lotes, servicos, camadas, entregaveis, insumos, regras, pendencias

Cada item traz "fonte" = {"documento": nome, "paginas": "12-13"} para conferência.
Sem QGIS: pode ser testado sozinho.
"""
import copy
import json
import os

VERSAO_PERFIL = 1


# ------------------------------------------------------------------ esquema JSON
def _obj(props, descricao=None):
    """Objeto com todos os campos obrigatórios e sem campos extras (exigência do
    structured output da API)."""
    o = {"type": "object", "properties": props, "required": list(props),
         "additionalProperties": False}
    if descricao:
        o["description"] = descricao
    return o


def _lista(item, descricao=None):
    o = {"type": "array", "items": item}
    if descricao:
        o["description"] = descricao
    return o


_S = {"type": "string"}
_B = {"type": "boolean"}
_LS = _lista(_S)
_FONTE = _obj({"documento": {"type": "string", "description": "nome do arquivo do documento"},
               "paginas": {"type": "string", "description": "página(s), ex.: '27' ou '27-28'"}})

GEOMETRIAS = ["ponto", "linha", "poligono", "tabela"]
TIPOS_CAMPO = ["texto", "inteiro", "decimal", "data", "data_hora", "booleano"]
TIPOS_INSUMO = ["camada_geografica", "tabela", "documento", "informacao"]
TIPOS_DOCUMENTO = ["edital", "termo_referencia", "anexo", "especificacao_tecnica", "outro"]
TIPOS_REGRA = ["formato", "validacao", "dimensionamento", "prazo", "outro"]

ESQUEMA = _obj({
    "contrato": _obj({
        "titulo": _S, "orgao": _S, "numero": _S,
        "objeto": {"type": "string", "description": "objeto do contrato, resumido"},
        "sistema_referencia": {"type": "string",
                               "description": "sistema de coordenadas exigido, ex.: 'SIRGAS 2000 / UTM 23S (EPSG:31983)'; vazio se não houver"},
        "prazo_entrega_plano": {"type": "string",
                                "description": "prazo para entregar o plano, ex.: '30 dias após a ordem de serviço'"},
    }),
    "documentos": _lista(_obj({
        "nome": _S,
        "tipo": {"type": "string", "enum": TIPOS_DOCUMENTO},
        "resumo": {"type": "string", "description": "uma frase sobre o conteúdo"},
        "contem_especificacoes": {"type": "boolean",
                                  "description": "true se o documento traz especificações técnicas do plano"},
    })),
    "lotes": _lista(_obj({
        "codigo": {"type": "string", "description": "ex.: '1', 'I', 'Lote 2'"},
        "nome": _S,
        "regioes": _lista(_S, "regiões/bairros/RAs do lote"),
        "fonte": _FONTE,
    })),
    "servicos": _lista(_obj({
        "codigo": {"type": "string", "description": "código usado no edital, ex.: 'P1'; se não houver, crie S1, S2..."},
        "sigla": {"type": "string", "description": "sigla usada nos arquivos, ex.: 'CC'; vazio se não houver"},
        "nome": _S,
        "unidade_medida": {"type": "string", "description": "ex.: 'tonelada', 'km varrido'"},
        "lotes": _lista(_S, "códigos dos lotes onde o serviço existe"),
        "frequencia": {"type": "string", "description": "frequência/turnos exigidos, resumidos"},
        "sob_demanda": _B,
        "fonte": _FONTE,
    })),
    "camadas": _lista(_obj({
        "nome": {"type": "string", "description": "nome exato exigido para a camada/tabela"},
        "descricao": _S,
        "geometria": {"type": "string", "enum": GEOMETRIAS},
        "servicos": _lista(_S, "códigos dos serviços que usam a camada (vazio = todos)"),
        "campos": _lista(_obj({
            "nome": {"type": "string", "description": "nome exato do campo"},
            "tipo": {"type": "string", "enum": TIPOS_CAMPO},
            "obrigatorio": _B,
            "descricao": _S,
            "valores_permitidos": _lista(_S, "valores/domínio, ex.: ['0 - Fim', '1 - Início']; vazio se livre"),
        })),
        "fonte": _FONTE,
    }), "camadas/tabelas que o plano entregue precisa ter"),
    "entregaveis": _lista(_obj({
        "nome": _S,
        "formato": {"type": "string", "description": "ex.: 'File Geodatabase (.gdb)', 'Excel (.xlsx)', 'Word (.docx)'"},
        "descricao": _S,
        "prazo": _S,
        "servicos": _LS,
        "fonte": _FONTE,
    })),
    "insumos": _lista(_obj({
        "nome": _S,
        "descricao": {"type": "string", "description": "o que é e para que serve no plano"},
        "tipo": {"type": "string", "enum": TIPOS_INSUMO},
        "obrigatorio": _B,
        "palavras_chave": _lista(_S, "palavras para reconhecer o insumo em nomes de camadas/arquivos, ex.: ['vias', 'logradouro', 'malha viária']"),
        "fornecido_pelo_contratante": {"type": "boolean",
                                       "description": "true se o edital diz que o órgão fornece"},
        "fonte": _FONTE,
    }), "o que a contratada precisa ter em mãos para elaborar o plano"),
    "regras": _lista(_obj({
        "descricao": _S,
        "tipo": {"type": "string", "enum": TIPOS_REGRA},
        "fonte": _FONTE,
    })),
    "pendencias": _lista(_S, "dúvidas, contradições ou informações que faltam nos documentos"),
})

LISTAS = ("documentos", "lotes", "servicos", "camadas", "entregaveis", "insumos", "regras",
          "pendencias")


# ------------------------------------------------------------------ validação
def valida(dado, esq=None, caminho=""):
    """Lista de erros do dado contra o esquema (tipos, enums, chaves obrigatórias e extras)."""
    esq = esq or ESQUEMA
    erros = []
    t = esq.get("type")
    if t == "object":
        if not isinstance(dado, dict):
            return [f"{caminho or 'raiz'}: deve ser objeto"]
        for k in esq["required"]:
            if k not in dado:
                erros.append(f"{caminho}.{k}: faltando".lstrip("."))
            else:
                erros += valida(dado[k], esq["properties"][k], f"{caminho}.{k}".lstrip("."))
        extras = [k for k in dado if k not in esq["properties"] and not k.startswith("_")]
        if extras:
            erros.append(f"{caminho or 'raiz'}: campos não previstos {extras}")
    elif t == "array":
        if not isinstance(dado, list):
            return [f"{caminho}: deve ser lista"]
        for i, x in enumerate(dado):
            erros += valida(x, esq["items"], f"{caminho}[{i}]")
    elif t == "string":
        if not isinstance(dado, str):
            erros.append(f"{caminho}: deve ser texto")
        elif "enum" in esq and dado not in esq["enum"]:
            erros.append(f"{caminho}: '{dado}' não é um de {esq['enum']}")
    elif t == "boolean" and not isinstance(dado, bool):
        erros.append(f"{caminho}: deve ser true/false")
    return erros


SECOES = ("contrato",) + LISTAS


# ------------------------------------------------------------------ uso
def vazio():
    p = {"contrato": {k: "" for k in ESQUEMA["properties"]["contrato"]["properties"]}}
    for k in LISTAS:
        p[k] = []
    p["_meta"] = {"versao": VERSAO_PERFIL}
    return p


def normaliza(p):
    """Completa chaves que faltem (perfil antigo ou editado à mão)."""
    base = vazio()
    out = copy.deepcopy(p or {})
    for k, v in base.items():
        if k not in out or out[k] is None:
            out[k] = v
    for k, v in base["contrato"].items():
        out["contrato"].setdefault(k, v)
    return out


def salvar(p, caminho):
    os.makedirs(os.path.dirname(os.path.abspath(caminho)), exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)
    os.replace(tmp, caminho)


def carregar(caminho):
    with open(caminho, encoding="utf-8") as f:
        return normaliza(json.load(f))


def fonte_txt(item):
    f = item.get("fonte") or {}
    doc, pag = f.get("documento", ""), f.get("paginas", "")
    if not doc and not pag:
        return ""
    return f"{doc}, p. {pag}" if pag else doc


def resumo(p):
    """Contagem curta para mostrar na janela."""
    return (f"{len(p['servicos'])} serviços · {len(p['lotes'])} lotes · "
            f"{len(p['camadas'])} camadas · {len(p['entregaveis'])} entregáveis · "
            f"{len(p['insumos'])} insumos · {len(p['pendencias'])} pendências")


# --------------------------------------------- perfil pronto: SLU-DF 90005/2026
_TIPO = {"str": "texto", "int": "inteiro", "int16": "inteiro", "real": "decimal",
         "datetime": "data_hora"}
_GEOM = {"Point": "ponto", "MultiLineString": "linha", "MultiPolygon": "poligono"}


def perfil_slu_df():
    """Perfil do Pregão 90005/2026 (SLU-DF) montado a partir de edital_slu.py, que foi
    escrito e conferido à mão. Serve de perfil pronto e de gabarito para a leitura por IA."""
    try:
        from .. import edital_slu as E
    except ImportError:
        import edital_slu as E

    anexo_g = "09-PREGAO-90005-26-Anexo-G"
    edital = "02-PREGAO-90005-26-Edital"
    p = vazio()
    p["contrato"].update({
        "titulo": "Pregão Presencial 90005/2026 — Limpeza urbana do Distrito Federal",
        "orgao": "SLU-DF — Serviço de Limpeza Urbana do Distrito Federal",
        "numero": "90005/2026",
        "objeto": "Coleta, varrição e serviços complementares de limpeza urbana em 3 lotes.",
        "sistema_referencia": f"SIRGAS 2000 / UTM 23S (EPSG:{E.EPSG})",
        "prazo_entrega_plano": "",
    })
    p["documentos"] = [
        {"nome": edital, "tipo": "edital", "resumo": "Edital e Termo de Referência.",
         "contem_especificacoes": True},
        {"nome": anexo_g, "tipo": "anexo",
         "resumo": "Roteiro de elaboração dos Planos de Serviço (padrão dos dados geográficos).",
         "contem_especificacoes": True},
        {"nome": "20-PREGAO-90005-26-Anexo-R", "tipo": "anexo",
         "resumo": "Quantidades de mão de obra e equipamentos por lote.",
         "contem_especificacoes": True},
    ]
    p["lotes"] = [{"codigo": str(n), "nome": f"Lote {n}",
                   "regioes": [E.RA[r] for r in sorted(ras)],
                   "fonte": {"documento": edital, "paginas": "27-28"}}
                  for n, ras in E.RA_POR_LOTE.items()]
    grupos_camadas = {}
    for cod, s in E.SERVICOS.items():
        p["servicos"].append({
            "codigo": cod, "sigla": s["sigla"] or "", "nome": s["nome"], "unidade_medida": "",
            "lotes": ["1", "2", "3"], "frequencia": "",
            "sob_demanda": cod in E.SERVICOS_TRIMESTRAIS,
            "fonte": {"documento": anexo_g, "paginas": ""}})
        if s["grupo"] != "sem_gdb":
            grupos_camadas.setdefault(s["grupo"], []).append(cod)

    # camadas: a mesma camada aparece em vários grupos; junta os serviços
    camadas = {}
    for grupo, servs in grupos_camadas.items():
        for c in E.esquema(servs[0], 1):
            chave = (c["nome"], grupo)
            doms = E.dominios(servs[0], 1)
            campos = []
            for f in c["campos"]:
                vals = []
                if f["dominio"] and f["dominio"] in doms:
                    vals = [f"{k} - {v}" if str(k) != str(v) else str(v)
                            for k, v in doms[f["dominio"]][2].items()]
                campos.append({"nome": f["nome"], "tipo": _TIPO.get(f["tipo"], "texto"),
                               "obrigatorio": True, "descricao": f["apelido"] or "",
                               "valores_permitidos": vals})
            camadas[chave] = {"nome": c["nome"], "descricao": f"Camada do grupo {grupo}",
                              "geometria": _GEOM.get(c["geometria"], "tabela"),
                              "servicos": list(servs), "campos": campos,
                              "fonte": {"documento": anexo_g, "paginas": ""}}
    p["camadas"] = list(camadas.values())

    sob = list(E.SERVICOS_TRIMESTRAIS)
    com_gdb = [c for c, s in E.SERVICOS.items() if s["grupo"] != "sem_gdb"]
    p["entregaveis"] = [
        {"nome": "Plano em File Geodatabase", "formato": "File Geodatabase (.gdb)",
         "descricao": "Um .gdb por serviço e lote (ex.: CC01.gdb), com as camadas do Anexo G.",
         "prazo": "", "servicos": com_gdb, "fonte": {"documento": anexo_g, "paginas": ""}},
        {"nome": "Tabela de atributos", "formato": "Excel (.xlsx)",
         "descricao": "Atributos dos circuitos.", "prazo": "", "servicos": com_gdb,
         "fonte": {"documento": anexo_g, "paginas": ""}},
        {"nome": "Programação trimestral", "formato": "Excel (.xlsx)",
         "descricao": "Programação dos serviços sob demanda por trimestre.", "prazo": "",
         "servicos": sob, "fonte": {"documento": anexo_g, "paginas": ""}},
        {"nome": "Texto do plano", "formato": "Word (.docx)",
         "descricao": "Seções: " + "; ".join(s[0] for s in E.SECOES_DOCX) + ".",
         "prazo": "", "servicos": list(E.SERVICOS),
         "fonte": {"documento": edital, "paginas": ""}},
    ]
    p["insumos"] = [
        _ins("Rede viária (eixos de vias)", "Base para desenhar os circuitos sobre as vias.",
             "camada_geografica", ["vias", "via", "logradouro", "eixo", "malha", "sistema_viario"]),
        _ins("Limites das Regiões Administrativas e lotes",
             "Para preencher codigo_ra e conferir se o circuito está no lote certo.",
             "camada_geografica", ["regioes", "ra", "regiao_administrativa", "lote", "limite"]),
        _ins("Plano de coleta atual (circuitos existentes)",
             "Ponto de partida para redesenhar os circuitos.", "camada_geografica",
             ["circuito", "plano", "rota", "coleta"], obrigatorio=False),
        _ins("Contêineres/LEVs e pontos de entrega", "Para a camada st_conteiner (coleta).",
             "camada_geografica", ["conteiner", "container", "lev", "papa", "ponto_entrega"],
             obrigatorio=False),
        _ins("Frota por lote e turno (Anexo R)", "Para dimensionar circuitos e soltura.",
             "tabela", ["frota", "anexo_r", "veiculos"], fornecido=True),
        _ins("Veículos e placas", "Relação de veículos com placas para o texto do plano.",
             "informacao", ["placa", "veiculo"]),
        _ins("Equipe e contatos", "Preposto e responsáveis (nome, função, telefone, e-mail).",
             "informacao", ["equipe", "contato", "preposto"]),
        _ins("Locais de destinação e pesagem", "Valores dos campos local_destinacao e local_pesagem.",
             "informacao", ["destinacao", "pesagem", "transbordo", "aterro"], fornecido=True),
    ]
    p["regras"] = [
        {"descricao": f"Dados em SIRGAS 2000 / UTM 23S (EPSG:{E.EPSG}).", "tipo": "formato",
         "fonte": {"documento": anexo_g, "paginas": ""}},
        {"descricao": "Não renomear camadas nem campos dos modelos do SLU.", "tipo": "formato",
         "fonte": {"documento": anexo_g, "paginas": ""}},
        {"descricao": f"codigo_ra entre {E.RA_MIN} e {E.RA_MAX}.", "tipo": "validacao",
         "fonte": {"documento": anexo_g, "paginas": ""}},
        {"descricao": "Textos em Word, Arial 12 no corpo e 14 nos títulos.", "tipo": "formato",
         "fonte": {"documento": edital, "paginas": ""}},
    ]
    p["_meta"]["origem"] = "perfil pronto SLU-DF (edital_slu.py)"
    return p


def _ins(nome, desc, tipo, chaves, obrigatorio=True, fornecido=False):
    return {"nome": nome, "descricao": desc, "tipo": tipo, "obrigatorio": obrigatorio,
            "palavras_chave": chaves, "fornecido_pelo_contratante": fornecido,
            "fonte": {"documento": "", "paginas": ""}}


PERFIS_PRONTOS = {"SLU-DF — Pregão 90005/2026": perfil_slu_df}
