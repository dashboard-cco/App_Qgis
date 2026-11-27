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
    lt = f"{int(lote):02d}" if str(lote).isdigit() else str(lote)
    return f"{sigla or 'V'}{lt}-{(turno or 'D')[0].upper()}{n:02d}"


def veiculos_do_edital(p, servico, lote, sigla):
    """Frota do edital para o serviço e lote, já com a identificação de cada veículo."""
    out = []
    for r in p.get("recursos") or []:
        if r.get("categoria") != "equipamento" or r.get("servico") != servico:
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
           "procedimentos": {}}
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
        elif "proced" in nome:
            for d in dados:
                t = col(d, "texto", "procedimento", "descricao")
                if t and not str(t).startswith("["):
                    out["procedimentos"][str(col(d, "servico")).strip()] = str(t)
    wb.close()
    return out


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
    for c in ("Razão social", "CNPJ", "Endereço", "Preposto", "Responsável técnico",
              "Telefone", "E-mail"):
        ws.append([c, ""])
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
        elif k == "servico" and serv:
            txt = f"{serv.get('nome', '')}" + (f", {serv['frequencia']}" if serv.get("frequencia")
                                               else "") + "."
        if txt.strip():
            out[t] = txt.strip()
    return out


def nome_empresa(emp):
    e = emp.get("empresa") or {}
    for k, v in e.items():
        if _sa(k).startswith(("razao", "empresa", "nome")) and v:
            return v
    return ""


def _num(s):
    m = re.search(r"\d+", str(s))
    return int(m.group()) if m else None
