# -*- coding: utf-8 -*-
"""Checklist "o que falta para gerar o plano": compara o perfil do contrato com as camadas
do projeto e com o que o usuário confirmou.

Sem QGIS: recebe as camadas do projeto já descritas como dicionários
    {"id", "nome", "tabela", "geometria" ("ponto"|"linha"|"poligono"|"tabela"),
     "campos": [nomes], "feicoes": int}
e uma função opcional contar(id_camada, [campos]) -> {campo: preenchidos}.
"""
import re
import unicodedata

from .perfil import fonte_txt

OK, PARCIAL, FALTA, CONFIRMAR, INFO = "ok", "parcial", "falta", "confirmar", "info"
ORDEM = {FALTA: 0, PARCIAL: 1, CONFIRMAR: 2, OK: 3, INFO: 4}
GRUPOS = ("Insumos para elaborar o plano", "Camadas do plano", "Entregáveis",
          "Pendências no edital")


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _palavras(s):
    return set(w for w in norm(s).split("_") if w)


def _item(grupo, titulo, status, detalhe="", fonte="", acao="", chave=""):
    return {"grupo": grupo, "titulo": titulo, "status": status, "detalhe": detalhe,
            "fonte": fonte, "acao": acao, "chave": chave or f"{grupo}|{titulo}"}


def filtra_servicos(itens, servicos):
    """Itens com lista "servicos" vazia valem para todos; senão, precisam cruzar a escolha."""
    if not servicos:
        return list(itens)
    sel = set(servicos)
    return [i for i in itens if not i.get("servicos") or sel & set(i["servicos"])]


def acha_camada(nome, camadas_projeto):
    n = norm(nome)
    for c in camadas_projeto:
        if norm(c["nome"]) == n or norm(c.get("tabela", "")) == n:
            return c
    return None


def acha_insumo(insumo, camadas_projeto):
    """Camadas cujo nome contém alguma palavra-chave do insumo (palavra inteira ou trecho
    com 4+ letras)."""
    chaves = [norm(k) for k in insumo.get("palavras_chave", []) if norm(k)]
    achadas = []
    for c in camadas_projeto:
        nomes = " ".join([c["nome"], c.get("tabela", "")])
        pal = _palavras(nomes)
        alvo = norm(nomes)
        for k in chaves:
            if k in pal or (len(k) >= 4 and k in alvo):
                achadas.append(c)
                break
    return achadas


def gerar(p, camadas_projeto, estado=None, contar=None):
    """Lista de itens do checklist, já ordenada (o que falta primeiro em cada grupo)."""
    estado = estado or {}
    servicos = estado.get("servicos") or []
    manuais = estado.get("manuais", {})
    itens = []

    # ---------------------------------------------------------- insumos
    g = GRUPOS[0]
    for ins in p.get("insumos", []):
        chave = f"insumo|{ins['nome']}"
        fonte = fonte_txt(ins)
        dica = "Peça ao contratante." if ins.get("fornecido_pelo_contratante") else ""
        if chave in manuais:
            st = OK if manuais[chave] else FALTA
            det = "Confirmado por você." if manuais[chave] else "Marcado como não disponível."
            itens.append(_item(g, ins["nome"], st, det, fonte, dica if st == FALTA else "", chave))
            continue
        if ins["tipo"] in ("camada_geografica", "tabela"):
            achadas = acha_insumo(ins, camadas_projeto)
            if achadas:
                nomes = ", ".join(c["nome"] for c in achadas[:4])
                itens.append(_item(g, ins["nome"], OK, f"No projeto: {nomes}", fonte, "", chave))
            else:
                st = FALTA if ins.get("obrigatorio") else CONFIRMAR
                acao = "Carregue a camada no projeto ou marque como disponível. " + dica
                itens.append(_item(g, ins["nome"], st,
                                   ins.get("descricao", "") + ("" if ins.get("obrigatorio")
                                                               else " (opcional)"),
                                   fonte, acao.strip(), chave))
        else:
            itens.append(_item(g, ins["nome"], CONFIRMAR, ins.get("descricao", ""), fonte,
                               ("Marque quando tiver esta informação. " + dica).strip(), chave))

    # ---------------------------------------------------------- camadas
    g = GRUPOS[1]
    vistos = set()
    for cam in filtra_servicos(p.get("camadas", []), servicos):
        rot = cam["nome"] + (f" ({', '.join(cam['servicos'])})" if cam.get("servicos") else "")
        chave = f"camada|{cam['nome']}|{','.join(cam.get('servicos', []))}"
        if chave in vistos:
            continue
        vistos.add(chave)
        fonte = fonte_txt(cam)
        c = acha_camada(cam["nome"], camadas_projeto)
        if not c:
            itens.append(_item(g, rot, FALTA,
                               f"{cam['geometria']} com {len(cam['campos'])} campos. "
                               + cam.get("descricao", ""),
                               fonte, "Será criada ao gerar o plano (modelo vazio) ou carregue a sua.",
                               chave))
            continue
        problemas = []
        if cam["geometria"] != c["geometria"]:
            problemas.append(f"geometria é {c['geometria']}, o edital pede {cam['geometria']}")
        tem = {norm(f) for f in c["campos"]}
        faltam = [f["nome"] for f in cam["campos"] if norm(f["nome"]) not in tem]
        if faltam:
            problemas.append("faltam campos: " + ", ".join(faltam[:8])
                             + (f" e mais {len(faltam) - 8}" if len(faltam) > 8 else ""))
        if c.get("feicoes", 0) == 0:
            problemas.append("camada vazia")
        elif contar:
            obrig = [f["nome"] for f in cam["campos"]
                     if f.get("obrigatorio") and norm(f["nome"]) in tem]
            reais = {norm(f): f for f in c["campos"]}
            cheios = contar(c["id"], [reais[norm(f)] for f in obrig])
            vazios = [(f, c["feicoes"] - cheios.get(reais[norm(f)], c["feicoes"])) for f in obrig]
            vazios = [(f, n) for f, n in vazios if n > 0]
            if vazios:
                problemas.append("campos vazios: " + ", ".join(
                    f"{f} ({n} de {c['feicoes']})" for f, n in vazios[:6]))
        if problemas:
            itens.append(_item(g, rot, PARCIAL, f"{c['nome']}: " + "; ".join(problemas), fonte,
                               "Complete a camada antes de gerar.", chave))
        else:
            itens.append(_item(g, rot, OK, f"{c['nome']}: {c.get('feicoes', 0)} feições, campos completos.",
                               fonte, "", chave))

    # ---------------------------------------------------------- entregáveis
    g = GRUPOS[2]
    for e in filtra_servicos(p.get("entregaveis", []), servicos):
        det = e.get("formato", "")
        if e.get("prazo"):
            det += f" · prazo: {e['prazo']}"
        if e.get("descricao"):
            det += f" · {e['descricao']}"
        itens.append(_item(g, e["nome"], INFO, det, fonte_txt(e), "Gerado na etapa Gerar.",
                           f"entregavel|{e['nome']}"))

    # ---------------------------------------------------------- pendências
    g = GRUPOS[3]
    for i, pend in enumerate(p.get("pendencias", [])):
        chave = f"pendencia|{i}"
        if manuais.get(chave):
            itens.append(_item(g, pend, OK, "Resolvida.", "", "", chave))
        else:
            itens.append(_item(g, pend, CONFIRMAR, "", "",
                               "Esclareça com o contratante e marque como resolvida.", chave))

    itens.sort(key=lambda i: (GRUPOS.index(i["grupo"]), ORDEM[i["status"]]))
    return itens


def placar(itens):
    """Contagem por status, sem os itens informativos."""
    c = {OK: 0, PARCIAL: 0, FALTA: 0, CONFIRMAR: 0}
    for i in itens:
        if i["status"] in c:
            c[i["status"]] += 1
    return c


def pronto(itens):
    """Pode gerar o plano? Só quando nenhum insumo obrigatório falta."""
    return not any(i["status"] == FALTA and i["grupo"] == GRUPOS[0] for i in itens)
