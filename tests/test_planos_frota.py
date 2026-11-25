# -*- coding: utf-8 -*-
"""
Planos do Contrato — frota e equipe: adequar o plano já feito à frota e ao pessoal do edital
novo (juntar circuitos, dividir um circuito entre vizinhos, trocar equipamento). Usa cópias
de Gdb/CC01.gdb e Gdb/CS01.gdb (os originais não mudam).

    "C:\\Program Files\\QGIS 3.44.15\\bin\\python-qgis-ltr.bat" tests\\test_planos_frota.py
"""
import copy
import os
import shutil
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.join(AQUI, "..", "src", "qgis_ia")
GDB = os.path.join(AQUI, "..", "Gdb")
sys.path.insert(0, PLUGIN)

from planos import estrutura, frota as F, perfil, validacao as V  # noqa: E402

FALHAS = []


def check(cond, msg):
    if not cond:
        FALHAS.append(msg)
        print("FALHOU:", msg)


# ------------------------------------------------------------ utilidades (sem arquivo)
check(F._minutos("06:30") == 390 and F._minutos("19h") == 1140 and F._minutos(630) == 390
      and F._minutos(None) is None, "horários")
check(F._turno("NOTURNO", 400) == "Noturno" and F._turno("", 1200) == "Noturno"
      and F._turno(None, 420) == "Diurno", "turno")
check(F._semelhanca("Compactadores de 19m³", "Caminhão Coletor Compactador de 19 m³") >
      F._semelhanca("Compactadores de 19m³", "Caminhão Coletor Compactador de 15 m³"),
      "semelhança pela capacidade")
check(F._semelhanca("Compactador 19 m³ c/ munk", "Compactador de 19 m³ com braço munk") >
      F._semelhanca("Compactador 19 m³ c/ munk", "Compactador de 19 m³"), "semelhança munk")
c = lambda ini, fim, d=(1, 0, 0, 0, 0, 0, 0): {"ini": ini, "fim": fim, "dias": list(d),
                                               "turno": "Diurno", "equip": "0"}
check(F._pico([c(420, 600), c(700, 900)], 60) == 1, "dois circuitos sem sobreposição = 1 veículo")
check(F._pico([c(420, 600), c(630, 900)], 60) == 2, "folga de 60 min")
check(F._pico([c(1140, 120), c(1150, 130)], 0) == 2, "noturno que vira o dia")
nec = F.necessidade([c(420, 900), c(420, 900, (1, 1, 0, 0, 0, 0, 0))], 60)
check(nec["veiculos"][("0", "Diurno")] == (2, 0), f"pico na segunda {nec['veiculos']}")

p = perfil.perfil_slu_df()
check(not perfil.valida({k: v for k, v in p.items() if not k.startswith("_")}),
      "perfil SLU com recursos/equipes válido")
rec = F.recursos(p, ["P1"], "1")
check(rec["equip"]["0"]["Noturno"] == 17 and rec["equip"]["1"]["Diurno"] == 10,
      "frota P1 lote 1 (Anexo R)")
check(rec["pessoal"]["coletor"]["Diurno"] == 130 and rec["equipes"]["0"]["coletor"] == 3,
      "pessoal e equipe padrão P1")
lote_cs = [c for c in p["camadas"] if c["nome"] == "st_circuito_planejado"]
check(any("CS01" in str(f["valores_permitidos"]) for cam in lote_cs for f in cam["campos"]
          if f["nome"] == "lote"), "domínio de lote inclui CS01 (P2)")

tmp = tempfile.mkdtemp()
try:
    cc = os.path.join(tmp, "CC01.gdb")
    cs = os.path.join(tmp, "CS01.gdb")
    shutil.copytree(os.path.join(GDB, "CC01.gdb"), cc)
    shutil.copytree(os.path.join(GDB, "CS01.gdb"), cs)

    # ------------------------------------------------------------ mapa de campos
    est = estrutura.ler(cc)
    m = F.mapear(est)
    check(m and m["camada"] == "lm_area_circuito_planejado" and m["codigo"] == "codigo_circuito"
          and m["equipamento"] == "id_tipo_equipamento" and m["inicio"] == "horario_inicio"
          and m["fim"] == "horario_termino" and m["regiao"] == "codigo_ra"
          and m["dias"][6] == "domingo", f"mapa {m}")
    check(("st_circuito_planejado", "codigo_circuito") in m["linhas"] and
          m["inicio_fim"] == {"st_circuito_inicio_fim": "tipo"}, "linhas e início/fim")
    check(F.lote_do_arquivo(p, cc) == "1", "lote pelo nome do arquivo")

    # ------------------------------------------------------------ comparar
    r = F.comparar(p, cc)
    lin = {(l["categoria"], l["codigo"], l["turno"]): l for l in r["linhas"]}
    check(r["circuitos"] == 130 and not r["cabe"], "CC01 não cabe no edital novo")
    check(lin[("equipamento", "0", "Noturno")]["plano"] == 26 and
          lin[("equipamento", "0", "Noturno")]["edital"] == 17, "noturno 26 x 17")
    check(lin[("equipamento", "0", "Diurno")]["situacao"] == "excede", "diurno 33 x 32")
    check(lin[("pessoal", "coletor", "Noturno")]["situacao"] == "excede", "coletores noturno")

    # nomes sem código: o casamento por nome dá o mesmo resultado
    p2 = copy.deepcopy(p)
    for x in p2["recursos"] + p2["equipes"]:
        x["codigo_no_plano"] = ""
    r2 = F.comparar(p2, cc)
    check([(l["codigo"], l["turno"], l["edital"]) for l in r2["linhas"]] ==
          [(l["codigo"], l["turno"], l["edital"]) for l in r["linhas"]],
          "casamento de equipamento pelo nome")

    # ------------------------------------------------------------ propor (CC01)
    pr = F.propor(p, cc)
    check(pr["cabe"], f"CC01 cabe com a proposta: {pr['nao_coube']}")
    tipos = {op["tipo"] for op in pr["operacoes"]}
    check(tipos == {"juntar", "dividir"}, f"usa juntar e dividir: {tipos}")
    check(all(len(op["recebem"]) <= 3 for op in pr["operacoes"]), "no máximo 3 vizinhos")
    check([t["de"] for t in pr["trocas"]] == ["1"] and pr["trocas"][0]["para"] == "0",
          "munk noturno (0 no edital) -> 19 m³")
    retirados = {op["circuito"] for op in pr["operacoes"]}
    recebem = {x["codigo"] for op in pr["operacoes"] for x in op["recebem"]}
    check(len(retirados) == len(pr["operacoes"]), "cada circuito sai uma vez")
    so_juntar = F.propor(p, cc, metodo="juntar")
    check(all(op["tipo"] == "juntar" for op in so_juntar["operacoes"]) and so_juntar["cabe"],
          "método só juntar")
    so_dividir = F.propor(p, cc, metodo="dividir", max_receptores=2)
    check(any(op["tipo"] == "dividir" for op in so_dividir["operacoes"]) and
          all(len(op["recebem"]) <= 2 for op in so_dividir["operacoes"]), "método dividir")
    recusa = F.propor(p, cc, substituicoes={("1", "Noturno"): ""})
    check(not recusa["trocas"][0]["para"] and not recusa["cabe"], "troca recusada")

    # ------------------------------------------------------------ aplicar (CC01)
    antes = {c["nome"]: c["feicoes"] for c in estrutura.ler(cc)["camadas"]}
    g = F.aplicar(p, cc, pr)
    check(os.path.isdir(g["saida"]) and g["saida"].endswith("CC01_adequado.gdb"), "cópia criada")
    depois = {c["nome"]: c["feicoes"] for c in estrutura.ler(g["saida"])["camadas"]}
    n_op = len(pr["operacoes"])
    check(depois["lm_area_circuito_planejado"] == 130 - n_op, "polígonos retirados")
    check(depois["st_circuito_planejado"] == antes["st_circuito_planejado"], "nenhuma linha perdida")
    check(depois["st_conteiner"] == antes["st_conteiner"], "contêineres mantidos")
    check(depois["st_circuito_inicio_fim"] == antes["st_circuito_inicio_fim"] - 2 * n_op,
          "início/fim dos retirados apagados")
    check({c["nome"]: c["feicoes"] for c in estrutura.ler(cc)["camadas"]} == antes,
          "original intacto")
    r3 = F.comparar(p, g["saida"])
    check(r3["cabe"] and r3["circuitos"] == 130 - n_op, "cópia cabe no edital")
    circ, _, _ = F.ler_circuitos(g["saida"])
    cods = {c["codigo"] for c in circ}
    check(not (retirados & cods) and recebem - retirados <= cods, "códigos na cópia")
    v = V.validar(p, g["saida"])
    regras = {e["regra"] for e in v["erros"]}
    check(not regras & {"geometria_invalida", "geometria_vazia", "obrigatorio_vazio",
                        "valor_fora_do_dominio"}, f"cópia válida: {regras}")
    try:
        F.aplicar(p, cc, pr)
        check(False, "não sobrescreve cópia existente")
    except FileExistsError:
        pass

    # ------------------------------------------------------------ CS01: troca de equipamento
    rs = F.propor(p, cs)
    t = [x for x in rs["trocas"] if x["de"] == "4"]
    check(t and t[0]["para"] == "2" and len(t[0]["circuitos"]) == 7,
          f"baú 30 m³ -> compactador 15 m³: {t}")
    check(any(op["recebem"][0]["dias_a_mais"] for op in rs["operacoes"]),
          "vizinho com dias a mais (etapa 2)")
    gs = F.aplicar(p, cs, rs, os.path.join(tmp, "CS01_novo.gdb"))
    circ, _, _ = F.ler_circuitos(gs["saida"])
    check(not any(c["equip"] == "4" for c in circ), "baú trocado na cópia")
    xlsx = F.relatorio_xlsx(rs, os.path.join(tmp, "frota.xlsx"))
    from openpyxl import load_workbook
    wb = load_workbook(xlsx)
    check(wb.sheetnames[:3] == ["Frota e equipe", "Trocas de equipamento", "Circuitos retirados"],
          f"xlsx {wb.sheetnames}")

    # ------------------------------------------------------------ ferramentas MCP
    from planos import ferramentas as FT, specs
    check("planos_frota" in FT.TOOLS and "planos_adequar_frota" in specs.SPECS, "MCP registrado")

    # ------------------------------------------------------------ aba (QGIS sem tela)
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

    with mock.patch.object(J.QgsSettings, "value", return_value=""):
        jan = J.JanelaPlanos(Iface())
    jan._abrir_pasta(os.path.join(tmp, "contrato"))
    jan.perfil = perfil.perfil_slu_df()
    jan._salvar_perfil()
    jan._mostrar_perfil()
    titulos = [jan.arv_perfil.topLevelItem(i).text(0)
               for i in range(jan.arv_perfil.topLevelItemCount())] \
        if hasattr(jan, "arv_perfil") else []
    check(jan.abas.tabText(4) == "5. Frota e equipe" and jan.abas.tabText(5) == "6. Validar",
          "abas 5 e 6")
    jan.estado["planos"] = [cc]
    jan.aba_plano.atualizar()
    a = jan.aba_frota
    a.atualizar()
    check(a.cb.currentText() == cc, "plano na aba frota")
    a._tabela(r["linhas"])
    check(a.tab.topLevelItemCount() == len(r["linhas"]), "tabela de comparação")
    a.proposta = pr
    a._mostrar()
    check(a.arv.topLevelItem(0).text(0) == "Trocas de equipamento" and
          a.arv.topLevelItem(1).childCount() == len(pr["operacoes"]), "árvore da proposta")
    check(a.bt_gravar.isEnabled(), "gravar habilitado")
    op_item = a.arv.topLevelItem(1).child(0)
    a._ir_para(op_item, 0)
    lyr = [l for l in QgsProject.instance().mapLayers().values()
           if l.name() == "lm_area_circuito_planejado"]
    check(lyr and lyr[0].selectedFeatureCount() == 1 + len(pr["operacoes"][0]["recebem"]),
          "selecionou circuito e vizinhos")
    with mock.patch.object(a, "_propor") as prop:
        it = a.arv.topLevelItem(0).child(0)
        it.setCheckState(0, J.Qt.CheckState.Unchecked)
        check(("1", "Noturno") in a.recusadas and prop.called, "desmarcar troca repropõe")
    jan.desligar()
    QgsProject.instance().removeAllMapLayers()
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("OK" if not FALHAS else f"{len(FALHAS)} FALHA(S)")
sys.exit(1 if FALHAS else 0)
