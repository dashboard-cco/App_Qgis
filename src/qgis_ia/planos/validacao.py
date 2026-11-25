# -*- coding: utf-8 -*-
"""Validação de um plano (gdb/gpkg/shp) contra o perfil do contrato. Genérico: vale para
qualquer edital, desde que o perfil tenha os nomes técnicos (ver estrutura.completar_perfil).

Sem QGIS (só osgeo): pode ser testado sozinho. Os erros saem agrupados por
(camada, campo, regra), com a quantidade e os FIDs das feições.
"""
import os

from . import estrutura
from .checklist import norm
from .perfil import codigo_valor, epsg as epsg_perfil

ERRO, AVISO = "erro", "aviso"

_COMPATIVEIS = {
    "texto": {"texto"}, "inteiro": {"inteiro"}, "decimal": {"decimal", "inteiro"},
    "data": {"data", "data_hora"}, "data_hora": {"data_hora", "data"},
    "booleano": {"inteiro", "booleano", "texto"},
}


def _vazio(v):
    return v is None or (isinstance(v, str) and not v.strip())


def _cod(v):
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


class _Erros:
    def __init__(self, max_fids):
        self.grupos = {}
        self.max_fids = max_fids

    def add(self, camada, campo, regra, mensagem, severidade=ERRO, fid=None):
        k = (camada, campo, regra)
        g = self.grupos.get(k)
        if g is None:
            g = self.grupos[k] = {"camada": camada, "campo": campo, "regra": regra,
                                  "mensagem": mensagem, "severidade": severidade,
                                  "quantidade": 0, "fids": []}
        g["quantidade"] += 1
        if fid is not None and len(g["fids"]) < self.max_fids:
            g["fids"].append(fid)

    def lista(self):
        return sorted(self.grupos.values(),
                      key=lambda g: (g["severidade"] != ERRO, g["camada"], g["campo"] or ""))


@estrutura.com_excecoes
def validar(p, caminho, servicos=None, max_fids=2000, geometrias=True, progresso=None):
    """{"plano", "servicos", "erros": [...], "resumo": {...}}"""
    _, ogr, _ = estrutura._ogr()
    servicos = servicos if servicos is not None else estrutura.servicos_do_arquivo(p, caminho)
    exigidas = estrutura.camadas_exigidas(p, servicos)
    E = _Erros(max_fids)
    ds = estrutura.abrir(caminho)
    if ds is None:
        raise ValueError(f"Não consegui abrir {caminho}")
    est = estrutura.ler(caminho)
    existentes = {norm(c["nome"]): c for c in est["camadas"]}
    cod_epsg = epsg_perfil(p)
    feicoes = 0

    for n, cam in enumerate(exigidas):
        nome = cam["nome"]
        if progresso:
            progresso(f"Validando {nome} ({n + 1}/{len(exigidas)})…")
        info = existentes.get(norm(nome))
        if info is None:
            E.add(nome, None, "camada_faltando", f"Camada '{nome}' não existe no plano.")
            continue
        if cam["geometria"] != info["geometria"]:
            E.add(nome, None, "geometria_tipo",
                  f"Geometria é {info['geometria']}; o contrato pede {cam['geometria']}.")
        if cod_epsg and info["epsg"] and info["epsg"] != cod_epsg:
            E.add(nome, None, "sistema",
                  f"Sistema EPSG:{info['epsg']}; o contrato pede EPSG:{cod_epsg}.")
        if info["feicoes"] == 0:
            E.add(nome, None, "camada_vazia", "Camada sem feições.", AVISO)

        tem = {norm(f["nome"]): f for f in info["campos"]}
        checar = []   # (campo do perfil, nome real no arquivo)
        for f in cam["campos"]:
            real = tem.get(norm(f["nome"]))
            if real is None:
                if f.get("_nome_a_confirmar"):
                    E.add(nome, f["nome"], "campo_faltando",
                          f"Campo '{f.get('descricao') or f['nome']}' pedido no edital não "
                          "encontrado (nome técnico a confirmar).", AVISO)
                else:
                    E.add(nome, f["nome"], "campo_faltando", f"Campo '{f['nome']}' não existe.")
                continue
            if real["tipo"] not in _COMPATIVEIS.get(f["tipo"], {f["tipo"]}):
                E.add(nome, f["nome"], "campo_tipo",
                      f"Campo '{real['nome']}' é {real['tipo']}; o contrato pede {f['tipo']}.")
            if f["tipo"] == "texto" and f.get("tamanho") and real["tamanho"] and \
                    real["tamanho"] < f["tamanho"]:
                E.add(nome, f["nome"], "campo_tamanho",
                      f"Campo '{real['nome']}' tem tamanho {real['tamanho']}; o contrato pede "
                      f"{f['tamanho']}.", AVISO)
            checar.append((f, real["nome"]))

        lyr = ds.GetLayerByName(info["nome"])
        defn = lyr.GetLayerDefn()
        idx = [(f, defn.GetFieldIndex(r)) for f, r in checar]
        permitidos = {}
        for f, _ in checar:
            vals = f.get("valores_permitidos") or []
            if vals:
                permitidos[f["nome"]] = {_cod(codigo_valor(v)) for v in vals}
        lyr.ResetReading()
        for feat in lyr:
            feicoes += 1
            fid = feat.GetFID()
            for f, i in idx:
                if i < 0:
                    continue
                v = feat.GetField(i) if feat.IsFieldSetAndNotNull(i) else None
                if _vazio(v):
                    if f.get("obrigatorio"):
                        E.add(nome, f["nome"], "obrigatorio_vazio",
                              f"Campo obrigatório '{f['nome']}' vazio.", fid=fid)
                    continue
                ok = permitidos.get(f["nome"])
                if ok and _cod(v) not in ok:
                    E.add(nome, f["nome"], "valor_fora_do_dominio",
                          f"Valor fora dos permitidos em '{f['nome']}' (ex.: {v!r}).", fid=fid)
                if f["tipo"] == "texto" and f.get("tamanho") and isinstance(v, str) and \
                        len(v) > f["tamanho"]:
                    E.add(nome, f["nome"], "texto_longo",
                          f"Texto maior que {f['tamanho']} caracteres em '{f['nome']}'.", fid=fid)
            if cam["geometria"] != "tabela" and geometrias:
                g = feat.GetGeometryRef()
                if g is None or g.IsEmpty():
                    E.add(nome, None, "geometria_vazia", "Feição sem geometria.", fid=fid)
                elif not g.IsValid():
                    E.add(nome, None, "geometria_invalida",
                          "Geometria inválida (autointerseção, anel aberto…).", AVISO, fid=fid)

    erros = E.lista()
    resumo = {"camadas_exigidas": len(exigidas), "feicoes_lidas": feicoes,
              "erros": sum(g["quantidade"] for g in erros if g["severidade"] == ERRO),
              "avisos": sum(g["quantidade"] for g in erros if g["severidade"] == AVISO),
              "grupos": len(erros)}
    resumo["aprovado"] = resumo["erros"] == 0
    return {"plano": os.path.normpath(caminho), "servicos": servicos, "erros": erros,
            "resumo": resumo}


def relatorio_xlsx(resultado, caminho_xlsx):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Resumo"
    r = resultado["resumo"]
    linhas = [("Plano", resultado["plano"]), ("Serviços", ", ".join(resultado["servicos"])),
              ("Situação", "APROVADO" if r["aprovado"] else "COM ERROS"),
              ("Erros", r["erros"]), ("Avisos", r["avisos"]),
              ("Camadas exigidas", r["camadas_exigidas"]), ("Feições lidas", r["feicoes_lidas"])]
    for a, b in linhas:
        ws.append([a, b])
        ws.cell(ws.max_row, 1).font = Font(bold=True)
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 80

    we = wb.create_sheet("Erros")
    cab = ["Severidade", "Camada", "Campo", "Regra", "Mensagem", "Quantidade", "FIDs (até 2000)"]
    we.append(cab)
    for c in we[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="44546A")
    for g in resultado["erros"]:
        we.append([g["severidade"], g["camada"], g["campo"] or "", g["regra"], g["mensagem"],
                   g["quantidade"], ", ".join(str(f) for f in g["fids"])[:32000]])
        if g["severidade"] == ERRO:
            we.cell(we.max_row, 1).font = Font(color="C00000", bold=True)
    for col, w in zip("ABCDEFG", (11, 28, 22, 22, 70, 11, 60)):
        we.column_dimensions[col].width = w
    we.freeze_panes = "A2"
    wb.save(caminho_xlsx)
    return caminho_xlsx
