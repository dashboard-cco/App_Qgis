# -*- coding: utf-8 -*-
"""
Planilha de soltura: qual veículo sai para qual circuito, em cada dia e turno.

A frota é dimensionada a partir dos circuitos do .gdb (quando não há lista de
placas): cada circuito recebe um veículo fixo do seu tipo de equipamento; um
veículo só assume outro circuito se não houver sobreposição de horário em nenhum
dos dias (com um intervalo mínimo entre eles). Os veículos recebem códigos
sequenciais (VA01, VA02...). As placas são digitadas uma vez na aba Frota e
aparecem na soltura por fórmula.
"""
import os
import re
from collections import Counter, defaultdict

from osgeo import gdal

try:
    from .. import edital_slu as E
    from . import slu
except ImportError:
    import edital_slu as E
    import slu

SEMANA = 7 * 1440


def _min(v):
    m = re.search(r"(\d{1,2}):(\d{2})", str(v or ""))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _hhmm(m):
    m %= 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def _intervalos(dias, ini, fim, folga):
    """Intervalos ocupados na semana (minutos), com a folga no fim."""
    dur = (fim - ini) % 1440 or 1440
    out = []
    for d, ativo in enumerate(dias):
        if ativo:
            a = d * 1440 + ini
            b = a + dur + folga
            if b <= SEMANA:
                out.append((a, b))
            else:  # domingo à noite invade a segunda
                out.append((a, SEMANA))
                out.append((0, b - SEMANA))
    return out


def _conflita(ocupado, novos):
    return any(a < d and c < b for a, b in novos for c, d in ocupado)


def _alocar(circuitos, folga, dois_turnos):
    """First-fit: circuitos mais longos/frequentes primeiro, por tipo de equipamento."""
    veiculos = []  # {"tipo", "ocupado": [...], "circuitos": [...], "turnos": set()}
    ordem = sorted(circuitos, key=lambda c: (c["equip"], -sum(c["dias"]), c["ini"], c["codigo"]))
    for c in ordem:
        iv = _intervalos(c["dias"], c["ini"], c["fim"], folga)
        for v in veiculos:
            if v["tipo"] != c["equip"]:
                continue
            if not dois_turnos and v["turnos"] and c["turno"] not in v["turnos"]:
                continue
            if not _conflita(v["ocupado"], iv):
                break
        else:
            v = {"tipo": c["equip"], "ocupado": [], "circuitos": [], "turnos": set()}
            veiculos.append(v)
        v["ocupado"].extend(iv)
        v["circuitos"].append(c)
        v["turnos"].add(c["turno"])
    return veiculos


def _ler_circuitos(gdb_path):
    ds = gdal.OpenEx(gdb_path, gdal.OF_VECTOR)
    if ds is None:
        raise ValueError(f"Não abri {gdb_path}")
    km = defaultdict(lambda: [0.0, 0.0])
    ll = ds.GetLayerByName("st_circuito_planejado")
    if ll is not None:
        for f in ll:
            g = f.GetGeometryRef()
            if g is not None:
                km[f.GetField("codigo_circuito")][1 if f.GetField("deslocamento") == 1 else 0] \
                    += g.Length() / 1000
    out, sem_horario = [], []
    for f in ds.GetLayerByName("lm_area_circuito_planejado"):
        cod = f.GetField("codigo_circuito")
        ini, fim = _min(f.GetField("horario_inicio")), _min(f.GetField("horario_termino"))
        dias = [int(f.GetField(d) or 0) for d in E.DIAS_CAMPOS]
        if ini is None or fim is None or not any(dias):
            sem_horario.append(cod)
            continue
        ra = f.GetField("codigo_ra")
        out.append({
            "codigo": cod, "nome": f.GetField("nome_circuito"), "ra": E.RA.get(ra, ra),
            "dias": dias, "ini": ini, "fim": fim,
            "turno": f.GetField("turno") or ("Noturno" if ini >= 18 * 60 else "Diurno"),
            "equip": f.GetField("id_tipo_equipamento"),
            "frequencia": f.GetField("frequencia"),
            "destino": f.GetField("local_destinacao"), "pesagem": f.GetField("local_pesagem"),
            "km_coleta": round(km[cod][0], 1), "km_passagem": round(km[cod][1], 1),
            "tipo_servico": E.TIPO_SERVICO_DESC.get(f.GetField("id_tipo_servico")),
        })
    return out, sem_horario


def slu_planilha_soltura(gdb_path, saida_xlsx, intervalo_min=60, dois_turnos=True,
                         servico=None, lote=None, prefixo_veiculo="VA"):
    """Gera a planilha de soltura (.xlsx) do plano: soltura por dia/turno, frota
    dimensionada (aba Frota, com placas a preencher), grade semanal por veículo,
    resumo de veículos por dia/turno e a lista de circuitos."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    servico, lote = slu._servico_lote_de_gdb(gdb_path, servico, lote)
    prefixo = E.lote_codigo(servico, lote)
    circuitos, sem_horario = _ler_circuitos(gdb_path)
    veiculos = _alocar(circuitos, int(intervalo_min), bool(dois_turnos))
    so_um_turno = _alocar(circuitos, int(intervalo_min), False)
    por_tipo = Counter(v["tipo"] for v in veiculos)
    ordem_v = sorted(veiculos, key=lambda v: (v["tipo"], min(c["ini"] for c in v["circuitos"]),
                                              min(c["codigo"] for c in v["circuitos"])))
    for n, v in enumerate(ordem_v, start=1):
        v["id"] = f"{prefixo_veiculo}{n:02d}"
        for c in v["circuitos"]:
            c["veiculo"] = v["id"]

    wb = Workbook()
    azul = PatternFill("solid", fgColor="1F4E78")
    claro = PatternFill("solid", fgColor="DDEBF7")
    noite = PatternFill("solid", fgColor="E7E6F7")
    amarelo = PatternFill("solid", fgColor="FFF2CC")
    fino = Side(style="thin", color="A6A6A6")
    borda = Border(left=fino, right=fino, top=fino, bottom=fino)
    centro = Alignment(horizontal="center", vertical="center", wrap_text=True)

    def cabecalho(ws, linha, colunas, larguras):
        for i, (t, w) in enumerate(zip(colunas, larguras), start=1):
            c = ws.cell(linha, i, t)
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = azul
            c.alignment = centro
            c.border = borda
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = ws.cell(linha + 1, 1)

    titulo = (f"Planilha de Soltura — {servico} {E.SERVICOS[servico]['nome']} — "
              f"{prefixo} (Lote {lote:02d})")

    # ------------------------------------------------------------ Soltura
    ws = wb.active
    ws.title = "Soltura"
    ws["A1"] = titulo
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = ("Placa vem da aba Frota. Motorista e coletores: preencher. Horários do plano "
                "de serviço (.gdb).")
    ws["A2"].font = Font(italic=True, color="595959")
    cols = ["Dia", "Turno", "Saída (início)", "Término", "Veículo", "Placa", "Equipamento",
            "Código Circuito", "Nome do Circuito", "RA", "Tipo de Serviço", "Frequência",
            "Km coleta", "Km passagem", "Destinação", "Pesagem", "Motorista", "Coletores",
            "Observação"]
    cabecalho(ws, 4, cols, (11, 9, 9, 9, 13, 11, 30, 11, 30, 18, 30, 26, 9, 9, 24, 24, 20, 24, 24))
    lin = 5
    contagem = defaultdict(Counter)  # (dia, turno) -> tipo -> nº veículos
    for d, nome_dia in enumerate(E.DIAS_NOMES):
        do_dia = [c for c in circuitos if c["dias"][d]]
        do_dia.sort(key=lambda c: (0 if c["turno"] == "Diurno" else 1, c["ini"], c["veiculo"]))
        for c in do_dia:
            contagem[(nome_dia, c["turno"])][c["equip"]] += 1
            vals = [nome_dia, c["turno"], _hhmm(c["ini"]), _hhmm(c["fim"]), c["veiculo"],
                    f'=IFERROR(IF(VLOOKUP(E{lin},Frota!$A:$D,4,FALSE)="","",'
                    f'VLOOKUP(E{lin},Frota!$A:$D,4,FALSE)),"")',
                    E.EQUIPAMENTOS.get(c["equip"], c["equip"]), c["codigo"], c["nome"], c["ra"],
                    c["tipo_servico"], c["frequencia"], c["km_coleta"], c["km_passagem"],
                    c["destino"], c["pesagem"], None, None, None]
            for i, v in enumerate(vals, start=1):
                cel = ws.cell(lin, i, v)
                cel.border = borda
                if c["turno"] == "Noturno":
                    cel.fill = noite
            for i in (17, 18, 19):
                ws.cell(lin, i).fill = amarelo
            lin += 1
    ws.auto_filter.ref = f"A4:{get_column_letter(len(cols))}{lin - 1}"

    # ------------------------------------------------------------ Frota
    wf = wb.create_sheet("Frota")
    wf["A1"] = f"Frota dimensionada — {prefixo}"
    wf["A1"].font = Font(bold=True, size=13)
    wf["A2"] = "Preencha a coluna Placa (amarela); ela aparece automaticamente na Soltura."
    wf["A2"].font = Font(italic=True, color="595959")
    cabecalho(wf, 4, ["Veículo", "Código Equip.", "Equipamento", "Placa", "Nº circuitos",
                      "Turnos", "Circuitos", "Km coleta/semana"],
              (13, 9, 34, 12, 10, 16, 60, 14))
    for r, v in enumerate(ordem_v, start=5):
        kms = sum(c["km_coleta"] * sum(c["dias"]) for c in v["circuitos"])
        vals = [v["id"], v["tipo"], E.EQUIPAMENTOS.get(v["tipo"], v["tipo"]), None,
                len(v["circuitos"]), " e ".join(sorted(v["turnos"])),
                ", ".join(f"{c['codigo']} ({c['turno'][0]} {''.join(E.DIAS_INICIAL[i] for i, a in enumerate(c['dias']) if a)})"
                          for c in sorted(v["circuitos"], key=lambda c: c["ini"])),
                round(kms, 1)]
        for i, val in enumerate(vals, start=1):
            cel = wf.cell(r, i, val)
            cel.border = borda
        wf.cell(r, 4).fill = amarelo

    # ------------------------------------------------------------ Grade semanal
    wg = wb.create_sheet("Grade semanal")
    wg["A1"] = "Circuito de cada veículo por dia e turno (D = diurno, N = noturno)"
    wg["A1"].font = Font(bold=True, size=13)
    cab = ["Veículo", "Placa"] + [f"{dn[:3]} {t}" for dn in E.DIAS_NOMES for t in ("D", "N")]
    cabecalho(wg, 3, cab, [13, 11] + [9] * 14)
    for r, v in enumerate(ordem_v, start=4):
        wg.cell(r, 1, v["id"]).border = borda
        cel = wg.cell(r, 2, f'=IFERROR(IF(VLOOKUP(A{r},Frota!$A:$D,4,FALSE)="","",'
                            f'VLOOKUP(A{r},Frota!$A:$D,4,FALSE)),"")')
        cel.border = borda
        for d in range(7):
            for k, t in enumerate(("Diurno", "Noturno")):
                cods = [str(c["codigo"]) for c in v["circuitos"] if c["dias"][d] and c["turno"] == t]
                cel = wg.cell(r, 3 + d * 2 + k, "\n".join(cods) or None)
                cel.border = borda
                cel.alignment = centro
                if cods:
                    cel.fill = claro if t == "Diurno" else noite

    # ------------------------------------------------------------ Resumo
    wr = wb.create_sheet("Resumo")
    wr["A1"] = titulo
    wr["A1"].font = Font(bold=True, size=13)
    tipos = sorted({c["equip"] for c in circuitos})
    cabecalho(wr, 3, ["Dia", "Turno"] + [E.EQUIPAMENTOS.get(t, t) for t in tipos] + ["Total"],
              [12, 10] + [26] * len(tipos) + [9])
    r = 4
    for dn in E.DIAS_NOMES:
        for t in ("Diurno", "Noturno"):
            cnt = contagem.get((dn, t), Counter())
            vals = [dn, t] + [cnt.get(k, 0) for k in tipos] + [sum(cnt.values())]
            for i, val in enumerate(vals, start=1):
                wr.cell(r, i, val).border = borda
            r += 1
    r += 1
    wr.cell(r, 1, "Frota necessária").font = Font(bold=True)
    r += 1
    for t in tipos:
        wr.cell(r, 1, E.EQUIPAMENTOS.get(t, t))
        wr.cell(r, 3, por_tipo.get(t, 0))
        r += 1
    wr.cell(r, 1, "Total (veículo pode fazer diurno e noturno)" if dois_turnos else "Total")
    wr.cell(r, 3, len(veiculos)).font = Font(bold=True)
    r += 1
    wr.cell(r, 1, "Total se cada veículo fizesse um só turno")
    wr.cell(r, 3, len(so_um_turno))
    r += 2
    wr.cell(r, 1, f"Intervalo mínimo entre circuitos do mesmo veículo: {intervalo_min} min. "
                  "Sem reserva técnica: acrescente a reserva exigida no contrato.")
    wr.cell(r, 1).font = Font(italic=True, color="595959")
    wr.column_dimensions["A"].width = 44

    # ------------------------------------------------------------ Circuitos
    wc = wb.create_sheet("Circuitos")
    cabecalho(wc, 1, ["Código Circuito", "Nome do Circuito", "Veículo", "Turno", "Início",
                      "Término", "Frequência", "Equipamento", "Km coleta", "Km passagem"],
              (11, 32, 13, 9, 8, 8, 30, 32, 9, 9))
    for r, c in enumerate(sorted(circuitos, key=lambda c: c["codigo"]), start=2):
        vals = [c["codigo"], c["nome"], c["veiculo"], c["turno"], _hhmm(c["ini"]),
                _hhmm(c["fim"]), c["frequencia"], E.EQUIPAMENTOS.get(c["equip"], c["equip"]),
                c["km_coleta"], c["km_passagem"]]
        for i, val in enumerate(vals, start=1):
            wc.cell(r, i, val).border = borda
    wc.auto_filter.ref = f"A1:J{len(circuitos) + 1}"

    os.makedirs(os.path.dirname(os.path.abspath(saida_xlsx)), exist_ok=True)
    wb.save(saida_xlsx)
    pico = max(contagem.items(), key=lambda kv: sum(kv[1].values())) if contagem else None
    return {
        "success": True, "xlsx": saida_xlsx, "circuitos": len(circuitos),
        "circuitos_sem_horario_ou_dias": sem_horario,
        "frota": {E.EQUIPAMENTOS.get(t, t): n for t, n in sorted(por_tipo.items())},
        "frota_total": len(veiculos), "frota_total_um_turno_por_veiculo": len(so_um_turno),
        "pico": {"dia_turno": f"{pico[0][0]} {pico[0][1]}",
                 "veiculos": sum(pico[1].values())} if pico else None,
        "linhas_soltura": lin - 5,
    }


TOOLS = {"slu_planilha_soltura": slu_planilha_soltura}
