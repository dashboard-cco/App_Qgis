# -*- coding: utf-8 -*-
"""Parâmetros do dimensionamento de cada serviço (a análise feita ANTES de criar os planos).

Vêm do edital (perfil + textos lidos) e o usuário pode mudar na tela do Criar Todos:

- coleta (domiciliar/seletiva): veículos por turno, dias por semana, jornada, tempo fora do
  circuito, velocidade de coleta, viagens por turno, carga por viagem e quantidade mensal
  (t) → capacidade de cada circuito (km e t) → nº de circuitos → divisão pelos bairros;
- varrição manual: equipes simultâneas, varredores, km por mês e dias por mês → km por
  equipe/dia e por dupla → circuitos;
- varrição mecanizada: varredeiras, km por mês, dias por mês → km por máquina/noite;
- zona (drenagem, capina…): uma área por veículo/equipe.

O cálculo (circuitos por bairro) fica em setorizacao.planejar.
"""
import glob
import json
import math
import os
import re
import unicodedata

try:
    from . import empresa as EMP
    from . import pastas as PA
except ImportError:  # testes
    import empresa as EMP
    import pastas as PA


def _sa(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower().strip()


# (chave, rótulo, tipo) — a ordem é a da tabela na tela
CAMPOS = {
    "coleta": [
        ("veiculos_diurno", "Veículos no turno diurno", int),
        ("veiculos_noturno", "Veículos no turno noturno", int),
        ("dias_semana", "Dias de coleta por semana", int),
        ("frequencia", "Frequência nos bairros (diaria, trissemanal, bissemanal, semanal, quinzenal)", str),
        ("diaria_em", "Coleta diária nos bairros com o nome", str),
        ("jornada_h", "Jornada por turno (h)", float),
        ("improdutivo_h", "Tempo fora do circuito por turno (h): garagem, descarga, refeição", float),
        ("velocidade_kmh", "Velocidade média coletando (km/h)", float),
        ("viagens", "Viagens ao destino por turno", int),
        ("t_viagem", "Carga por viagem (t)", float),
        ("t_mes", "Quantidade do edital (t/mês)", float),
        ("so_urbano", "Só área urbana (1 = sim)", int),
    ],
    "varricao": [
        ("equipes", "Equipes simultâneas", int),
        ("varredores", "Varredores (total)", int),
        ("km_mes", "Quantidade do edital (km/mês)", float),
        ("lados", "Sarjetas por via (2 = o km do edital é de sarjeta, os dois lados; 1 = km de via)", int),
        ("dias_mes", "Dias de trabalho por mês", int),
        ("dias_semana", "Dias de trabalho por semana", int),
        ("diaria_em", "Varrição diária nos bairros com o nome", str),
        ("frequencia", "Frequência nos demais bairros", str),
    ],
    "varricao_mec": [
        ("maquinas", "Varredeiras em operação", int),
        ("turno", "Turno", str),
        ("km_mes", "Quantidade do edital (km/mês)", float),
        ("lados", "Sarjetas por via (2 = o km do edital é de sarjeta, os dois lados; 1 = km de via)", int),
        ("dias_mes", "Dias de trabalho por mês", int),
    ],
    "zona": [
        ("equipes", "Equipes / veículos", int),
    ],
}
ROTULOS_TIPO = {"coleta": "Coleta", "varricao": "Varrição manual",
                "varricao_mec": "Varrição mecanizada", "zona": "Áreas (por equipe)"}


# ------------------------------------------------------------------ leitura do edital
def _paginas(pasta):
    out = []
    for arq in glob.glob(os.path.join(PA.contrato(pasta), "textos", "*.json")):
        try:
            d = json.load(open(arq, encoding="utf-8"))
        except Exception:
            continue
        pags = d.get("paginas") if isinstance(d, dict) else d
        if isinstance(pags, list):
            out += [p for p in pags if isinstance(p, str)]
    return out


_UNID = r"(toneladas?|ton|t|km\.?\s*eixo|km|m2|m²|unidades?|un|m[eê]s)"
_NUM = r"(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)"


def _num(s):
    return float(s.replace(".", "").replace(",", "."))


def quantidades_edital(pasta):
    """[(descrição, unidade, quantidade mensal)] das tabelas de quantitativos do edital."""
    out, vistos = [], set()
    pad = re.compile(r"^\s*\d{1,2}\s+(.{5,160}?)\s+" + _UNID + r"\s+" + _NUM + r"\b",
                     re.I | re.M)
    for pg in _paginas(pasta):
        for m in pad.finditer(pg):
            d, u, q = m.group(1).strip(), m.group(2), m.group(3)
            chave = (_sa(d), _sa(u))
            if chave in vistos:
                continue
            vistos.add(chave)
            out.append((d, u, _num(q)))
    return out


_PARADAS = {"de", "da", "do", "das", "dos", "e", "em", "a", "o", "para", "com", "por"}


def _palavras(s):
    return {w for w in re.findall(r"[a-z]+", _sa(s)) if w not in _PARADAS and len(w) > 2}


def quantidade(qtds, nome_servico, unidades):
    """Quantidade mensal do serviço (pelo nome mais parecido e a unidade esperada)."""
    alvo = _palavras(nome_servico)
    melhor, nota = None, 0.0
    for d, u, q in qtds:
        if not any(x in _sa(u) for x in unidades):
            continue
        p = _palavras(d)
        if not p or not alvo:
            continue
        j = len(p & alvo) / len(p | alvo)
        if j > nota:
            melhor, nota = q, j
    return melhor if nota >= 0.4 else None


def _numero_antes(texto, palavra):
    m = re.search(r"(\d+)\s*(?:\([^)]*\)\s*)?" + palavra, _sa(texto))
    return int(m.group(1)) if m else None


def _textos_servico(p, servico, chaves):
    s = next((x for x in p.get("servicos") or [] if x["codigo"] == servico), {})
    txt = [s.get("frequencia") or ""]
    for r in p.get("regras") or []:
        d = _sa(r.get("descricao"))
        if any(k in d for k in chaves):
            txt.append(r.get("descricao") or "")
    return txt


# ------------------------------------------------------------------ padrões por serviço
def tipo_servico(nome):
    """'coleta' | 'varricao_mec' | 'varricao' | 'zona' | None (não vira circuito)."""
    n = _sa(nome)
    if any(k in n for k in NAO_SETORIZA):
        return None
    if "varri" in n:
        return "varricao_mec" if "mecaniz" in n else "varricao"
    if "coleta" in n:
        return "coleta"
    if any(k in n for k in ("drenagem", "capina", "rocada", "raspagem", "bueiro")):
        return "zona"
    return None


NAO_SETORIZA = ("feira", "transbordo", "destinacao final", "ecoponto", "cemiter", "papeleira",
                "conteiner", "container", "cacamba", "servicos diversos", "unidade de",
                "praca", "parque", "animais", "saude", "dificil acesso", "demanda")


def padrao(p, servico, lote, pasta=None, qtds=None):
    """Parâmetros iniciais do serviço, lidos do edital. Devolve dict (com "tipo")."""
    s = next((x for x in p.get("servicos") or [] if x["codigo"] == servico), {})
    tipo = tipo_servico(s.get("nome"))
    if not tipo:
        return None
    if qtds is None:
        qtds = quantidades_edital(pasta) if pasta else []
    sigla = (s.get("sigla") or "").strip() or f"S{servico}"
    veic = EMP.veiculos_do_edital(p, servico, lote, sigla)
    vd = sum(1 for v in veic if v["turno"] != "Noturno")
    vn = len(veic) - vd
    domingo = any(r.get("domingo") for r in p.get("recursos") or []
                  if r.get("servico") == servico and r.get("categoria") == "equipamento")
    freq = s.get("frequencia") or ""
    nome = _sa(s.get("nome"))
    if tipo == "coleta":
        seletiva = "seletiv" in nome or "reciclav" in nome
        try:
            from . import territorio as TE
        except ImportError:
            import territorio as TE
        fpad, esp = TE.frequencia_padrao(freq)
        txt = " ".join(_textos_servico(p, servico, ["coleta"]))
        m = re.search(r"(\d+)\s*(?:\([^)]*\)\s*)?viagens", _sa(txt))
        viagens_dia = int(m.group(1)) if m else 2
        turnos = (1 if vd else 0) + (1 if vn else 0) or 1
        t_mes = quantidade(qtds, s.get("nome"), ("ton", "t")) or 0.0
        t_viagem = 3.0 if seletiva else 7.0
        # viagens por turno: o mínimo do edital ou o que a geração pede (t por veículo-turno)
        viagens = max(1, math.ceil(viagens_dia / turnos),
                      math.ceil(t_mes / 30 / max(1, vd + vn) / t_viagem - 0.05) if t_mes else 1)
        return {"tipo": "coleta", "veiculos_diurno": vd, "veiculos_noturno": vn,
                "dias_semana": 7 if domingo else 6,
                "frequencia": fpad or ("semanal" if seletiva else "trissemanal"),
                "diaria_em": ", ".join(k for k, v in esp.items() if v == "diaria"),
                "jornada_h": 7.33, "improdutivo_h": 2.0,
                "velocidade_kmh": 6.0 if seletiva else 5.0,
                "viagens": viagens,
                "t_viagem": t_viagem,
                "t_mes": t_mes,
                "so_urbano": 1 if seletiva else 0}
    if tipo == "varricao":
        txt = _textos_servico(p, servico, ["varricao manual", "varrição manual"])
        eq = next((n for n in (_numero_antes(t, "equipes") for t in txt) if n), None)
        varr = sum(int(r.get("diurno") or 0) + int(r.get("noturno") or 0)
                   for r in p.get("recursos") or []
                   if r.get("servico") == servico and r.get("categoria") == "pessoal"
                   and any(k in _sa(r.get("nome")) for k in ("varred", "gari")))
        if not eq:
            eq = max(1, round(varr / 8)) if varr else 1
        return {"tipo": "varricao", "equipes": eq, "varredores": varr or eq * 6,
                "km_mes": quantidade(qtds, s.get("nome"), ("km",)) or 0.0, "lados": 2,
                "dias_mes": 30 if domingo else 26, "dias_semana": 7 if domingo else 6,
                "diaria_em": "centro", "frequencia": "semanal"}
    if tipo == "varricao_mec":
        maq = len(veic) or (_numero_antes(" ".join(_textos_servico(
            p, servico, ["mecaniz"])), "varredeiras") or 1)
        continua = "continu" in _sa(freq) or "fins de semana" in _sa(freq) or domingo
        return {"tipo": "varricao_mec", "maquinas": maq,
                "turno": "Noturno" if (vn or "noturn" in _sa(freq)) else "Diurno",
                "km_mes": quantidade(qtds, s.get("nome"), ("km",)) or 0.0, "lados": 2,
                "dias_mes": 30 if continua else 26}
    return {"tipo": "zona", "equipes": len(veic) or 1}


def capacidade(par):
    """Capacidade de um circuito de coleta: (km, t)."""
    km = max(0.5, (float(par["jornada_h"]) - float(par["improdutivo_h"]))) * float(par["velocidade_kmh"])
    t = max(0.1, float(par["viagens"]) * float(par["t_viagem"]))
    return km, t


def resumo_parametros(par):
    """Linhas de texto que explicam a conta (vão para a tela e para a planilha)."""
    t = par.get("tipo")
    if t == "coleta":
        km, ton = capacidade(par)
        v = int(par["veiculos_diurno"]) + int(par["veiculos_noturno"])
        lin = [f"{v} veículos-turno por dia ({par['veiculos_diurno']} diurno + "
               f"{par['veiculos_noturno']} noturno), {par['dias_semana']} dias por semana.",
               f"Circuito: até {km:.1f} km ({float(par['jornada_h']) - float(par['improdutivo_h']):.1f} h "
               f"coletando × {par['velocidade_kmh']} km/h) e até {ton:.1f} t "
               f"({par['viagens']} viagem(ns) × {par['t_viagem']} t)."]
        if float(par.get("t_mes") or 0):
            lin.append(f"Geração: {float(par['t_mes']):,.0f} t/mês ≈ "
                       f"{float(par['t_mes']) / 30:,.1f} t/dia ≈ "
                       f"{float(par['t_mes']) / 30 / max(1, v):.1f} t por veículo-turno."
                       .replace(",", "."))
        return lin
    if t == "varricao":
        kd = float(par["km_mes"]) / max(1, int(par["dias_mes"]))
        ke = kd / max(1, int(par["equipes"]))
        dup = max(1, int(par["varredores"]) // max(1, int(par["equipes"])) // 2)
        la = _lados(par)
        kv = kd / max(1, int(par["varredores"]))
        lin = [f"{float(par['km_mes']):.0f} km/mês ÷ {par['dias_mes']} dias = {kd:.1f} km/dia.",
               f"{par['equipes']} equipes → {ke:.1f} km por equipe/dia; {dup} duplas por equipe "
               f"→ {ke / dup:.1f} km por dupla/dia ({kv:.2f} km por varredor).",
               (f"O km é de sarjeta (os 2 lados da rua): cada equipe varre {ke / la:.1f} km de rua "
                f"por dia e cada dupla anda {ke / dup / la:.1f} km de rua varrendo os dois lados."
                if la == 2 else
                f"O km é de rua: cada dupla anda {ke / dup:.1f} km de rua por dia.")]
        if kv > 3.0:
            lin.append(f"⚠ {kv:.1f} km por varredor/dia é muito para varrição a pé "
                       "(o comum é 1,5 a 2,5 km de sarjeta).")
        return lin
    if t == "varricao_mec":
        kd = float(par["km_mes"]) / max(1, int(par["dias_mes"]))
        km_m = kd / max(1, int(par["maquinas"]))
        return [f"{float(par['km_mes']):.0f} km/mês ÷ {par['dias_mes']} dias = {kd:.1f} km/dia; "
                f"{km_m:.1f} km por varredeira/turno ({par['turno']})"
                + (f", ou {km_m / 2:.1f} km de avenida (as 2 sarjetas)." if _lados(par) == 2 else ".")]
    return [f"{par.get('equipes')} área(s), uma por equipe."]


def _lados(par):
    try:
        return max(1, min(2, int(float(par.get("lados") or 2))))
    except (TypeError, ValueError):
        return 2


def converter(par):
    """Converte os valores digitados (texto) para o tipo de cada campo."""
    out = dict(par)
    for k, _, tp in CAMPOS.get(par.get("tipo"), []):
        if k in out:
            try:
                v = str(out[k]).replace(",", ".")
                out[k] = (int(float(v)) if tp is int else float(v)) if tp is not str else str(out[k])
            except ValueError:
                pass
    return out
