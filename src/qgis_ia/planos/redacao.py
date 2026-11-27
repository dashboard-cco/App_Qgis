# -*- coding: utf-8 -*-
"""O Claude redige as seções de um documento exigido pelo edital (ex.: "Plano de Trabalho
Operacional": setorização, rotas, dimensionamento de frota e equipes, metodologia,
contingência…), a partir:

- das páginas do edital/anexos citadas no perfil (fonte do entregável e dos serviços);
- do perfil (serviços, frota, pessoal, equipes, turnos, regras, pendências);
- dos dados da empresa (planilha_modelo_empresa).

Usa a conta Claude da máquina (`claude -p`, dados pela entrada padrão, sem ferramentas).
O que só a empresa ou o órgão definem sai marcado "[A DEFINIR: …]" — nada inventado.
Sem QGIS.
"""
import json
import os
import re
import subprocess

from . import documentos

MODELO = "sonnet"
TEMPO_LIMITE = 900
MAX_CHARS = 140_000

PEDIDO = """Você vai redigir o texto de um documento que a empresa contratada precisa \
entregar à prefeitura/órgão, exatamente como o edital pede. Os dados vêm pela entrada \
padrão em JSON: o documento exigido (nome, seções, como fazer), os serviços que ele cobre, a \
frota e o pessoal do edital, as equipes, os turnos, as regras, as pendências, os dados da \
empresa e os TRECHOS do edital e dos anexos (com documento e página).

Escreva o texto de CADA seção listada em "documento.secoes", na ordem, em português formal \
de plano de trabalho. Responda SÓ com um JSON: {"secoes": {"<título exato da seção>": \
"<texto>"}}."""

INSTRUCOES = """Regras:
- Use somente o que está nos trechos do edital e nos dados. Não invente números, nomes, \
endereços, horários, frequências ou equipamentos.
- Cite a fonte entre parênteses quando trouxer uma exigência (ex.: "(Anexo II, p. 4)").
- Frota e pessoal: use as quantidades do edital; veículos sem placa são identificados pelos \
códigos dados (ex.: S1.1-L01-D01).
- O que depende de definição da empresa ou do órgão (horário não informado, cronograma da \
contratante, endereço da garagem, nomes de responsáveis…) escreva no ponto certo como \
[A DEFINIR: o que falta e quem define].
- Seções de mapa/rota/setorização: descreva como a setorização e os roteiros serão feitos \
(critérios do edital) e diga que os setores e as rotas estão no arquivo de mapa do plano \
(GeoPackage), a ser completado.
- Texto corrido em parágrafos (separe com linha em branco); listas com "- ". Sem títulos \
dentro das seções. Sem markdown além disso."""


def _paginas(txt):
    """'4-5' → [4, 5]; '30' → [30]; '27-28, 31' → [27, 28, 31]."""
    out = []
    for a, b in re.findall(r"(\d+)\s*(?:[-–a]\s*(\d+))?", str(txt or "")):
        a = int(a)
        b = int(b) if b else a
        if b < a or b - a > 40:
            b = a
        out += list(range(a, b + 1))
    return out


def _doc_por_nome(docs, nome):
    n = re.sub(r"\W+", "", str(nome or "").lower())
    if not n:
        return None
    for d in docs:
        dn = re.sub(r"\W+", "", d["nome"].lower())
        if dn.startswith(n[:25]) or n.startswith(dn[:25]):
            return d
    return None


def trechos(docs, fontes, folga=1, maximo=MAX_CHARS):
    """Texto das páginas citadas (mais 'folga' páginas antes/depois), por documento."""
    pedidos = {}
    for f in fontes:
        d = _doc_por_nome(docs, (f or {}).get("documento"))
        if d is None:
            continue
        for pg in _paginas((f or {}).get("paginas")):
            for x in range(pg - folga, pg + folga + 1):
                if 1 <= x <= len(d["paginas"]):
                    pedidos.setdefault(d["nome"], set()).add(x)
    out, total = [], 0
    for nome, pgs in pedidos.items():
        d = next(x for x in docs if x["nome"] == nome)
        for pg in sorted(pgs):
            t = re.sub(r"[ \t]+", " ", d["paginas"][pg - 1]).strip()
            if not t:
                continue
            if total + len(t) > maximo:
                return out
            out.append({"documento": nome, "pagina": pg, "texto": t})
            total += len(t)
    return out


def dados(p, entregavel, servicos, lote, docs, emp, veiculos=None, nome_empresa=""):
    """JSON (texto) com tudo o que o Claude precisa para redigir o documento."""
    sv = set(servicos)
    serv = [s for s in p.get("servicos") or [] if s["codigo"] in sv]
    fontes = [entregavel.get("fonte")] + [s.get("fonte") for s in serv]
    fontes += [r.get("fonte") for r in p.get("recursos") or [] if r.get("servico") in sv]
    fontes += [e.get("fonte") for e in p.get("equipes") or [] if e.get("servico") in sv]
    lote_s = str(lote)

    def do_lote(x):
        return not x.get("lote") or re.sub(r"\D", "", str(x["lote"])) == re.sub(r"\D", "", lote_s)

    return json.dumps({
        "contrato": p.get("contrato"),
        "lote": lote_s,
        "documento": {k: entregavel.get(k) for k in ("nome", "formato", "descricao", "secoes",
                                                     "como_fazer", "prazo", "fonte")},
        "servicos": [{k: s.get(k) for k in ("codigo", "nome", "unidade_medida", "frequencia",
                                            "sob_demanda", "fonte")} for s in serv],
        "frota_e_pessoal_do_edital": [
            {k: r.get(k) for k in ("servico", "lote", "categoria", "nome", "diurno", "noturno",
                                   "domingo")}
            for r in p.get("recursos") or [] if r.get("servico") in sv and do_lote(r)],
        "veiculos_identificados": veiculos or [],
        "equipes": [e for e in p.get("equipes") or [] if e.get("servico") in sv],
        "turnos": [t for t in p.get("turnos") or [] if t.get("servico") in sv],
        "regras": p.get("regras") or [],
        "insumos": [{k: i.get(k) for k in ("nome", "descricao", "fornecido_pelo_contratante")}
                    for i in p.get("insumos") or []],
        "pendencias": p.get("pendencias") or [],
        "empresa": {"nome": nome_empresa, **{k: emp.get(k) for k in
                                             ("empresa", "contatos", "procedimentos")}},
        "trechos_do_edital": trechos(docs, [f for f in fontes if f]),
    }, ensure_ascii=False)


def argumentos(modelo=MODELO):
    return ["-p", PEDIDO, "--model", modelo, "--tools", "", "--strict-mcp-config",
            "--append-system-prompt", INSTRUCOES, "--output-format", "json"]


def executar_claude(entrada, exe=None, timeout=TEMPO_LIMITE, pasta=None, args=None):
    from .importacao import texto_resposta_claude
    from .leitor_claude import achar_claude, ambiente
    exe = exe or achar_claude()
    if not exe:
        raise RuntimeError("Claude Code não encontrado (veja Configurar IA).")
    cmd = [exe] + (args or argumentos())
    if exe.lower().endswith((".cmd", ".bat")):
        cmd = ["cmd", "/c"] + cmd
    r = subprocess.run(cmd, input=entrada.encode("utf-8"), cwd=pasta or os.path.expanduser("~"),
                       env=ambiente(), capture_output=True, timeout=timeout,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    ok, texto = texto_resposta_claude(r.stdout.decode("utf-8", "replace"))
    if not ok:
        raise RuntimeError(texto or r.stderr.decode("utf-8", "replace")[-600:]
                           or "O Claude parou sem resposta.")
    return texto


def ler_resposta(texto, secoes):
    """JSON do Claude → {título: texto}, só com as seções pedidas (título conferido sem
    acento/maiúscula)."""
    m = re.search(r"\{.*\}", texto, re.S)
    if not m:
        raise ValueError("O Claude não devolveu o texto no formato combinado.")
    d = json.loads(m.group())
    d = d.get("secoes", d)

    def n(s):
        return re.sub(r"\W+", "", documentos._sem_acento(str(s)))

    por = {n(k): v for k, v in d.items()}
    out = {}
    for t in secoes:
        v = d.get(t) or por.get(n(t))
        if isinstance(v, list):
            v = "\n".join(f"- {x}" for x in v)
        if v and str(v).strip():
            out[t] = str(v).strip()
    return out


def redigir(p, entregavel, servicos, lote, docs, emp, secoes, veiculos=None,
            nome_empresa="", executar=None):
    """{título da seção: texto} redigido pelo Claude."""
    executar = executar or executar_claude
    e = dict(entregavel, secoes=list(secoes))
    entrada = dados(p, e, servicos, lote, docs, emp, veiculos, nome_empresa)
    return ler_resposta(executar(entrada), secoes)
