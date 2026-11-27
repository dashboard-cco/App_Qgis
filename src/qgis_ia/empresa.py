# -*- coding: utf-8 -*-
"""Dados da empresa para o texto dos planos: planilha "planilha_modelo_empresa" na pasta do
contrato (o usuário salva; se não houver, o app cria um modelo já com a frota e o pessoal do
edital).

Veículos sem placa: cada um recebe uma identificação = sigla do serviço + lote + turno + nº
(ex.: CC01-D01 = Coleta Convencional, lote 1, diurno, veículo 1). A placa entra na
mobilização.

Sem QGIS (openpyxl).
"""
import os
import re
import unicodedata

NOME = "planilha_modelo_empresa"
CAMPOS_EMPRESA = ("Razão social", "CNPJ", "Endereço", "Fundação", "Capital social",
                  "Preposto", "Responsável técnico", "Telefone", "E-mail")


# ====================================================================== dados padrão
def arquivo_padrao():
    """Dados da empresa guardados para todos os projetos (fora das pastas dos contratos)."""
    return os.environ.get("APP_QGIS_EMPRESA") or os.path.join(
        os.path.expanduser("~"), ".app_qgis", "empresa.json")


def empresa_padrao():
    import json
    try:
        with open(arquivo_padrao(), encoding="utf-8") as f:
            return {k: str(v) for k, v in json.load(f).items() if v not in (None, "")}
    except (OSError, ValueError):
        return {}


def salvar_empresa_padrao(dados):
    """Junta 'dados' aos dados guardados (campo vazio não apaga o que já existe)."""
    import json
    atual = empresa_padrao()
    atual.update({k: str(v).strip() for k, v in dados.items() if str(v or "").strip()})
    os.makedirs(os.path.dirname(arquivo_padrao()), exist_ok=True)
    with open(arquivo_padrao(), "w", encoding="utf-8") as f:
        json.dump(atual, f, ensure_ascii=False, indent=2)
    return atual


def completar_empresa_na_planilha(arq):
    """Preenche na aba Empresa os campos vazios com os dados guardados (não troca o que o
    usuário escreveu). Devolve quantos campos preencheu."""
    from openpyxl import load_workbook
    padrao = empresa_padrao()
    if not padrao or not arq or not os.path.exists(arq):
        return 0
    wb = load_workbook(arq)
    ws = next((w for w in wb.worksheets if "empresa" in _sa(w.title)), None)
    if ws is None:
        return 0
    existentes = {_sa(r[0].value): r for r in ws.iter_rows(min_row=2) if r[0].value}
    n = 0
    for campo in CAMPOS_EMPRESA:
        v = padrao.get(campo)
        if not v:
            continue
        r = existentes.get(_sa(campo))
        if r is None:
            ws.append([campo, v])
            n += 1
        elif r[1].value in (None, ""):
            r[1].value = v
            n += 1
    if n:
        wb.save(arq)
    return n
SECOES = {           # chave interna → palavras que identificam a seção do texto exigida
    "servico": ("o que e o servico", "descricao do servico", "objeto", "escopo"),
    "material": ("material", "residuo"),
    "destino": ("destinacao", "destino", "origem"),
    "planejamento": ("planejamento", "rotas", "roteiro", "frequencia", "dimensionamento"),
    "veiculos": ("veiculo", "frota", "placa"),
    "tipos_veiculo": ("tipos de caminh", "tipos de veic", "equipamentos utilizados"),
    "pessoal": ("pessoal", "mao de obra", "efetivo", "quantitativo de func", "equipe",
                "funcionario", "guarnicao"),
    "horarios": ("horario", "turno", "jornada"),
    "procedimentos": ("procedimento", "metodologia", "execucao"),
    "contatos": ("contato", "responsave", "preposto", "equipe e contatos"),
}


def _sa(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower().strip()


def secao_chave(titulo):
    """Que tipo de seção é um título exigido no edital (ou None)."""
    t = _sa(titulo)
    for k in ("contatos", "tipos_veiculo", "veiculos", "pessoal", "horarios", "procedimentos",
              "destino", "material", "planejamento", "servico"):
        if any(p in t for p in SECOES[k]):
            return k
    return None


def arquivo(pasta):
    for a in sorted(os.listdir(pasta)) if os.path.isdir(pasta) else []:
        b, ext = os.path.splitext(a)
        if _sa(b).startswith(NOME) and ext.lower() in (".xlsx", ".xlsm") and not a.startswith("~$"):
            return os.path.join(pasta, a)
    return None


# ====================================================================== identificação
def ident_veiculo(sigla, lote, turno, n):
    """CC01-D01 (sigla + lote, turno, nº). Sem sigla de letras (item do edital, ex.: 1.1):
    S1.1-L01-D01."""
    lt = f"{int(lote):02d}" if str(lote).isdigit() else str(lote)
    t = (turno or "D")[0].upper()
    sigla = sigla or "V"
    if not sigla.isalpha():
        sigla = sigla if sigla.startswith("S") else f"S{sigla}"
        return f"{sigla}-L{lt}-{t}{n:02d}"
    return f"{sigla}{lt}-{t}{n:02d}"


NAO_VEICULO = ("cacamba", "conteiner", "container", "papeleira", "lixeira", "cesto",
               "rocadeira", "soprador", "ferramenta", "carrinho", "lutocar", "bombona",
               "equipamento de protecao", "epi", "balanca", "kit", "placa", "sinalizacao",
               "banheiro", "capinadeira")


def eh_veiculo(nome):
    """Veículo com placa (caminhão, varredeira, carro…) — não caçamba, contêiner, carrinho."""
    n = _sa(nome)
    return not any(k in n for k in NAO_VEICULO) or n.startswith("caminhao")


def veiculos_do_edital(p, servico, lote, sigla):
    """Frota do edital para o serviço e lote, já com a identificação de cada veículo
    (só veículos: caçambas, contêineres e carrinhos ficam de fora)."""
    out = []
    for r in p.get("recursos") or []:
        if r.get("categoria") != "equipamento" or r.get("servico") != servico:
            continue
        if not eh_veiculo(r.get("nome")):
            continue
        if r.get("lote") and str(r["lote"]) != str(lote):
            continue
        for turno in ("Diurno", "Noturno"):
            for _ in range(int(r.get(turno.lower()) or 0)):
                out.append({"tipo": r["nome"], "turno": turno})
    cont = {}
    for v in out:
        cont[v["turno"]] = cont.get(v["turno"], 0) + 1
        v["identificacao"] = ident_veiculo(sigla, lote, v["turno"], cont[v["turno"]])
        v["placa"] = ""
    return out


def pessoal_do_edital(p, servico, lote):
    out = []
    for r in p.get("recursos") or []:
        if r.get("categoria") != "pessoal" or r.get("servico") != servico:
            continue
        if r.get("lote") and str(r["lote"]) != str(lote):
            continue
        for turno in ("Diurno", "Noturno"):
            n = int(r.get(turno.lower()) or 0)
            if n:
                out.append({"funcao": r["nome"], "turno": turno, "quantidade": n})
    if not out:                       # sem quadro de pessoal: veículos × equipe padrão
        for v in veiculos_do_edital(p, servico, lote, ""):
            for eq in p.get("equipes") or []:
                if eq.get("servico") == servico and _sa(eq.get("equipamento"))[:12] in _sa(v["tipo"]):
                    for f in eq.get("funcoes") or []:
                        out.append({"funcao": f["funcao"], "turno": v["turno"],
                                    "quantidade": int(f.get("quantidade") or 0)})
        soma = {}
        for x in out:
            k = (x["funcao"], x["turno"])
            soma[k] = soma.get(k, 0) + x["quantidade"]
        out = [{"funcao": f, "turno": t, "quantidade": n} for (f, t), n in soma.items()]
    return out


# ====================================================================== planilha
def ler(pasta):
    """Dados da planilha da empresa: {"arquivo", "empresa": {campo: valor}, "veiculos": [...],
    "pessoal": [...], "contatos": [...], "procedimentos": {servico|"": texto}}."""
    arq = arquivo(pasta)
    out = {"arquivo": arq, "empresa": {}, "veiculos": [], "pessoal": [], "contatos": [],
           "procedimentos": {}, "locais": []}
    if not arq:
        return out
    from openpyxl import load_workbook
    wb = load_workbook(arq, read_only=True, data_only=True)
    for ws in wb.worksheets:
        nome = _sa(ws.title)
        linhas = [[c for c in r] for r in ws.iter_rows(values_only=True)]
        linhas = [r for r in linhas if any(v not in (None, "") for v in r)]
        if not linhas:
            continue
        cab = [_sa(c) for c in linhas[0]]
        dados = [dict(zip(cab, r)) for r in linhas[1:]]

        def col(d, *chaves):
            for k, v in d.items():
                if k and any(c in k for c in chaves) and v not in (None, ""):
                    return v
            return ""

        if nome.startswith("_") or "contrato" in nome:
            continue                     # aba de controle do app / dados do edital
        if "empresa" in nome or "dados" in nome:
            for r in linhas[1:] if cab and cab[0] in ("campo", "item", "dado") else linhas:
                if len(r) >= 2 and r[0]:
                    out["empresa"][str(r[0]).strip()] = "" if r[1] is None else str(r[1]).strip()
        elif "veic" in nome or "frota" in nome:
            for d in dados:
                ident = col(d, "identifica", "codigo", "prefixo")
                tipo = col(d, "tipo", "veiculo", "equipamento", "descricao")
                if ident or tipo:
                    out["veiculos"].append({
                        "identificacao": str(ident), "tipo": str(tipo),
                        "servico": str(col(d, "servico")), "lote": str(col(d, "lote")),
                        "turno": str(col(d, "turno")).capitalize(), "placa": str(col(d, "placa"))})
        elif "pessoal" in nome or "equipe" in nome or "funcion" in nome:
            for d in dados:
                f = col(d, "funcao", "cargo")
                if f:
                    q = col(d, "quantidade", "qtd", "qtde")
                    out["pessoal"].append({"funcao": str(f), "servico": str(col(d, "servico")),
                                           "lote": str(col(d, "lote")),
                                           "turno": str(col(d, "turno")).capitalize(),
                                           "quantidade": int(q) if str(q).strip().isdigit() else q})
        elif "contato" in nome or "respons" in nome:
            for d in dados:
                n = col(d, "nome")
                if n:
                    out["contatos"].append({"nome": str(n), "funcao": str(col(d, "funcao", "cargo")),
                                            "telefone": str(col(d, "telefone", "fone", "celular")),
                                            "email": str(col(d, "mail"))})
        elif "loca" in nome:
            for d in dados:
                n = col(d, "nome", "local")
                if n or col(d, "tipo"):
                    out["locais"].append({"tipo": str(col(d, "tipo")), "nome": str(n),
                                          "endereco": str(col(d, "endereco")),
                                          "servicos": str(col(d, "servico"))})
        elif "proced" in nome:
            for d in dados:
                t = col(d, "texto", "procedimento", "descricao")
                if t and not str(t).startswith("["):
                    out["procedimentos"][str(col(d, "servico")).strip()] = str(t)
    wb.close()
    # campos vazios da aba Empresa: valem os dados guardados da empresa
    for k, v in empresa_padrao().items():
        if not out["empresa"].get(k):
            out["empresa"][k] = v
    return out


FIXOS_EMPRESA = ("Razão social", "CNPJ", "Endereço", "Fundação", "Capital social",
                 "Responsável técnico", "Telefone", "E-mail")


def aprender_empresa(emp):
    """Guarda os dados fixos da empresa que o usuário preencheu numa planilha (o preposto
    muda de contrato para contrato e não é guardado)."""
    novos = {k: v for k, v in (emp.get("empresa") or {}).items()
             if k in FIXOS_EMPRESA and str(v or "").strip()}
    if novos and any(empresa_padrao().get(k) != v for k, v in novos.items()):
        salvar_empresa_padrao(novos)
    return novos


def criar_modelo(pasta, p, planos):
    """Cria planilha_modelo_empresa.xlsx (só se não existir) com a frota e o pessoal do edital
    dos planos [(servico, lote, sigla)], para a empresa completar."""
    arq = os.path.join(pasta, NOME + ".xlsx")
    if arquivo(pasta):
        return arquivo(pasta)
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    cab_fill = PatternFill("solid", fgColor="1F4E78")

    def aba(titulo, colunas, larguras, primeira=False):
        ws = wb.active if primeira else wb.create_sheet()
        ws.title = titulo
        ws.append(colunas)
        for c, w in zip(ws[1], larguras):
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = cab_fill
            ws.column_dimensions[c.column_letter].width = w
        return ws

    ws = aba("Empresa", ["Campo", "Valor"], [30, 60], primeira=True)
    padrao = empresa_padrao()
    for c in CAMPOS_EMPRESA:
        ws.append([c, padrao.get(c, "")])
    ws = aba("Veículos", ["Identificação", "Serviço", "Lote", "Turno", "Tipo (edital)",
                          "Placa (opcional)"], [16, 10, 8, 10, 60, 16])
    ws2 = aba("Pessoal", ["Serviço", "Lote", "Turno", "Função", "Quantidade"],
              [10, 8, 10, 40, 12])
    ws3 = aba("Contatos", ["Nome", "Função", "Telefone", "E-mail"], [35, 35, 18, 35])
    for f in ("Preposto", "Responsável pela operação", "Responsável pelo planejamento"):
        ws3.append(["", f, "", ""])
    ws4 = aba("Procedimentos", ["Serviço", "Texto"], [10, 110])
    vistos = set()
    for servico, lote, sigla in planos:
        for v in veiculos_do_edital(p, servico, lote, sigla):
            ws.append([v["identificacao"], servico, lote, v["turno"], v["tipo"], ""])
        for x in pessoal_do_edital(p, servico, lote):
            ws2.append([servico, lote, x["turno"], x["funcao"], x["quantidade"]])
        if servico not in vistos:
            vistos.add(servico)
            ws4.append([servico, "[Escreva como o serviço é executado: saída da garagem, "
                                 "execução, pesagem, descarga e retorno.]"])
    for row in ws4.iter_rows(min_row=2):
        row[1].alignment = Alignment(wrap_text=True)
    os.makedirs(pasta, exist_ok=True)
    wb.save(arq)
    return arq


# ====================================================================== textos
def textos(p, servico, lote, sigla, turnos, emp, titulos):
    """Texto de cada seção exigida (títulos do edital) que dá para escrever com o edital e
    a planilha da empresa. Devolve {título: texto}."""
    serv = next((s for s in p.get("servicos") or [] if s.get("codigo") == servico), {})
    out = {}
    for t in titulos:
        k = secao_chave(t)
        txt = ""
        if k == "veiculos":
            vs = [v for v in emp.get("veiculos") or []
                  if (not v.get("servico") or v["servico"] == servico)
                  and (not v.get("lote") or str(v["lote"]) == str(lote))]
            if not vs:
                vs = veiculos_do_edital(p, servico, lote, sigla)
            if vs:
                linhas = []
                por_tipo = {}
                for v in vs:
                    por_tipo.setdefault((v["tipo"], v.get("turno") or ""), []).append(v)
                for (tipo, turno), lst in por_tipo.items():
                    ids = [v["identificacao"] for v in lst if v.get("identificacao")]
                    faixa = (f"{ids[0]} a {ids[-1]}" if len(ids) > 2 else ", ".join(ids))
                    placas = [f"{v['identificacao']} ({v['placa']})" for v in lst if v.get("placa")]
                    linhas.append(f"{tipo} — {len(lst)} {turno.lower()}: {faixa}."
                                  + (f" Placas: {', '.join(placas)}." if placas else ""))
                txt = "\n".join(linhas)
                if not any(v.get("placa") for v in vs):
                    txt += ("\nOs veículos estão identificados pelo código acima (serviço + lote + "
                            "turno + número); as placas serão informadas na mobilização.")
        elif k == "tipos_veiculo":
            tipos = sorted({v["tipo"] for v in veiculos_do_edital(p, servico, lote, sigla)})
            txt = "\n".join(tipos)
        elif k == "pessoal":
            ps = [x for x in emp.get("pessoal") or []
                  if (not x.get("servico") or x["servico"] == servico)
                  and (not x.get("lote") or str(x["lote"]) == str(lote))] \
                or pessoal_do_edital(p, servico, lote)
            txt = "\n".join(f"{x['funcao']}: {x['quantidade']}"
                            + (f" ({x['turno'].lower()})" if x.get("turno") else "") for x in ps)
        elif k == "horarios":
            tur = [x for x in p.get("turnos") or [] if x.get("servico") == servico
                   and x.get("nome") in turnos and not x.get("equipamento")]
            txt = "\n".join(f"Turno {x['nome'].lower()}: {x['inicio']} às {x['fim']} "
                            f"(jornada {x['jornada']})." for x in tur)
        elif k == "contatos":
            cs = emp.get("contatos") or []
            linhas = [f"{c['funcao']}: {c['nome']}" + (f" — {c['telefone']}" if c["telefone"] else "")
                      + (f" — {c['email']}" if c["email"] else "") for c in cs if c.get("nome")]
            e = emp.get("empresa") or {}
            for campo in ("Preposto", "Responsável técnico"):
                if e.get(campo) and not any(campo.lower() in l.lower() for l in linhas):
                    linhas.append(f"{campo}: {e[campo]}")
            txt = "\n".join(linhas)
        elif k == "procedimentos":
            pr = emp.get("procedimentos") or {}
            txt = pr.get(servico) or pr.get("") or ""
        elif k == "destino":
            ls = [x for x in emp.get("locais") or []
                  if not x.get("servicos") or servico in re.split(r"[,;\s]+", x["servicos"])]
            txt = "\n".join(f"{x['tipo']}: {x['nome']}" + (f" — {x['endereco']}" if x["endereco"]
                                                           else "") for x in ls if x.get("nome"))
        elif k == "servico" and serv:
            txt = f"{serv.get('nome', '')}" + (f", {serv['frequencia']}" if serv.get("frequencia")
                                               else "") + "."
        if txt.strip():
            out[t] = txt.strip()
    return out


# ====================================================================== preencher com o edital
PEDIDO_PLANILHA = """Monte, a partir do edital, os dados que a empresa contratada vai usar \
nos planos. Os dados vêm pela entrada padrão em JSON: os serviços (com código e fonte), \
insumos, regras, equipes e os TRECHOS do edital/anexos (documento e página).

Responda SÓ com um JSON:
{"procedimentos": {"<código do serviço>": "<como o serviço é executado, conforme o edital: \
saída da garagem, execução, cuidados exigidos, pesagem/descarga, destinação e retorno; 3 a 8 \
frases; cite a fonte entre parênteses, ex.: (Anexo II, p. 4)>"},
 "locais": [{"tipo": "garagem|transbordo|aterro|triagem|ecoponto|cemitério|unidade de saúde|\
compostagem|outro", "nome": "...", "endereco": "... ou vazio", "servicos": "códigos separados \
por vírgula", "fonte": "documento, p. N"}],
 "responsaveis": [{"funcao": "ex.: Engenheiro preposto", "exigencia": "o que o edital exige \
dessa função", "fonte": "documento, p. N"}]}

Regras: use só o que está nos trechos; não invente endereços nem nomes. Locais que o edital \
manda a empresa indicar (garagem, transbordo próprio…) entram com endereco "[A DEFINIR pela \
empresa]". Um procedimento para cada serviço da lista."""


def _argumentos_planilha():
    try:
        from .planos import redacao as R
    except ImportError:
        from planos import redacao as R
    return ["-p", PEDIDO_PLANILHA, "--model", R.MODELO, "--tools", "", "--strict-mcp-config",
            "--output-format", "json"]


def dados_edital(p, docs):
    """JSON (texto) com serviços, insumos, regras, equipes e os trechos do edital citados."""
    try:
        from .planos import redacao as R
    except ImportError:
        from planos import redacao as R
    import json
    serv = p.get("servicos") or []
    fontes = [s.get("fonte") for s in serv] + [i.get("fonte") for i in p.get("insumos") or []]
    fontes += [e.get("fonte") for e in p.get("equipes") or []]
    return json.dumps({
        "contrato": p.get("contrato"),
        "servicos": [{k: s.get(k) for k in ("codigo", "nome", "frequencia", "lotes", "fonte")}
                     for s in serv],
        "insumos": [{k: i.get(k) for k in ("nome", "descricao", "fornecido_pelo_contratante",
                                           "fonte")} for i in p.get("insumos") or []],
        "regras": p.get("regras") or [],
        "equipes": p.get("equipes") or [],
        "trechos_do_edital": R.trechos(docs, [f for f in fontes if f], folga=0),
    }, ensure_ascii=False)


def _assinatura(wb):
    """Resumo do conteúdo das abas (menos a de controle) — muda se o usuário mexer."""
    import hashlib
    h = hashlib.sha1()
    for ws in wb.worksheets:
        if ws.title.startswith("_"):
            continue
        h.update(ws.title.encode("utf-8"))
        for r in ws.iter_rows(values_only=True):
            cel = [("" if v is None else str(v).strip()) for v in r]
            while cel and not cel[-1]:
                cel.pop()
            if cel:
                h.update(("\x1f".join(cel) + "\x1e").encode("utf-8"))
    return h.hexdigest()


def _gerada_pelo_app_intacta(arq):
    """True se a planilha foi criada pelo app e ninguém a salvou depois (pode regravar)."""
    from openpyxl import load_workbook
    try:
        wb = load_workbook(arq, read_only=True)
    except Exception:
        return False
    try:
        if "_app" in wb.sheetnames:
            v = {r[0]: r[1] for r in wb["_app"].iter_rows(values_only=True) if r and len(r) > 1}
            return bool(v.get("assinatura")) and v["assinatura"] == _assinatura(wb)
        # modelo antigo do app: nada preenchido pelo usuário
        emp = ler(os.path.dirname(arq))
        return not (any(emp["empresa"].values()) or emp["contatos"] or emp["procedimentos"]
                    or any(v.get("placa") for v in emp["veiculos"]))
    finally:
        wb.close()


def preencher_do_edital(pasta, p, docs, usar_claude=True, executar=None, progresso=None):
    """Planilha da empresa montada com o que já está no edital: veículos (com código, só
    veículos), pessoal, funções responsáveis, procedimentos por serviço e locais (o Claude lê
    os trechos citados). Se a planilha atual já foi mexida pelo usuário, grava
    planilha_modelo_empresa_sugerida.xlsx ao lado. Devolve {"arquivo", "substituiu",
    "procedimentos", "locais", "veiculos", "pessoal", "claude"}."""
    import json
    import shutil
    import time
    info = {"claude": None, "erro_claude": ""}
    extra = {"procedimentos": {}, "locais": [], "responsaveis": []}
    if usar_claude:
        if progresso:
            progresso("Claude lendo os procedimentos, locais e responsáveis no edital…")
        try:
            if executar is None:
                try:
                    from .planos import redacao as R
                except ImportError:
                    from planos import redacao as R
                texto = R.executar_claude(dados_edital(p, docs), args=_argumentos_planilha())
            else:
                texto = executar(dados_edital(p, docs))
            m = re.search(r"\{.*\}", texto, re.S)
            extra.update(json.loads(m.group()) if m else {})
            info["claude"] = True
        except Exception as e:
            info["claude"] = False
            info["erro_claude"] = str(e)

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    cab_fill = PatternFill("solid", fgColor="1F4E78")

    def aba(titulo, colunas, larguras, primeira=False):
        ws = wb.active if primeira else wb.create_sheet()
        ws.title = titulo
        ws.append(colunas)
        for c, w in zip(ws[1], larguras):
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = cab_fill
            ws.column_dimensions[c.column_letter].width = w
        return ws

    ws = aba("Empresa", ["Campo", "Valor", "Observação"], [28, 50, 60], primeira=True)
    padrao = empresa_padrao()
    for c in CAMPOS_EMPRESA:
        ws.append([c, padrao.get(c, ""), "Dados guardados da empresa" if padrao.get(c)
                   else "Dado da empresa (não está no edital)"])
    serv = p.get("servicos") or []
    lotes_perfil = [re.sub(r"\D", "", l["codigo"]) or l["codigo"] for l in p.get("lotes") or []]
    wv = aba("Veículos", ["Identificação", "Serviço", "Lote", "Turno", "Tipo (edital)",
                          "Placa (opcional)", "Fonte"], [18, 9, 6, 9, 55, 16, 34])
    wp = aba("Pessoal", ["Serviço", "Lote", "Turno", "Função", "Quantidade", "Fonte"],
             [9, 6, 9, 40, 11, 34])
    nv = npes = 0
    for s in serv:
        sig = (s.get("sigla") or "").strip() or f"S{s['codigo']}"
        for lote in [re.sub(r"\D", "", x) or x for x in s.get("lotes") or []] or lotes_perfil or ["1"]:
            fonte = next((r.get("fonte") for r in p.get("recursos") or []
                          if r.get("servico") == s["codigo"]), None) or {}
            ftxt = fonte.get("documento", "") + (f", p. {fonte['paginas']}"
                                                 if fonte.get("paginas") else "")
            for v in veiculos_do_edital(p, s["codigo"], lote, sig):
                wv.append([v["identificacao"], s["codigo"], lote, v["turno"], v["tipo"], "", ftxt])
                nv += 1
            for x in pessoal_do_edital(p, s["codigo"], lote):
                wp.append([s["codigo"], lote, x["turno"], x["funcao"], x["quantidade"], ftxt])
                npes += 1
    wc = aba("Contatos", ["Nome", "Função", "Telefone", "E-mail", "O que o edital exige",
                          "Fonte"], [30, 32, 16, 30, 60, 30])
    resp = extra.get("responsaveis") or [{"funcao": f, "exigencia": "", "fonte": ""} for f in
                                         ("Preposto", "Responsável técnico",
                                          "Responsável pela operação")]
    for r in resp:
        wc.append(["", r.get("funcao", ""), "", "", r.get("exigencia", ""), r.get("fonte", "")])
    wr = aba("Procedimentos", ["Serviço", "Nome do serviço", "Texto"], [9, 40, 110])
    for s in serv:
        t = (extra.get("procedimentos") or {}).get(s["codigo"]) or \
            "[Escreva como o serviço é executado: saída da garagem, execução, pesagem, descarga e retorno.]"
        wr.append([s["codigo"], s["nome"], t])
    wl = aba("Locais", ["Tipo", "Nome", "Endereço", "Serviços", "Fonte"], [16, 40, 50, 16, 30])
    locais = extra.get("locais") or []
    if not any(_sa(x.get("tipo")).startswith("garagem") for x in locais):
        locais = [{"tipo": "garagem", "nome": "Garagem da empresa",
                   "endereco": "[A DEFINIR pela empresa]", "servicos": "", "fonte": ""}] + locais
    for x in locais:
        wl.append([x.get("tipo", ""), x.get("nome", ""), x.get("endereco", ""),
                   x.get("servicos", ""), x.get("fonte", "")])
    wk = aba("Contrato (edital)", ["Campo", "Valor"], [26, 110])
    for k, v in (p.get("contrato") or {}).items():
        if v:
            wk.append([k.replace("_", " ").capitalize(), str(v)])
    for w in (wr, wc, wl, wk):
        for row in w.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical="top")
    agora = time.time()
    assinatura = _assinatura(wb)
    ctrl = wb.create_sheet("_app")
    ctrl.append(["gerada_em", agora])
    ctrl.append(["assinatura", assinatura])
    ctrl.sheet_state = "hidden"

    atual = arquivo(pasta)
    substituiu = False
    if atual and not _gerada_pelo_app_intacta(atual):
        destino = os.path.join(pasta, NOME + "_sugerida.xlsx")
    else:
        destino = atual or os.path.join(pasta, NOME + ".xlsx")
        if atual:
            try:
                from . import pastas as PA
            except ImportError:
                import pastas as PA
            shutil.copy2(atual, PA.arquivo(pasta, "planilha_modelo_empresa_anterior.xlsx",
                                           criar=True))
            substituiu = True
    wb.save(destino)
    info.update(arquivo=destino, substituiu=substituiu, veiculos=nv, pessoal=npes,
                procedimentos=sum(1 for s in serv if (extra.get("procedimentos") or {}).get(s["codigo"])),
                locais=len(locais), responsaveis=len(resp))
    return info


def nome_empresa(emp):
    e = emp.get("empresa") or {}
    for k, v in e.items():
        if _sa(k).startswith(("razao", "empresa", "nome")) and v:
            return v
    return ""


def _num(s):
    m = re.search(r"\d+", str(s))
    return int(m.group()) if m else None
