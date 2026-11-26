# -*- coding: utf-8 -*-
"""
Planos do Contrato — frota e equipe: adequar o plano já feito à frota e ao pessoal do edital
novo (juntar circuitos, dividir um circuito entre vizinhos, trocar equipamento). Usa cópias
de Gdb/CC01.gdb e Gdb/CS01.gdb (os originais não mudam).

    "C:\\Program Files\\QGIS 3.44.15\\bin\\python-qgis-ltr.bat" tests\\test_planos_frota.py
"""
import copy
import datetime
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

    # ------------------------------------------------------------ turnos do edital
    tur = F.turnos_edital(p, ["P1"])
    check(F.horario_edital(tur, "0", "Diurno") == (360, 860) and
          F.horario_edital(tur, "0", "Noturno") == (960, 20), "horários P1 (Quadro 05)")
    check(F.horario_edital(tur, "1", "Diurno") == (480, 980), "munk: 08h00-16h20 (papa-lixo)")
    check(F.horario_edital(tur, "1", "Diurno", (360, 860)) == (360, 860),
          "horário atual que já é do edital fica")
    check(abs(F.jornada_edital(tur, "0", "Noturno", 8) - 22 / 3) < 1e-9, "jornada 7h20")

    # ------------------------------------------------------------ propor (CC01, sem histórico)
    pr = F.propor(p, cc)
    check(pr["cabe"], f"CC01 cabe com a proposta: {pr['nao_coube']}")
    tipos = {op["tipo"] for op in pr["operacoes"]}
    check(tipos == {"juntar", "dividir"}, f"usa juntar e dividir: {tipos}")
    check(all(len(op["recebem"]) <= 3 for op in pr["operacoes"]), "no máximo 3 vizinhos")
    check(not pr["trocas"] and [(m["circuito"], m["para"], m["inicio"], m["fim"])
                                for m in pr["mudancas_turno"]] ==
          [("182302", "Diurno", "08:00", "16:20")], "munk noturno -> diurno 08h00-16h20")
    hor = {(h["equip"], h["turno"]): h for h in pr["horarios"]}
    check(hor[("0", "Diurno")]["para"] == "06:00–14:20" and
          hor[("0", "Noturno")]["para"] == "16:00–00:20" and
          len(hor[("0", "Diurno")]["circuitos"]) == 68, f"horários do edital {list(hor)}")
    check(not pr["horas_depois"] and pr["historico"] is None, "sem histórico: sem horas")
    retirados = {op["circuito"] for op in pr["operacoes"]}
    recebem = {x["codigo"] for op in pr["operacoes"] for x in op["recebem"]}
    check(len(retirados) == len(pr["operacoes"]), "cada circuito sai uma vez")
    so_juntar = F.propor(p, cc, metodo="juntar")
    check(all(op["tipo"] == "juntar" for op in so_juntar["operacoes"]) and so_juntar["cabe"],
          "método só juntar")
    so_dividir = F.propor(p, cc, metodo="dividir", max_receptores=2)
    check(any(op["tipo"] == "dividir" for op in so_dividir["operacoes"]) and
          all(len(op["recebem"]) <= 2 for op in so_dividir["operacoes"]), "método dividir")
    sem_mudar = F.propor(p, cc, mudar_turno=False)
    check([t["de"] for t in sem_mudar["trocas"]] == ["1"] and sem_mudar["trocas"][0]["para"] == "0"
          and not sem_mudar["mudancas_turno"], "sem mudar turno: munk noturno -> 19 m³")
    recusa = F.propor(p, cc, mudar_turno=False, substituicoes={("1", "Noturno"): ""})
    check(not recusa["trocas"][0]["para"] and not recusa["cabe"], "troca recusada")
    sem_hor = F.propor(p, cc, horarios=False)
    check(not sem_hor["horarios"], "horários mantidos se pedido")

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
    por = {c["codigo"]: c for c in circ}
    check(por["182302"]["turno"] == "Diurno" and por["182302"]["turno_bruto"] == "Diurno" and
          (por["182302"]["ini"], por["182302"]["fim"]) == (480, 980), "munk gravado no diurno")
    check({(c["ini"], c["fim"]) for c in circ if c["equip"] == "0"} == {(360, 860), (960, 20)},
          "horários gravados na cópia")
    check(g["horarios"] >= 129 and g["mudancas_turno"] == 1, f"contagem gravada {g}")
    try:
        F.aplicar(p, cc, pr)
        check(False, "não sobrescreve cópia existente")
    except FileExistsError:
        pass

    # ------------------------------------------------------------ histórico e jornada
    from planos import historico as H
    check(abs(H.horas("7:20") - 22 / 3) < 1e-9 and H.horas(":00") == 0 and
          abs(H.horas(datetime.time(6, 30)) - 6.5) < 1e-9 and H.hhmm(7 + 1 / 3) == "7h20"
          and H.hhmm(-1.5) == "-1h30", "horas/hhmm")
    circ0, _, _ = F.ler_circuitos(cc)
    diurnos = sorted(c["codigo"] for c in circ0 if c["turno"] == "Diurno" and c["equip"] == "0")
    pesado = diurnos[0]
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "P1"
    ws.append(["RD", "Veículo", "Início Operação", "Tempo Total RD", "Tempo de Refeição",
               "Tempo Produtivo", "Tempo Improdutivo", "Peso 1", "Setor 1", "Peso 2", "Setor 2"])
    rd = 1
    for c in circ0:
        trab = 8.5 if c["codigo"] == pesado else 5.0
        for d in range(6):
            ws.append([rd, "V1", datetime.datetime(2026, 3, 2 + d, 7), datetime.time(int(trab + 1),
                       int(round((trab % 1) * 60))), datetime.time(1, 0),
                       datetime.time(int(trab - 1), int(round((trab % 1) * 60))),
                       datetime.time(1, 0), 9000, int(c["codigo"]), 0, ""])
            rd += 1
    ws.append([rd, "V9", datetime.datetime(2026, 3, 9, 7), "0:10:00", None, None, None,
               100, 999, 0, ""])   # RD curto: fica de fora
    arq_h = os.path.join(tmp, "historico.xlsx")
    wb.save(arq_h)
    cache = os.path.join(tmp, "hist.json")
    h = H.ler(arq_h, cache=cache)
    check(len(h["circuitos"]) == 130 and abs(h["circuitos"][pesado]["trab"] - 8.5) < 0.02
          and abs(h["circuitos"][diurnos[1]]["peso"] - 9.0) < 1e-6 and os.path.exists(cache),
          f"histórico lido: {len(h['circuitos'])}")
    check(H.ler(arq_h, cache=cache)["_chave"] == h["_chave"], "cache do histórico")
    ph = F.propor(p, cc, historico=h)
    J = 7 + 20 / 60
    check(ph["historico"]["circuitos"] == 130 and abs(ph["jornada"] - J) < 1e-3,
          "proposta com histórico")
    rec_ok = all(r["tempo_depois"] is not None and r["tempo_depois"] <= J + 1e-6
                 for op in ph["operacoes"] for r in op["recebem"])
    check(rec_ok, "quem recebe cabe na jornada")
    al = [op for op in ph["operacoes"] if op["tipo"] == "aliviar"]
    check(any(op["circuito"] == pesado for op in al) or
          any(a["circuito"] == pesado for a in ph["acima_jornada"]),
          "circuito acima da jornada: aliviado ou listado")
    check(not any(a["circuito"] != pesado for a in ph["acima_jornada"]),
          f"só o pesado acima da jornada: {ph['acima_jornada']}")
    noturno = [h_ for h_ in ph["horas_depois"] if h_["turno"] == "Noturno" and h_["codigo"] == "0"]
    check(noturno and all(h_["capacidade"] == round(17 * J, 1) for h_ in noturno),
          "horas por dia: 17 veículos × 7h20")
    if not ph["cabe"]:
        check(any("faltam" in n or "folga" in n for n in ph["nao_coube"]),
              f"diz o que falta: {ph['nao_coube']}")
    gh = F.aplicar(p, cc, ph, os.path.join(tmp, "CC01_jornada.gdb"))
    ch, _, _ = F.ler_circuitos(gh["saida"])
    cods_h = {c["codigo"] for c in ch}
    check({op["circuito"] for op in al} <= cods_h, "aliviado continua na cópia")
    check(len(ch) == 130 - len([op for op in ph["operacoes"] if op["tipo"] != "aliviar"]),
          "só os retirados saem")
    vh = V.validar(p, gh["saida"])
    regras = {e["regra"] for e in vh["erros"]}
    check(not regras & {"geometria_invalida", "geometria_vazia", "obrigatorio_vazio",
                        "valor_fora_do_dominio"}, f"cópia com jornada válida: {regras}")
    xh = F.relatorio_xlsx(ph, os.path.join(tmp, "frota_jornada.xlsx"))
    from openpyxl import load_workbook
    nomes_abas = load_workbook(xh).sheetnames
    check({"Horários do edital", "Mudança de turno", "Horas por dia"} <= set(nomes_abas),
          f"xlsx com jornada {nomes_abas}")

    # ------------------------------------------------------------ equipar e desdobrar
    pd_ = F.propor(p, cc, historico=h, equipar={"182501": "1", "182502": "1", "999999": "1"},
                   desdobrar="Sobradinho")
    check([e["circuito"] for e in pd_["equipados"]] == ["182501", "182502"] and
          all(e["para"] == "1" and e["inicio"] == "08:00" for e in pd_["equipados"]),
          f"Noroeste passa para o munk (08h00): {pd_['equipados']}")
    check(any("999999" in a for a in pd_["avisos"]), "circuito inexistente avisado")
    nv = pd_["desdobramentos"]
    check(nv and all(n["equip"] == "1" and n["servico"] == "8" and n["inicio"] == "08:00"
                     and n["turno"] == "Diurno" and "Sobradinho" in n["base"]
                     and n["tempo"] <= J + 1e-6 for n in nv),
          f"circuitos novos mistos do munk saindo de Sobradinho: {nv}")
    inteiros = [o["circuito"] for n in nv for o in n["origens"] if o["inteiro"]]
    check(inteiros and all(o["turno"] == "Noturno" for n in nv for o in n["origens"]
                           if o["inteiro"]), "recebem circuitos noturnos inteiros")
    cods_novos = [n["codigo"] for n in nv]
    check(len(set(cods_novos)) == len(cods_novos) and all(c.startswith("18") for c in cods_novos)
          and not set(cods_novos) & {c["codigo"] for c in circ0}, f"códigos novos {cods_novos}")

    def plano_de(prop, eq, t):
        return next(l["plano"] for l in prop["depois"] if l["categoria"] == "equipamento"
                    and l["codigo"] == eq and l["turno"] == t)
    check(plano_de(pd_, "1", "Diurno") <= 10, "munk diurno dentro do edital")
    check(plano_de(pd_, "0", "Noturno") < plano_de(ph, "0", "Noturno"),
          "desdobrar tira veículos do noturno")
    gd = F.aplicar(p, cc, pd_, os.path.join(tmp, "CC01_desd.gdb"))
    cd, _, _ = F.ler_circuitos(gd["saida"])
    pc = {c["codigo"]: c for c in cd}
    check(gd["novos"] == len(nv) and all(c in pc and pc[c]["equip"] == "1"
                                         and pc[c]["servico"] == "8" for c in cods_novos),
          "circuitos novos gravados")
    check(not set(inteiros) & set(pc) and pc["182501"]["equip"] == "1", "origens inteiras saem")
    check(all(pc[c]["linhas"] and pc[c]["geom"] is not None for c in cods_novos),
          "novos com linhas e polígono")
    vd = V.validar(p, gd["saida"])
    regras = {e["regra"] for e in vd["erros"]}
    check(not regras & {"geometria_invalida", "geometria_vazia", "obrigatorio_vazio",
                        "valor_fora_do_dominio"}, f"cópia desdobrada válida: {regras}")
    xd = F.relatorio_xlsx(pd_, os.path.join(tmp, "frota_desd.xlsx"))
    check({"Circuitos novos", "Outro equipamento"} <= set(load_workbook(xd).sheetnames),
          "xlsx com circuitos novos")

    # ------------------------------------------------------------ redimensionar ao máximo
    pm = F.propor(p, cc, historico=h, equipar={"182501": "1", "182502": "1"},
                  desdobrar="Sobradinho", redimensionar=True)
    om = [o for o in pm["operacoes"] if o.get("redimensionar")]
    check(om, "redimensionar ao máximo faz operações")
    check(plano_de(pm, "0", "Noturno") < plano_de(pd_, "0", "Noturno"),
          "máximo tira mais veículos do noturno")
    check(all(r_["tempo_depois"] is None or r_["tempo_depois"] <= J + 1e-6
              for o in om for r_ in o["recebem"]), "quem recebe no máximo fica até a jornada")
    check(len(pm["acima_jornada"]) <= len(pd_["acima_jornada"]), "máximo não piora a jornada")
    temas = [x["tema"] for x in pm["pontos"]]
    excede = any(l["situacao"] == "excede" and l["categoria"] == "equipamento"
                 for l in pm["depois"])
    check(excede == any(t_.startswith("Frota") for t_ in temas) and "Ordem de passagem" in temas
          and "Circuitos novos mistos" in temas, f"pontos para o órgão: {temas}")
    check(all(x["situacao"] and x["proposta"] for x in pm["pontos"]), "pontos detalhados")
    gm = F.aplicar(p, cc, pm, os.path.join(tmp, "CC01_max.gdb"))
    cm, _, _ = F.ler_circuitos(gm["saida"])
    tirados = {o["circuito"] for o in om if o["tipo"] != "aliviar"}
    check(not tirados & {c["codigo"] for c in cm}, "circuitos tirados no máximo saem da cópia")
    vm = V.validar(p, gm["saida"])
    check(not {e["regra"] for e in vm["erros"]} & {"geometria_invalida", "geometria_vazia",
                                                  "obrigatorio_vazio", "valor_fora_do_dominio"},
          "cópia redimensionada válida")
    xm = F.relatorio_xlsx(pm, os.path.join(tmp, "frota_max.xlsx"))
    check("Pontos para o órgão" in load_workbook(xm).sheetnames, "xlsx com pontos para o órgão")

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
    check(jan.abas.tabText(5) == "6. Frota e equipe" and jan.abas.tabText(6) == "7. Validar",
          "abas 6 e 7")
    jan.estado["planos"] = [cc]
    jan.aba_plano.atualizar()
    a = jan.aba_frota
    a.atualizar()
    check(a.cb.currentText() == cc, "plano na aba frota")
    a._tabela(r["linhas"])
    check(a.tab.topLevelItemCount() == len(r["linhas"]), "tabela de comparação")
    a.proposta = pr
    a._mostrar()

    def grupo(texto):
        for i in range(a.arv.topLevelItemCount()):
            if a.arv.topLevelItem(i).text(0).startswith(texto):
                return a.arv.topLevelItem(i)
        return None

    ret = grupo("Circuitos retirados")
    check(grupo("Horários do edital") is not None and grupo("Mudanças de turno") is not None
          and ret is not None and ret.childCount() == len(pr["operacoes"]), "árvore da proposta")
    check(a.bt_gravar.isEnabled(), "gravar habilitado")
    a._ir_para(ret.child(0), 0)
    lyr = [l for l in QgsProject.instance().mapLayers().values()
           if l.name() == "lm_area_circuito_planejado"]
    check(lyr and lyr[0].selectedFeatureCount() == 1 + len(pr["operacoes"][0]["recebem"]),
          "selecionou circuito e vizinhos")
    a._ir_para(grupo("Mudanças de turno").child(0), 0)
    check(lyr[0].selectedFeatureCount() == 1, "selecionou o circuito que muda de turno")
    a.proposta = sem_mudar
    a._mostrar()
    with mock.patch.object(a, "_propor") as prop:
        it = grupo("Trocas de equipamento").child(0)
        it.setCheckState(0, J.Qt.CheckState.Unchecked)
        check(("1", "Noturno") in a.recusadas and prop.called, "desmarcar troca repropõe")
    a.proposta = ph
    a._mostrar()
    check(grupo("Horas de trabalho por dia") is not None and "jornada 7h20" in a.lb.text(),
          f"árvore com jornada: {a.lb.text()}")
    a.proposta = pd_
    a._mostrar()
    a.proposta = pm
    a._mostrar()
    check(grupo("📋 Pontos para levar ao órgão") is not None, "árvore com pontos para o órgão")
    a.proposta = pd_
    a._mostrar()
    novos_g = grupo("Circuitos novos")
    check(novos_g is not None and novos_g.childCount() == len(nv) and
          grupo("Passam para outro equipamento") is not None, "árvore com desdobramento")
    check("munk" in a.cb_desd.currentText().lower(), "munk escolhido por padrão")
    a.ed_equipar.setText("182501, 182502")
    a.ck_desd.setChecked(True)
    a.ed_base.setText("Sobradinho")
    check(a.ck_maximo.isChecked(), "redimensionar ao máximo marcado por padrão")
    eqp, base, eqd, mx = a._opcoes()
    check(eqp == {"182501": "1", "182502": "1"} and base == "Sobradinho" and eqd == "1" and mx
          and jan.estado["frota_opcoes"]["maximo"] is True
          and jan.estado["frota_opcoes"]["base"] == "Sobradinho", "opções salvas no contrato")
    a._definir_hist(arq_h)
    check(jan.estado["historico_operacao"] == os.path.normpath(arq_h) and
          "historico.xlsx" in a.lb_hist.text() and "7h20" in a.lb_jornada.text(),
          "histórico escolhido na aba")
    jan.desligar()
    QgsProject.instance().removeAllMapLayers()
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("OK" if not FALHAS else f"{len(FALHAS)} FALHA(S)")
sys.exit(1 if FALHAS else 0)
