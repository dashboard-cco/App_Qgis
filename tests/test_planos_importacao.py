# -*- coding: utf-8 -*-
"""
Planos do Contrato — 2.2 Trazer os seus dados: ligar uma camada qualquer ao modelo do plano,
converter valores (domínios, sim/não, hora em texto), reprojetar e gravar. A origem é montada
a partir de Gdb/CC01.gdb com outros nomes, outro sistema e valores por extenso.

    "C:\\Program Files\\QGIS 3.44.15\\bin\\python-qgis-ltr.bat" tests\\test_planos_importacao.py
"""
import json
import os
import shutil
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.join(AQUI, "..", "src", "qgis_ia")
GDB = os.path.join(AQUI, "..", "Gdb")
sys.path.insert(0, PLUGIN)

from osgeo import gdal, ogr, osr  # noqa: E402

from planos import estrutura as S, importacao as I, perfil  # noqa: E402

gdal.UseExceptions()
FALHAS = []


def check(cond, msg):
    if not cond:
        FALHAS.append(msg)
        print("FALHOU:", msg)


# ------------------------------------------------------------ funções puras
check(I.txt(1.0) == "1" and I.txt(" 2.000 ") == "2" and I.txt(None) == "", "txt")
check(I.converter("7", ogr.OFTInteger) == (7, None), "inteiro de texto")
check(I.converter("Sim", ogr.OFTInteger) == (1, None) and I.converter("não", ogr.OFTInteger) == (0, None),
      "sim/não")
check(I.converter("abc", ogr.OFTInteger) == (None, "conversao"), "inteiro inválido")
check(I.converter("1.234,5", ogr.OFTReal) == (1234.5, None), "decimal brasileiro")
check(I.converter("07:30", ogr.OFTDateTime) == ("1899/12/30 07:30:00", None), "hora só")
check(I.converter("25/11/2026", ogr.OFTDate)[0] == "2026/11/25 00:00:00", "data br")
check(I.converter("abcdef", ogr.OFTString, 3) == ("abc", "truncado"), "truncado")
lv = I.ligar_valores(["2 - Gama", "3 - Taguatinga", "N - Noturno"], ["GAMA", "taguatinga", "2", "Noturno", "Xyz"])
check(lv == {"GAMA": "2", "taguatinga": "3", "2": "2", "Noturno": "N", "Xyz": ""}, f"ligar_valores {lv}")
lc = I.ligar_campos([{"nome": "codigo_circuito", "alias": "Código Circuito", "descricao": ""},
                     {"nome": "codigo_ra", "alias": "Código RA", "descricao": ""},
                     {"nome": "turno", "alias": "", "descricao": ""}],
                    [{"nome": "TURNO", "alias": ""}, {"nome": "Codigo_Circuito", "alias": ""},
                     {"nome": "cod_regiao_administrativa", "alias": ""}])
check(lc.get("codigo_circuito", {}).get("origem") == "Codigo_Circuito" and
      lc.get("turno", {}).get("como") == "nome", f"ligar_campos {lc}")

cc01 = os.path.join(GDB, "CC01.gdb")
if not os.path.isdir(cc01):
    print("aviso: Gdb/CC01.gdb não encontrado; testes de arquivo pulados")
    print("OK" if not FALHAS else f"{len(FALHAS)} FALHA(S)")
    sys.exit(1 if FALHAS else 0)

tmp = tempfile.mkdtemp(prefix="importacao_")
try:
    # ------------------------------------------------------------ origem "da empresa"
    p = perfil.perfil_slu_df()
    est_cc = S.ler(cc01)
    nomes_ra = {int(k): v for k, v in est_cc["dominios"]["cod_ra"].items()}
    src = ogr.Open(cc01)
    area = src.GetLayerByName("lm_area_circuito_planejado")
    origem = os.path.join(tmp, "circuitos_empresa.gpkg")
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(origem)
    sirgas_geo = osr.SpatialReference()
    sirgas_geo.ImportFromEPSG(4674)
    sirgas_geo.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    utm = area.GetSpatialRef().Clone()
    utm.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    ct = osr.CoordinateTransformation(utm, sirgas_geo)
    out = ds.CreateLayer("Circuitos", sirgas_geo, ogr.wkbPolygon)
    for nome, tipo in (("COD_CIRC", ogr.OFTString), ("Regiao", ogr.OFTString),
                       ("Nome do Circuito", ogr.OFTString), ("Turno", ogr.OFTString),
                       ("Seg", ogr.OFTString), ("Inicio", ogr.OFTString), ("Obs", ogr.OFTString)):
        out.CreateField(ogr.FieldDefn(nome, tipo))
    originais = {}
    for ft in area:
        g = ft.GetGeometryRef().Clone()
        if g.GetGeometryCount() != 1:      # origem com polígono simples: só os de uma parte
            continue
        cod = ft.GetField("codigo_circuito")
        originais[str(cod)] = (ft.GetField("codigo_ra"), g.Centroid().GetX(), g.Centroid().GetY(),
                               ft.GetField("segunda"), ft.GetField("turno"))
        g = ogr.ForceToPolygon(g)
        g.Transform(ct)
        n = ogr.Feature(out.GetLayerDefn())
        n.SetField("COD_CIRC", str(cod))
        ra = ft.GetField("codigo_ra")
        n.SetField("Regiao", nomes_ra.get(ra, "").upper() if ra is not None else None)
        n.SetField("Nome do Circuito", ft.GetField("nome_circuito"))
        n.SetField("Turno", ft.GetField("turno"))
        n.SetField("Seg", "Sim" if ft.GetField("segunda") == 1 else "Não")
        n.SetField("Inicio", "07:30")
        n.SetField("Obs", "x")
        n.SetGeometry(g)
        out.CreateFeature(n)
    n_origem = out.GetFeatureCount()
    ds = src = None
    check(n_origem > 50, f"origem montada ({n_origem})")

    # ------------------------------------------------------------ plano novo vazio
    plano = os.path.join(tmp, "CC01_novo.gdb")
    rel = I.criar_plano(p, plano, ["P1"])
    check("lm_area_circuito_planejado" in rel["camadas_criadas"], f"plano novo {rel['camadas_criadas']}")
    try:
        I.criar_plano(p, plano, ["P1"])
        check(False, "criar_plano por cima deveria recusar")
    except ValueError:
        pass

    # ------------------------------------------------------------ ligação automática
    info = I.montar_ligacao(p, origem, "Circuitos", plano, None, ["P1"])
    lig = info["ligacao"]
    check(lig["camada_destino"] == "lm_area_circuito_planejado", f"destino sugerido {lig['camada_destino']}")
    c = lig["campos"]
    check(c["turno"]["origem"] == "Turno" and c["turno"]["como"] == "nome", f"turno {c['turno']}")
    check(c["nome_circuito"]["origem"] == "Nome do Circuito", f"nome_circuito {c['nome_circuito']}")
    check(not c["codigo_circuito"]["origem"], "COD_CIRC não liga sozinho (fica para a IA/usuário)")
    check(I.dados_ia(info) and '"amostra"' in I.dados_ia(info), "dados para a IA")

    # resposta simulada do Claude: completa códigos, RA (valores) e dias
    resposta = "Segue:\n" + json.dumps({"campos": {
        "codigo_circuito": {"origem": "COD_CIRC"},
        "codigo_ra": {"origem": "Regiao", "valores": {"GAMA": "2 - Gama"}},
        "segunda": {"origem": "Seg"},
        "horario_inicio": {"origem": "Inicio"},
        "lote": {"fixo": "CC01"},
        "inventado": {"origem": "Nao_existe"},
        "terca": {"origem": "Campo_que_nao_existe"}},
        "observacoes": "Conferir turno."})
    lig, obs, n = I.ler_resposta_ia(resposta, info)
    c = lig["campos"]
    check(obs == "Conferir turno." and n >= 5, f"resposta IA ({n})")
    check(c["codigo_circuito"]["origem"] == "COD_CIRC" and c["lote"]["fixo"] == "CC01", "IA aplicada")
    check(not c["terca"]["origem"], "campo inexistente ignorado")
    check(c["codigo_ra"]["valores"].get("SOBRADINHO") == "5", f"valores completados {c['codigo_ra']['valores']}")

    # ------------------------------------------------------------ prévia e gravação
    pre = I.executar(lig, p, ["P1"])
    check(pre["lidas"] == n_origem and pre["gravadas"] == 0, "prévia não grava")
    check(pre["reprojecao"] and "4674" in pre["reprojecao"], f"reprojeção {pre['reprojecao']}")
    check(S.ler(plano)["camadas"][0]["feicoes"] == 0 or
          all(cm["feicoes"] == 0 for cm in S.ler(plano)["camadas"]), "plano continua vazio")
    print("\n".join(I.resumo(pre)))

    rel = I.executar(lig, p, ["P1"], gravar=True)
    check(rel["gravadas"] == n_origem and rel["backup"] and os.path.isdir(rel["backup"]), "gravou com backup")
    d = gdal.OpenEx(plano, gdal.OF_VECTOR)
    lyr = d.GetLayerByName("lm_area_circuito_planejado")
    check(lyr.GetFeatureCount() == n_origem, "contagem no plano")
    ok_ra = ok_xy = ok_seg = ok_hora = ok_lote = 0
    for ft in lyr:
        o = originais[str(ft.GetField("codigo_circuito"))]
        ok_ra += ft.GetField("codigo_ra") == o[0] or o[0] is None
        cen = ft.GetGeometryRef().Centroid()
        ok_xy += abs(cen.GetX() - o[1]) < 0.05 and abs(cen.GetY() - o[2]) < 0.05
        ok_seg += ft.GetField("segunda") == (1 if o[3] == 1 else 0)
        ok_hora += str(ft.GetField("horario_inicio")).startswith("1899/12/30 07:30")
        ok_lote += ft.GetField("lote") == "CC01"
        g = ft.GetGeometryRef()
    check(ok_ra == n_origem, f"RA por nome -> código ({ok_ra}/{n_origem})")
    check(ok_xy == n_origem, f"reprojeção volta ao lugar ({ok_xy}/{n_origem})")
    check(ok_seg == n_origem, f"Sim/Não -> 1/0 ({ok_seg}/{n_origem})")
    check(ok_hora == n_origem, f"hora em texto ({ok_hora}/{n_origem})")
    check(ok_lote == n_origem, "valor fixo")
    check(ogr.GT_Flatten(g.GetGeometryType()) == ogr.wkbMultiPolygon, "polígono -> multipolígono")
    check(S.ler(plano)["camadas"][[cm["nome"] for cm in S.ler(plano)["camadas"]].index(
        "lm_area_circuito_planejado")]["epsg"] == 31983, "sistema do plano")
    d = None

    # substituir: não duplica
    lig["substituir"] = True
    rel = I.executar(lig, p, ["P1"], gravar=True, backup=False)
    check(rel["apagadas"] == n_origem and rel["gravadas"] == n_origem, "substituir")
    d = gdal.OpenEx(plano, gdal.OF_VECTOR)
    check(d.GetLayerByName("lm_area_circuito_planejado").GetFeatureCount() == n_origem, "sem duplicar")
    d = None

    # geometria incompatível
    try:
        I.executar(dict(lig, camada_destino="st_conteiner"), p, ["P1"])
        check(False, "polígono -> ponto deveria recusar")
    except ValueError:
        pass

    # ------------------------------------------------------------ estado (reaproveitar)
    estado = {}
    I.guardar(estado, lig)
    I.guardar(estado, lig)
    check(len(estado["importacoes"]) == 1, "guardar sem repetir")
    ant = I.anterior(estado, origem, "Circuitos", plano)
    info2 = I.montar_ligacao(p, origem, "Circuitos", plano, None, ["P1"], anterior=ant)
    check(info2["ligacao"]["campos"]["codigo_circuito"]["origem"] == "COD_CIRC" and
          info2["ligacao"]["substituir"], "ligação reaproveitada")

    # ------------------------------------------------------------ linhas de shapefile -> gdb existente (cópia)
    plano2 = os.path.join(tmp, "CC01.gdb")
    shutil.copytree(cc01, plano2)
    shp = os.path.join(tmp, "linhas.shp")
    gdal.VectorTranslate(shp, cc01, layers=["st_circuito_planejado"], format="ESRI Shapefile",
                         SQLStatement="SELECT codigo_circuito AS circuito, codigo_ra AS ra, "
                                      "deslocamento AS desloc FROM st_circuito_planejado", limit=500,
                         explodeCollections=True, dstSRS="EPSG:4326")
    info3 = I.montar_ligacao(p, shp, "linhas", plano2, None, ["P1"])
    check(info3["ligacao"]["camada_destino"] == "st_circuito_planejado",
          f"linha -> {info3['ligacao']['camada_destino']}")
    antes = S.ler(plano2)
    n_antes = next(cm["feicoes"] for cm in antes["camadas"] if cm["nome"] == "st_circuito_planejado")
    lig3 = info3["ligacao"]
    lig3["campos"]["codigo_circuito"]["origem"] = "circuito"
    lig3["campos"]["codigo_ra"]["origem"] = "ra"
    lig3["campos"]["deslocamento"]["origem"] = "desloc"
    r3 = I.executar(lig3, p, ["P1"], gravar=True, backup=False)
    depois = next(cm["feicoes"] for cm in S.ler(plano2)["camadas"] if cm["nome"] == "st_circuito_planejado")
    check(depois == n_antes + r3["gravadas"] and r3["gravadas"] > 0, "acrescentar no plano existente")
    check(not r3["problemas"].get("deslocamento"), f"domínio deslocamento ok {r3['problemas']}")
    print("\n".join(I.resumo(r3)))

    # ------------------------------------------------------------ aba "5. Trazer dados" (QGIS sem tela)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import time
    from unittest import mock

    from qgis.core import QgsApplication, QgsProject
    qgs = QgsApplication([], False)
    qgs.initQgis()
    from planos import janela as J

    class Iface:
        def mainWindow(self):
            return None

        def setActiveLayer(self, lyr):
            pass

        def zoomToActiveLayer(self):
            pass

    def esperar(jan, segundos=120):
        fim = time.time() + segundos
        while jan._tarefa is not None and time.time() < fim:
            qgs.processEvents()
        qgs.processEvents()

    with mock.patch.object(J.QgsSettings, "value", return_value=""):
        jan = J.JanelaPlanos(Iface())
    jan._abrir_pasta(os.path.join(tmp, "contrato"))
    jan.perfil = p
    jan._salvar_perfil()
    jan.estado["planos"] = [plano]
    jan.estado["servicos"] = ["P1"]
    jan.estado["fontes_importacao"] = [[origem, "Circuitos"]]
    jan._salvar_estado()
    check(jan.abas.tabText(4) == "5. Trazer dados", "aba 5")
    a = jan.aba_importar
    a.atualizar()
    from planos.abas_importar import chave_fonte
    i = a.cb_origem.findData(chave_fonte(origem, "Circuitos"), J.Qt.ItemDataRole.UserRole)
    check(i > 0, "origem na lista")
    a.cb_plano.setCurrentText(plano)
    a.cb_origem.setCurrentIndex(i)
    check(a.info is not None and a.info["ligacao"]["camada_destino"] == "lm_area_circuito_planejado",
          "aba montou a ligação")
    check(a.tab.rowCount() == len(a.info["destino"]["campos"]), "linhas da tabela")
    r_ra = a._linha("codigo_ra")
    cb = a.tab.cellWidget(r_ra, 2)
    cb.setCurrentText("Regiao")
    check(a.info["ligacao"]["campos"]["codigo_ra"]["valores"].get("SOBRADINHO") == "5",
          "valores ligados ao escolher a origem")
    a.tab.selectRow(r_ra)
    check(a.tab_val.rowCount() > 3, "tabela de valores")
    v0 = a.tab_val.item(0, 0).text()
    cbv = a.tab_val.cellWidget(0, 2)
    cbv.setCurrentIndex(3)
    check(a.info["ligacao"]["campos"]["codigo_ra"]["valores"][v0] == I.codigo_valor(cbv.currentText()),
          "valor ligado à mão")
    with open(os.path.join(tmp, "contrato", "App_Qgis", "Contrato", "estado.json"), encoding="utf-8") as fh:
        salvo = I.anterior(json.load(fh), origem, "Circuitos", plano)
    check(salvo and salvo["campos"]["codigo_ra"]["origem"] == "Regiao", "ligação salva no estado.json")
    a.cb_origem.setCurrentIndex(0)
    a.cb_origem.setCurrentIndex(i)
    check(a.info["ligacao"]["campos"]["codigo_ra"]["valores"][v0] == I.codigo_valor(cbv.currentText()),
          "ligação volta ao reabrir")
    a.tab.cellWidget(r_ra, 2).setCurrentText("Regiao")
    a.tab.cellWidget(a._linha("codigo_circuito"), 2).setCurrentText("COD_CIRC")
    a._aplicar_ia(json.dumps({"campos": {"lote": {"fixo": "CC01"}}, "observacoes": "ok"}), a.info)
    check(a.info["ligacao"]["campos"]["lote"]["fixo"] == "CC01" and
          a.tab.item(a._linha("lote"), 4).text() == "valor fixo", "resposta do Claude na tabela")
    a.info["ligacao"]["campos"]["codigo_ra"]["valores"].pop(v0, None)
    a._executar(False)
    esperar(jan)
    check("Prévia" in a.txt.toPlainText(), f"prévia na aba: {a.txt.toPlainText()[:200]}")
    a.ck_subst.setChecked(True)
    with mock.patch.object(J.QMessageBox, "question", return_value=J.QMessageBox.StandardButton.Yes), \
            mock.patch.object(J.QMessageBox, "information"):
        a._executar(True)
        esperar(jan)
    check("Importado" in a.txt.toPlainText(), f"importou pela aba: {a.txt.toPlainText()[:300]}")
    d = gdal.OpenEx(plano, gdal.OF_VECTOR)
    check(d.GetLayerByName("lm_area_circuito_planejado").GetFeatureCount() == n_origem,
          "aba substituiu sem duplicar")
    d = None
    jan.desligar()
    QgsProject.instance().removeAllMapLayers()
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("OK" if not FALHAS else f"{len(FALHAS)} FALHA(S)")
sys.exit(1 if FALHAS else 0)
