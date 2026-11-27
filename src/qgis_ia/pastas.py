# -*- coding: utf-8 -*-
"""Estrutura de pastas que o app cria dentro da pasta de cada projeto/contrato.

    <pasta do contrato>\\
        (seus arquivos: edital, anexos, planos atuais .gdb, planilhas — ficam onde estão)
        App_Qgis\\
            Planos\\         um subpasta por plano entregue (ex.: P1_CC01: .gdb, .xlsx, .docx,
                            conferência, frota)
            Base\\           limite do município (IBGE) e vias (OpenStreetMap)
            Relatorios\\     resumo de cada "Criar Todos"
            Contrato\\       perfil do contrato (contrato.json), estado, escolhas, cache dos
                            textos do edital

Pastas antigas (contrato.json, estado.json, textos\\… soltos na raiz) são movidas para cá na
primeira vez que o app as usa.
"""
import os
import shutil

APP = "App_Qgis"
LEIA_ME = """Pasta criada pelo App_Qgis. Seus arquivos (edital, planos atuais, planilhas) ficam
fora dela, na pasta do projeto.

Planos\\      um subpasta por plano entregue (.gdb/.gpkg, tabela .xlsx, texto .docx,
             conferência com as regras do edital, adequação de frota)
Base\\        limite do município (IBGE) e vias (OpenStreetMap) baixados
Relatorios\\  resumo de cada "Criar Todos" (planos criados e problemas)
Contrato\\    perfil do contrato lido do edital (contrato.json), escolhas e cache do app
"""


def raiz(pasta):
    return os.path.join(pasta, APP)


def _sub(pasta, nome, criar):
    p = os.path.join(pasta, APP, nome)
    if criar:
        os.makedirs(p, exist_ok=True)
        leia = os.path.join(pasta, APP, "LEIA-ME.txt")
        if not os.path.exists(leia):
            try:
                with open(leia, "w", encoding="utf-8") as f:
                    f.write(LEIA_ME)
            except OSError:
                pass
    return p


def planos(pasta, criar=False):
    return _sub(pasta, "Planos", criar)


def base(pasta, criar=False):
    return _sub(pasta, "Base", criar)


def relatorios(pasta, criar=False):
    return _sub(pasta, "Relatorios", criar)


def contrato(pasta, criar=False):
    return _sub(pasta, "Contrato", criar)


def arquivo(pasta, nome, criar=False):
    """Caminho de um arquivo/pasta interno (contrato.json, estado.json, textos…) dentro de
    App_Qgis\\Contrato. Se ele ainda está no lugar antigo (raiz da pasta), é movido."""
    novo = os.path.join(contrato(pasta), nome)
    antigo = os.path.join(pasta, nome)
    if not os.path.exists(novo) and os.path.exists(antigo):
        try:
            os.makedirs(os.path.dirname(novo), exist_ok=True)
            shutil.move(antigo, novo)
        except OSError:
            return antigo          # arquivo preso (aberto): usa onde está
    if criar:
        contrato(pasta, criar=True)
    return novo


def eh_do_app(caminho, pasta):
    """True se o caminho está dentro de App_Qgis (não é arquivo de entrada)."""
    r = os.path.normcase(os.path.abspath(raiz(pasta))) + os.sep
    return os.path.normcase(os.path.abspath(caminho)).startswith(r)
