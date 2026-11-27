# -*- coding: utf-8 -*-
"""OCR das páginas escaneadas pelo Claude (conta claude.ai da máquina, pelo Claude Code).

Cada página sem texto do PDF vira imagem (GDAL/Poppler, já no QGIS). O Claude lê as imagens
e devolve o texto, que entra no cache do documento (pasta do contrato/textos/): daí em
diante o documento é lido normalmente (Criar Todos, Ler com IA, buscar…).

Nada para instalar. Usa o limite da assinatura (≈ 10 páginas por chamada).
Sem QGIS: só osgeo e subprocess.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile

from . import documentos

POR_CHAMADA = 8
DPI = 150
MODELO = "sonnet"
TEMPO_LIMITE = 900          # segundos por chamada

PEDIDO = """Transcreva o texto das imagens de páginas de documento listadas abaixo (estão \
nesta pasta; abra cada uma com a ferramenta Read). São páginas escaneadas de um edital de \
licitação em português.

Regras:
- Transcreva fielmente, na ordem de leitura, sem resumir nem comentar.
- Tabelas: uma linha por linha da tabela, células separadas por " | ".
- Campos em branco de formulário: escreva "____".
- Antes de cada página escreva exatamente a linha === PÁGINA <n> === (n = número indicado).
- Responda só com as transcrições.

Páginas:
"""


def paginas_sem_texto(doc, minimo=30):
    """Números (1, 2…) das páginas sem texto do documento lido."""
    return [i + 1 for i, p in enumerate(doc["paginas"]) if len(p.strip()) < minimo]


def imagem_da_pagina(pdf, pagina, destino, dpi=DPI):
    """Grava a página (1, 2…) do PDF como PNG."""
    from osgeo import gdal
    with gdal.ExceptionMgr(useExceptions=True):
        ds = gdal.OpenEx(pdf, gdal.OF_RASTER, open_options=[f"DPI={dpi}"])
        subs = ds.GetMetadata("SUBDATASETS") or {}
        if subs:
            ds = gdal.OpenEx(subs[f"SUBDATASET_{pagina}_NAME"], gdal.OF_RASTER,
                             open_options=[f"DPI={dpi}"])
        elif pagina != 1:
            raise ValueError(f"{os.path.basename(pdf)} tem 1 página só.")
        gdal.Translate(destino, ds, format="PNG")
    return destino


def argumentos(nomes, modelo=MODELO):
    lista = "\n".join(f"- {n} (página {p})" for n, p in nomes)
    return ["-p", PEDIDO + lista, "--model", modelo, "--tools", "Read",
            "--allowedTools", "Read", "--strict-mcp-config", "--output-format", "json"]


def executar_claude(args, pasta, exe=None, timeout=TEMPO_LIMITE):
    """Roda o Claude Code na pasta das imagens. Devolve o texto da resposta."""
    from .leitor_claude import achar_claude, ambiente
    from .importacao import texto_resposta_claude
    exe = exe or achar_claude()
    if not exe:
        raise RuntimeError("Claude Code não encontrado (veja Configurar IA).")
    cmd = [exe] + args
    if exe.lower().endswith((".cmd", ".bat")):
        cmd = ["cmd", "/c"] + cmd
    r = subprocess.run(cmd, cwd=pasta, env=ambiente(), capture_output=True, timeout=timeout,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    ok, texto = texto_resposta_claude(r.stdout.decode("utf-8", "replace"))
    if not ok:
        raise RuntimeError(texto or r.stderr.decode("utf-8", "replace")[-600:]
                           or "O Claude parou sem resposta.")
    return texto


def separar(texto):
    """'=== PÁGINA n ===' → {n: texto}."""
    partes = re.split(r"^\s*=+\s*P[ÁA]GINA\s+(\d+)\s*=+\s*$", texto, flags=re.MULTILINE | re.I)
    out = {}
    for i in range(1, len(partes) - 1, 2):
        out[int(partes[i])] = partes[i + 1].strip()
    return out


def ocr_documento(caminho, pasta_cache, paginas=None, progresso=None, cancelado=None,
                  executar=None):
    """Lê com o Claude as páginas sem texto do PDF e grava o texto no cache do documento.
    Devolve {"documento", "paginas_lidas", "faltaram"}."""
    executar = executar or executar_claude
    doc = documentos.ler(caminho, pasta_cache)
    if not caminho.lower().endswith(".pdf"):
        return {"documento": doc["nome"], "paginas_lidas": 0, "faltaram": []}
    alvo = paginas or paginas_sem_texto(doc)
    lidas, faltaram = {}, []
    tmp = tempfile.mkdtemp(prefix="qgisia_ocr_")
    try:
        for k in range(0, len(alvo), POR_CHAMADA):
            if cancelado and cancelado():
                faltaram += alvo[k:]
                break
            lote = alvo[k:k + POR_CHAMADA]
            if progresso:
                progresso(f"{doc['nome']}: lendo as páginas {lote[0]}–{lote[-1]} com o "
                          f"Claude ({k + len(lote)}/{len(alvo)})…")
            nomes = []
            for pg in lote:
                n = f"pagina_{pg:04d}.png"
                imagem_da_pagina(caminho, pg, os.path.join(tmp, n))
                nomes.append((n, pg))
            try:
                res = separar(executar(argumentos(nomes), tmp))
            except Exception:
                faltaram += lote
                continue
            for pg in lote:
                if res.get(pg):
                    lidas[pg] = res[pg]
                else:
                    faltaram.append(pg)
            for n, _ in nomes:
                os.remove(os.path.join(tmp, n))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if lidas:
        for pg, txt in lidas.items():
            doc["paginas"][pg - 1] = txt
        doc["chars"] = sum(len(p) for p in doc["paginas"])
        doc["paginas_sem_texto"] = sum(1 for p in doc["paginas"] if len(p.strip()) < 30)
        doc["ocr"] = sorted(set(doc.get("ocr") or []) | set(lidas))
        if pasta_cache:
            os.makedirs(pasta_cache, exist_ok=True)
            arq = os.path.join(pasta_cache, documentos._chave(caminho) + ".json")
            with open(arq, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False)
    return {"documento": doc["nome"], "paginas_lidas": len(lidas), "faltaram": faltaram,
            "doc": doc}
