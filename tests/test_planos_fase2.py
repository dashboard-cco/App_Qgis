# -*- coding: utf-8 -*-
"""
Fase 2 do Planos do Contrato: modelo do contratante, plano existente (criar o que falta)
e validação genérica. Usa uma cópia de Gdb/CC01.gdb (não altera o original).

    "C:\\Program Files\\QGIS 3.44.15\\bin\\python-qgis-ltr.bat" tests\\test_planos_fase2.py
"""
import os
import shutil
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.join(AQUI, "..", "src", "qgis_ia")
GDB = os.path.join(AQUI, "..", "Gdb")
sys.path.insert(0, PLUGIN)

from planos import estrutura as S, perfil, validacao as V  # noqa: E402
from planos.checklist import norm  # noqa: E402

FALHAS = []


def check(cond, msg):
    if not cond:
        FALHAS.append(msg)
        print("FALHOU:", msg)


# ------------------------------------------------------------ utilidades
check(perfil.codigo_valor("0 - Fim") == "0" and perfil.codigo_valor("CC01") == "CC01"
      and perfil.codigo_valor("Sol Nascente - Pôr do Sol") == "Sol Nascente", "codigo_valor")
check(perfil.epsg({"contrato": {"sistema_referencia": "SIRGAS 2000 / UTM 23S (EPSG:31983)"}}) == 31983, "epsg")
check(perfil.epsg({"contrato": {"sistema_referencia": "SIRGAS 2000 / UTM zona 23 S"}}) == 31983, "epsg utm")
check(perfil.epsg({"contrato": {"sistema_referencia": ""}}) is None, "epsg vazio")
check(S._parecido("codigo_ra", "codigo_regiao_administrativa"), "sigla RA")
check(S._parecido("horario_inicio", "horario_de_inicio"), "preposição")
check(S._parecido("local_destinacao", "local_de_tratamento_ou_destinacao"), "local destinação")
check(not S._parecido("codigo_circuito", "codigo_ra"), "não confunde códigos")
check(not S._parecido("segunda", "sexta"), "dias diferentes")

cc01 = os.path.join(GDB, "CC01.gdb")
if not os.path.isdir(cc01):
    print("aviso: Gdb/CC01.gdb não encontrado; testes de arquivo pulados")
    print("OK" if not FALHAS else f"{len(FALHAS)} FALHA(S)")
    sys.exit(1 if FALHAS else 0)

tmp = tempfile.mkdtemp(prefix="fase2_")
try:
    plano = os.path.join(tmp, "CC01.gdb")
    shutil.copytree(cc01, plano)

    # ------------------------------------------------------------ leitura
    est = S.ler(plano)
    nomes = {c["nome"] for c in est["camadas"]}
    check(nomes == {"st_circuito_inicio_fim", "st_circuito_planejado",
                    "lm_area_circuito_planejado", "st_conteiner"}, f"camadas sem as de sistema: {nomes}")
    area = next(c for c in est["camadas"] if c["nome"] == "lm_area_circuito_planejado")
    check(area["geometria"] == "poligono" and area["epsg"] == 31983, "geometria/epsg")
    cr = next(f for f in area["campos"] if f["nome"] == "codigo_circuito")
    check(cr["alias"] == "Código Circuito" and cr["tipo"] == "inteiro", f"campo {cr}")
    check("shape_length" not in {norm(f["nome"]) for f in area["campos"]}, "sem Shape_Length")
    check("1" in est["dominios"]["cod_ra"], "domínio cod_ra lido")

    # ------------------------------------------------------------ perfil do edital + modelo
    # perfil como a IA monta: nomes de exibição, sem nomes técnicos
    ed = perfil.vazio()
    ed["contrato"]["sistema_referencia"] = "SIRGAS 2000 / UTM 23S"
    ed["servicos"] = [{"codigo": "P1", "sigla": "CC", "nome": "Coleta Convencional",
                       "unidade_medida": "", "lotes": ["1"], "frequencia": "", "sob_demanda": False,
                       "fonte": {"documento": "", "paginas": ""}}]

    def campo(nome, tipo="inteiro", vals=()):
        return {"nome": nome, "tipo": tipo, "tamanho": 0, "obrigatorio": True, "descricao": "",
                "valores_permitidos": list(vals)}

    ed["camadas"] = [
        {"nome": "POLÍGONO (GDB CC0X)", "descricao": "Área do circuito", "geometria": "poligono",
         "servicos": ["P1"], "fonte": {"documento": "Anexo G", "paginas": "10"},
         "campos": [campo("Lote", "texto"), campo("Código Circuito"),
                    campo("Código Região Administrativa"), campo("Horário de Início", "data_hora"),
                    campo("Ciclo", vals=["0 - Padrão", "1 - Quinzenal"])]},
        {"nome": "PONTO - CONTÊINER (GDB CC0X)", "descricao": "", "geometria": "ponto",
         "servicos": ["P1"], "fonte": {"documento": "Anexo G", "paginas": "11"},
         "campos": [campo("Lote", "texto"), campo("Código Circuito")]},
    ]
    check(S.servicos_do_arquivo(ed, plano) == ["P1"], "serviço pela sigla do arquivo")
    novo, rel = S.completar_perfil(ed, est, ["P1"])
    lig = {l["edital"]: l["modelo"] for l in rel["ligadas"]}
    check(lig.get("POLÍGONO (GDB CC0X)") == "lm_area_circuito_planejado", f"ligou polígono: {lig}")
    check(lig.get("PONTO - CONTÊINER (GDB CC0X)") == "st_conteiner", f"ligou contêiner: {lig}")
    check(set(rel["novas"]) == {"st_circuito_inicio_fim", "st_circuito_planejado"},
          f"novas: {rel['novas']}")
    check(rel["campos_so_no_perfil"].get("lm_area_circuito_planejado") == ["Ciclo"], f"{rel}")
    ca = next(c for c in novo["camadas"] if c["nome"] == "lm_area_circuito_planejado")
    nomes_ca = [f["nome"] for f in ca["campos"]]
    check("codigo_ra" in nomes_ca and "horario_inicio" in nomes_ca, f"nomes técnicos {nomes_ca}")
    cra = next(f for f in ca["campos"] if f["nome"] == "codigo_ra")
    check(cra["obrigatorio"] and "1 - Plano Piloto" in cra["valores_permitidos"], "domínio no perfil")
    check(cra["descricao"] == "Código Região Administrativa", "descrição do edital mantida")
    extra = next(f for f in ca["campos"] if f["nome"] == "ciclo")
    check(extra.get("_nome_a_confirmar"), "campo só do edital fica, a confirmar")
    so_modelo = next(f for f in ca["campos"] if f["nome"] == "enderecamento")
    check(so_modelo["obrigatorio"] is False, "campo só do modelo não é obrigatório")
    check(ca["fonte"]["paginas"] == "10" and ca["_nome_no_edital"] == "POLÍGONO (GDB CC0X)", "fonte")
    check(perfil.valida({k: v for k, v in novo.items() if k != "_meta"}) == [], "perfil continua válido")

    # ------------------------------------------------------------ validação (gabarito SLU)
    p = perfil.perfil_slu_df()
    r = V.validar(p, plano)
    check(r["servicos"] == ["P1"], "serviços do CC01")
    faltando = {(g["camada"], g["campo"]) for g in r["erros"] if g["regra"] == "campo_faltando"}
    check(faltando == {("lm_area_circuito_planejado", "ciclo"),
                       ("lm_area_circuito_planejado", "flag_semana")}, f"faltando {faltando}")
    check(r["resumo"]["feicoes_lidas"] > 40000 and not r["resumo"]["aprovado"], f"{r['resumo']}")

    # ------------------------------------------------------------ criar o que falta
    falta = S.o_que_falta(p, plano)
    check(falta["campos"] == {"lm_area_circuito_planejado": ["ciclo", "flag_semana"]}, f"{falta}")
    rel = S.completar_plano(p, plano)
    check(rel["backup"] and os.path.isdir(rel["backup"]), "backup feito")
    check(rel["campos_criados"] == {"lm_area_circuito_planejado": ["ciclo", "flag_semana"]}, f"{rel}")
    est2 = S.ler(plano)
    a2 = next(c for c in est2["camadas"] if c["nome"] == "lm_area_circuito_planejado")
    ciclo = next(f for f in a2["campos"] if f["nome"] == "ciclo")
    check(ciclo["tipo"] == "inteiro" and ciclo["dominio"], f"ciclo com domínio {ciclo}")
    check(a2["feicoes"] == area["feicoes"], "feições preservadas")
    check(S.o_que_falta(p, plano)["campos"] == {}, "nada mais falta")
    check(S.completar_plano(p, plano)["backup"] is None, "sem backup quando nada a fazer")
    r2 = V.validar(p, plano)
    vazios = {g["campo"]: g["quantidade"] for g in r2["erros"] if g["regra"] == "obrigatorio_vazio"}
    check(vazios == {"ciclo": area["feicoes"], "flag_semana": area["feicoes"]}, f"vazios {vazios}")

    # camada inteira faltando: remove st_conteiner da cópia e recria
    from osgeo import ogr
    ds = ogr.Open(plano, 1)
    for i in range(ds.GetLayerCount()):
        if ds.GetLayerByIndex(i).GetName() == "st_conteiner":
            ds.DeleteLayer(i)
            break
    ds = None
    check(S.o_que_falta(p, plano)["camadas"] == ["st_conteiner"], "detecta camada faltando")
    rel = S.completar_plano(p, plano, backup=False)
    check(rel["camadas_criadas"] == ["st_conteiner"], f"recriou camada {rel}")
    c3 = next(c for c in S.ler(plano)["camadas"] if c["nome"] == "st_conteiner")
    check(c3["geometria"] == "ponto" and c3["epsg"] == 31983 and
          {f["nome"] for f in c3["campos"]} >= {"lote", "codigo_conteiner"}, f"camada criada {c3}")

    # ------------------------------------------------------------ relatório
    xlsx = os.path.join(tmp, "val.xlsx")
    V.relatorio_xlsx(r2, xlsx)
    from openpyxl import load_workbook
    wb = load_workbook(xlsx)
    check(wb.sheetnames == ["Resumo", "Erros"] and wb["Erros"].max_row == len(r2["erros"]) + 1,
          "relatório xlsx")

    # ------------------------------------------------------------ abas 4 e 5 (QGIS sem tela)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from qgis.core import QgsApplication, QgsProject
    qgs = QgsApplication([], False)
    qgs.initQgis()
    from unittest import mock
    from planos import janela as J

    class Canvas:
        def zoomToSelected(self, lyr):
            pass

    class Iface:
        def mainWindow(self):
            return None

        def mapCanvas(self):
            return Canvas()

        def setActiveLayer(self, lyr):
            pass

    pasta = os.path.join(tmp, "contrato")
    with mock.patch.object(J.QgsSettings, "value", return_value=""):
        jan = J.JanelaPlanos(Iface())
    jan._abrir_pasta(pasta)
    jan.perfil = perfil.perfil_slu_df()
    jan._salvar_perfil()
    # plano sem os campos ciclo/flag_semana de novo
    plano2 = os.path.join(tmp, "CC01b.gdb")
    shutil.copytree(cc01, plano2)
    jan.estado["planos"] = [plano2]
    jan.aba_plano.atualizar()
    check(jan.aba_plano.cb.currentText() == plano2, "plano na lista")
    textos = [jan.aba_plano.arv.topLevelItem(i).text(0)
              for i in range(jan.aba_plano.arv.topLevelItemCount())]
    check(textos == ["🟡 lm_area_circuito_planejado"], f"o que falta na aba: {textos}")
    with mock.patch.object(J.QMessageBox, "question", return_value=J.QMessageBox.StandardButton.Yes), \
            mock.patch("planos.abas_plano.QMessageBox.question",
                       return_value=J.QMessageBox.StandardButton.Yes), \
            mock.patch("planos.abas_plano.QMessageBox.information"):
        jan.aba_plano._criar()
    check("Estrutura completa" in jan.aba_plano.lb.text(), jan.aba_plano.lb.text())
    jan.aba_validar.atualizar()
    jan.aba_validar.resultado = V.validar(jan.perfil, plano2)
    jan.aba_validar._mostrar()
    raiz = jan.aba_validar.arv.topLevelItem(0)
    check(raiz.text(0) == "lm_area_circuito_planejado" and raiz.childCount() == 2,
          f"árvore validação {raiz.text(0)} {raiz.childCount()}")
    jan.aba_validar._ir_para(raiz.child(0), 0)
    lyr = [l for l in QgsProject.instance().mapLayers().values()
           if l.name() == "lm_area_circuito_planejado"]
    check(lyr and lyr[0].selectedFeatureCount() == area["feicoes"], "selecionou no mapa")
    jan.desligar()
    QgsProject.instance().removeAllMapLayers()
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("OK" if not FALHAS else f"{len(FALHAS)} FALHA(S)")
sys.exit(1 if FALHAS else 0)
