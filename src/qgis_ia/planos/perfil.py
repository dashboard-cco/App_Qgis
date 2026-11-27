# -*- coding: utf-8 -*-
"""Perfil do contrato: o que o edital e as especificações exigem para gerar o plano.

É um dicionário JSON (salvo em contrato.json na pasta do contrato) com:
    contrato, documentos, lotes, servicos, camadas, entregaveis, insumos, regras, recursos,
    equipes, turnos, pendencias

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
CATEGORIAS_RECURSO = ["equipamento", "pessoal"]

ESQUEMA = _obj({
    "contrato": _obj({
        "titulo": _S, "orgao": _S, "numero": _S,
        "objeto": {"type": "string", "description": "objeto do contrato, resumido"},
        "sistema_referencia": {"type": "string",
                               "description": "sistema de coordenadas exigido, ex.: 'SIRGAS 2000 / UTM 23S (EPSG:31983)'; vazio se não houver"},
        "prazo_entrega_plano": {"type": "string",
                                "description": "prazo para entregar o plano, ex.: '30 dias após a ordem de serviço'"},
        "municipio": {"type": "string",
                      "description": "município(s) atendido(s), separados por ';' (ex.: 'Brasília'); "
                                     "serve para baixar limites (IBGE) e vias (OpenStreetMap)"},
        "uf": {"type": "string", "description": "sigla do estado, ex.: 'DF'"},
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
            "tamanho": {"type": "integer", "description": "tamanho máximo de texto; 0 se não informado"},
            "obrigatorio": _B,
            "descricao": _S,
            "valores_permitidos": _lista(_S, "valores/domínio, ex.: ['0 - Fim', '1 - Início']; vazio se livre"),
            "valor_padrao": {"type": "string",
                             "description": "valor para os registros sem informação (ex.: '0' em ciclo quando "
                                            "a coleta é semanal); vazio se não houver"},
        })),
        "fonte": _FONTE,
    }), "camadas/tabelas que o plano entregue precisa ter"),
    "entregaveis": _lista(_obj({
        "nome": _S,
        "formato": {"type": "string", "description": "ex.: 'File Geodatabase (.gdb)', 'Excel (.xlsx)', 'Word (.docx)'"},
        "descricao": _S,
        "prazo": _S,
        "servicos": _LS,
        "nome_arquivo": {"type": "string",
                         "description": "padrão do nome do arquivo exigido, com {sigla}, {lote} "
                                        "(2 dígitos), {codigo} ou {servico}, ex.: '{sigla}{lote}.gdb'; "
                                        "vazio se o edital não diz"},
        "secoes": _lista(_S, "títulos das seções/capítulos exigidos no texto (na ordem do edital); "
                             "vazio se não for texto"),
        "como_fazer": {"type": "string",
                       "description": "instruções do edital de como o arquivo deve ser feito "
                                      "(conteúdo, formatação, fonte, escala…), resumidas"},
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
    "recursos": _lista(_obj({
        "servico": {"type": "string", "description": "código do serviço, ex.: 'P1'"},
        "lote": {"type": "string", "description": "código do lote; vazio se vale para todos"},
        "categoria": {"type": "string", "enum": CATEGORIAS_RECURSO},
        "nome": {"type": "string", "description": "veículo/equipamento ou função, como no edital, ex.: 'Compactador de 19 m³', 'Motorista', 'Coletor'"},
        "codigo_no_plano": {"type": "string", "description": "equipamento: código do valor permitido do campo de tipo de equipamento do plano, ex.: '0' para '0 - Caminhão Coletor Compactador de 19 m³'; vazio se não souber ou se for pessoal"},
        "diurno": {"type": "integer", "description": "quantidade no turno diurno (0 se não houver)"},
        "noturno": {"type": "integer", "description": "quantidade no turno noturno (0 se não houver)"},
        "domingo": {"type": "boolean", "description": "true se também trabalha aos domingos"},
        "fonte": _FONTE,
    }), "frota e mão de obra que o edital dá por serviço, lote e turno (ex.: tabela de quantidades)"),
    "equipes": _lista(_obj({
        "servico": _S,
        "nome": {"type": "string", "description": "ex.: 'Equipe Padrão de Coleta Seletiva'"},
        "equipamento": {"type": "string", "description": "veículo da equipe, como no edital"},
        "codigo_no_plano": {"type": "string", "description": "código do equipamento no campo de tipo de equipamento do plano; vazio se não souber"},
        "funcoes": _lista(_obj({"funcao": _S, "quantidade": {"type": "integer"}}),
                          "pessoas por veículo, ex.: [{'funcao': 'Motorista', 'quantidade': 1}, {'funcao': 'Coletor', 'quantidade': 3}]"),
        "fonte": _FONTE,
    }), "equipe padrão (guarnição) de cada veículo"),
    "turnos": _lista(_obj({
        "servico": {"type": "string", "description": "código do serviço, ex.: 'P1'"},
        "nome": {"type": "string", "enum": ["Diurno", "Noturno"],
                 "description": "1º turno = Diurno, 2º turno = Noturno"},
        "inicio": {"type": "string", "description": "hora de início, 'HH:MM', ex.: '06:00'"},
        "fim": {"type": "string", "description": "hora de término, 'HH:MM', ex.: '14:20'"},
        "jornada": {"type": "string", "description": "jornada de trabalho por turno, sem o intervalo, 'HH:MM', ex.: '07:20'"},
        "equipamento": {"type": "string", "description": "código no plano do equipamento a que este horário se aplica só a ele (ex.: o munk do papa-lixo); vazio = vale para todos"},
        "observacao": _S,
        "fonte": _FONTE,
    }), "horário de cada turno por serviço e jornada (quadros de turnos e horários)"),
    "pendencias":_lista(_S, "dúvidas, contradições ou informações que faltam nos documentos"),
})

LISTAS = ("documentos", "lotes", "servicos", "camadas", "entregaveis", "insumos", "regras",
          "recursos", "equipes", "turnos", "pendencias")


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
    elif t == "integer" and (isinstance(dado, bool) or not isinstance(dado, int)):
        erros.append(f"{caminho}: deve ser número inteiro")
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
    for cam in out.get("camadas") or []:
        for f in cam.get("campos") or []:
            f.setdefault("tamanho", 0)
            f.setdefault("valor_padrao", "")
    for e in out.get("entregaveis") or []:
        e.setdefault("nome_arquivo", "")
        e.setdefault("secoes", [])
        e.setdefault("como_fazer", "")
    return out


def codigo_valor(v):
    """'0 - Fim' -> '0'; 'CC01' -> 'CC01' (código de um valor permitido)."""
    import re
    m = re.match(r"^\s*(.+?)\s+[-–]\s+\S", str(v))
    return (m.group(1) if m else str(v)).strip()


def epsg(p):
    """Código EPSG exigido pelo contrato (ou None)."""
    import re
    s = (p.get("contrato") or {}).get("sistema_referencia", "") or ""
    m = re.search(r"EPSG\D{0,3}(\d{4,6})", s, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"SIRGAS\s*2000.*?UTM.*?(\d{2})\s*([NS])", s, re.IGNORECASE)
    if m:
        z, h = int(m.group(1)), m.group(2).upper()
        return 31960 + z if h == "S" else None  # SIRGAS 2000 / UTM 18S-25S = 31978-31985
    return None


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
            f"{len(p['insumos'])} insumos · {len(p.get('recursos') or [])} recursos · "
            f"{len(p['pendencias'])} pendências")


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
        "municipio": "Brasília",
        "uf": "DF",
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
            # domínios de todos os serviços do grupo (ex.: lote = CC01..CC03 e CS01..CS03)
            doms = {}
            for sv in servs:
                for nome_d, (_, _, valores) in E.dominios(sv, 1).items():
                    doms.setdefault(nome_d, {}).update(valores)
            campos = []
            for f in c["campos"]:
                vals = []
                if f["dominio"] and f["dominio"] in doms:
                    vals = [f"{k} - {v}" if str(k) != str(v) else str(v)
                            for k, v in doms[f["dominio"]].items()]
                campos.append({"nome": f["nome"], "tipo": _TIPO.get(f["tipo"], "texto"),
                               "tamanho": f["tamanho"] or 0, "obrigatorio": True, "descricao": f["apelido"] or "",
                               "valores_permitidos": vals,
                               "valor_padrao": _PADRAO_SLU.get(f["nome"], "")})
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
         "prazo": "", "servicos": com_gdb, "nome_arquivo": "{sigla}{lote}.gdb", "secoes": [],
         "como_fazer": "SIRGAS 2000 / UTM 23S; camadas, campos e domínios do Anexo G.",
         "fonte": {"documento": anexo_g, "paginas": ""}},
        {"nome": "Tabela de atributos", "formato": "Excel (.xlsx)",
         "descricao": "Atributos dos circuitos.", "prazo": "", "servicos": com_gdb,
         "nome_arquivo": "{sigla}{lote}_tabela_atributos.xlsx", "secoes": [], "como_fazer": "",
         "fonte": {"documento": anexo_g, "paginas": ""}},
        {"nome": "Programação trimestral", "formato": "Excel (.xlsx)",
         "descricao": "Programação dos serviços sob demanda por trimestre.", "prazo": "",
         "servicos": sob, "nome_arquivo": "", "secoes": [], "como_fazer": "",
         "fonte": {"documento": anexo_g, "paginas": ""}},
        {"nome": "Texto do plano", "formato": "Word (.docx)",
         "descricao": "Seções: " + "; ".join(s[0] for s in E.SECOES_DOCX) + ".",
         "prazo": "", "servicos": list(E.SERVICOS), "nome_arquivo": "",
         "secoes": [s[0] for s in E.SECOES_DOCX],
         "como_fazer": f"Word, {E.FONTE_DOCX} {E.TAM_CORPO_PT} no corpo e {E.TAM_TITULO_PT} nos "
                       "títulos (item 7.8).",
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
    p["recursos"], p["equipes"] = _recursos_slu(E, edital)
    p["turnos"] = _turnos_slu(edital)
    p["_meta"]["origem"] = "perfil pronto SLU-DF (edital_slu.py)"
    return p


# Ciclo/semana só valem para circuitos quinzenais/mensais; os semanais ficam 0 ("Padrão").
_PADRAO_SLU = {"ciclo": "0", "flag_semana": "0"}

# Anexo R: motoristas e coletores (diurno, noturno) de P1 (+P1A, cujos compactadores c/ munk
# estão na frota do P1) e de P2, por lote (págs. 1-3, 9-10, 17-18).
_PESSOAL_SLU = {
    ("P1", 1): {"Motorista": (49, 22), "Coletor": (130, 61)},
    ("P1", 2): {"Motorista": (53, 24), "Coletor": (136, 67)},
    ("P1", 3): {"Motorista": (51, 21), "Coletor": (139, 58)},
    ("P2", 1): {"Motorista": (9, 4), "Coletor": (18, 8)},
    ("P2", 2): {"Motorista": (14, 6), "Coletor": (28, 12)},
    ("P2", 3): {"Motorista": (11, 3), "Coletor": (22, 6)},
}
# Edital, Quadros 12 (P1) e 16 (P2): equipe padrão por veículo
_EQUIPES_SLU = [
    ("P1", "Equipe Padrão de Coleta (Convencional e Limpeza Urbana)", 0, 3, "37"),
    ("P1", "Equipe Padrão de Coleta (Semienterrado)", 1, 2, "37"),
    ("P1", "Equipe Padrão de Coleta (Rejeito de IRR)", 14, 2, "37"),
    ("P2", "Equipe Padrão de Coleta Seletiva", 2, 2, "41"),
    ("P2", "Equipe Padrão de Coleta de LEV", 3, 2, "41"),
    ("P2", "Equipe Padrão de Coleta Seletiva (6 m³)", 14, 2, "41"),
]


# Edital, Quadros 05 (P1, pág. 34) e 13 (P2, pág. 40); jornada de 7h20 + 1h de intervalo
# (itens 5.2.39 e 5.3.29). O 1º turno das 08h00 às 16h20 é só para o papa-lixo (munk).
_TURNOS_SLU = [
    ("P1", "Diurno", "06:00", "14:20", "", "todos os tipos de coleta", "34"),
    ("P1", "Diurno", "08:00", "16:20", "1", "apenas papa-lixo (semienterrado)", "34"),
    ("P1", "Noturno", "16:00", "00:20", "", "", "34"),
    ("P2", "Diurno", "06:00", "14:20", "", "", "40"),
    ("P2", "Noturno", "16:00", "00:20", "", "", "40"),
]


def _turnos_slu(edital):
    return [{"servico": s, "nome": n, "inicio": i, "fim": f, "jornada": "07:20",
             "equipamento": eq, "observacao": obs, "fonte": {"documento": edital, "paginas": pg}}
            for s, n, i, f, eq, obs, pg in _TURNOS_SLU]


def _recursos_slu(E, edital):
    anexo_r = "20-PREGAO-90005-26-Anexo-R"
    rec = []
    for (srv, lote), frota in E.FROTA_ANEXO_R.items():
        for cod, t in frota.items():
            rec.append({"servico": srv, "lote": str(lote), "categoria": "equipamento",
                        "nome": E.EQUIPAMENTOS[cod], "codigo_no_plano": str(cod),
                        "diurno": int(t.get("Diurno", 0)), "noturno": int(t.get("Noturno", 0)),
                        "domingo": True, "fonte": {"documento": anexo_r, "paginas": ""}})
        for funcao, (d, n) in _PESSOAL_SLU.get((srv, lote), {}).items():
            rec.append({"servico": srv, "lote": str(lote), "categoria": "pessoal",
                        "nome": funcao, "codigo_no_plano": "", "diurno": d, "noturno": n,
                        "domingo": True, "fonte": {"documento": anexo_r, "paginas": ""}})
    eqs = [{"servico": srv, "nome": nome, "equipamento": E.EQUIPAMENTOS[cod],
            "codigo_no_plano": str(cod),
            "funcoes": [{"funcao": "Motorista", "quantidade": 1},
                        {"funcao": "Coletor", "quantidade": col}],
            "fonte": {"documento": edital, "paginas": pg}}
           for srv, nome, cod, col, pg in _EQUIPES_SLU]
    return rec, eqs


def _ins(nome, desc, tipo, chaves, obrigatorio=True, fornecido=False):
    return {"nome": nome, "descricao": desc, "tipo": tipo, "obrigatorio": obrigatorio,
            "palavras_chave": chaves, "fornecido_pelo_contratante": fornecido,
            "fonte": {"documento": "", "paginas": ""}}


PERFIS_PRONTOS = {"SLU-DF — Pregão 90005/2026": perfil_slu_df}
