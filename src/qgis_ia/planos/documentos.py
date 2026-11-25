# -*- coding: utf-8 -*-
"""Leitura do texto dos documentos do contrato (PDF, DOCX, TXT), página a página.

O texto extraído fica em cache (pasta do contrato/textos/) para não reler o PDF a cada vez.
Sem QGIS: pode ser testado sozinho.
"""
import hashlib
import json
import os
import re
import zipfile

EXTENSOES = (".pdf", ".docx", ".txt")
CHARS_POR_TOKEN = 3.6       # média medida nos PDFs do edital SLU-DF
PAGINAS_DOCX = 3000         # caracteres por "página" ao fatiar .docx/.txt


def _chave(caminho):
    st = os.stat(caminho)
    base = f"{os.path.abspath(caminho)}|{st.st_size}|{int(st.st_mtime)}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def _paginas_pdf(caminho):
    from pypdf import PdfReader
    r = PdfReader(caminho)
    out = []
    for pg in r.pages:
        try:
            out.append(pg.extract_text() or "")
        except Exception:
            out.append("")
    return out


def _fatiar(texto):
    paginas, atual = [], ""
    for par in texto.split("\n"):
        if len(atual) + len(par) > PAGINAS_DOCX and atual:
            paginas.append(atual)
            atual = ""
        atual += par + "\n"
    if atual.strip():
        paginas.append(atual)
    return paginas or [""]


def _paginas_docx(caminho):
    with zipfile.ZipFile(caminho) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    texto = re.sub(r"<[^>]+>", "", xml)
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'")):
        texto = texto.replace(a, b)
    return _fatiar(texto)


def _paginas_txt(caminho):
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            with open(caminho, encoding=enc) as f:
                return _fatiar(f.read())
        except UnicodeDecodeError:
            continue
    return [""]


def ler(caminho, pasta_cache=None):
    """Devolve {"nome", "caminho", "paginas": [texto...], "chars", "paginas_sem_texto"}."""
    ext = os.path.splitext(caminho)[1].lower()
    if ext not in EXTENSOES:
        raise ValueError(f"Formato não suportado: {ext} (use PDF, DOCX ou TXT)")
    cache = None
    if pasta_cache:
        os.makedirs(pasta_cache, exist_ok=True)
        cache = os.path.join(pasta_cache, _chave(caminho) + ".json")
        if os.path.exists(cache):
            with open(cache, encoding="utf-8") as f:
                return json.load(f)
    if ext == ".pdf":
        paginas = _paginas_pdf(caminho)
    elif ext == ".docx":
        paginas = _paginas_docx(caminho)
    else:
        paginas = _paginas_txt(caminho)
    doc = {
        "nome": os.path.splitext(os.path.basename(caminho))[0],
        "caminho": os.path.abspath(caminho),
        "paginas": paginas,
        "chars": sum(len(p) for p in paginas),
        "paginas_sem_texto": sum(1 for p in paginas if len(p.strip()) < 30),
    }
    if cache:
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
    return doc


def tokens_estimados(docs):
    return int(sum(d["chars"] for d in docs) / CHARS_POR_TOKEN)


def texto_para_ia(docs):
    """Junta os documentos com marcadores de documento e página, para a IA citar a fonte."""
    partes = []
    for d in docs:
        partes.append(f"<documento nome=\"{d['nome']}\" paginas=\"{len(d['paginas'])}\">")
        for i, pg in enumerate(d["paginas"], 1):
            pg = re.sub(r"[ \t]+", " ", pg).strip()
            if pg:
                partes.append(f"[pág. {i}]\n{pg}")
        partes.append("</documento>")
    return "\n".join(partes)


_TITULO = re.compile(
    r"^\s*((\d{1,2}(\.\d{1,2}){0,3}[\.\)\-–]?\s+\S)|(anexo|cap[ií]tulo|se[cç][aã]o|t[ií]tulo|"
    r"tabela|quadro|figura|item)\b)", re.IGNORECASE)


def _eh_titulo(linha):
    s = linha.strip()
    if not 4 <= len(s) <= 110:
        return False
    if _TITULO.match(s):
        return True
    letras = [c for c in s if c.isalpha()]
    return len(letras) >= 6 and sum(c.isupper() for c in letras) / len(letras) > 0.8


def indice(doc, max_por_pagina=6, max_chars=40_000):
    """Títulos/itens numerados por página: [{"pagina": n, "linhas": [...]}]."""
    out, total = [], 0
    for i, pg in enumerate(doc["paginas"], 1):
        linhas = [ln.strip()[:110] for ln in pg.splitlines() if _eh_titulo(ln)][:max_por_pagina]
        if not linhas:
            continue
        total += sum(len(x) for x in linhas)
        if total > max_chars:
            out.append({"pagina": i, "linhas": ["(índice cortado: use planos_buscar)"]})
            break
        out.append({"pagina": i, "linhas": linhas})
    return out


def _sem_acento(s):
    import unicodedata
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def buscar(docs, termos, contexto=160, maximo=40):
    """Ocorrências dos termos ('|' = alternativas), sem diferenciar acento e maiúscula."""
    alts = [_sem_acento(t.strip()) for t in termos.split("|") if t.strip()]
    if not alts:
        return []
    padrao = re.compile("|".join(re.escape(a) for a in alts))
    achados = []
    for d in docs:
        for i, pg in enumerate(d["paginas"], 1):
            # busca no texto sem acento, mas devolve o trecho original (mapa de posições)
            plano, mapa = [], []
            for j, ch in enumerate(pg):
                n = _sem_acento(ch)
                plano.append(n)
                mapa.extend([j] * len(n))
            plano = "".join(plano)
            mapa.append(len(pg))
            for m in padrao.finditer(plano):
                a = max(0, mapa[m.start()] - contexto)
                b = min(len(pg), mapa[m.end()] + contexto)
                trecho = re.sub(r"\s+", " ", pg[a:b]).strip()
                achados.append({"documento": d["nome"], "pagina": i, "trecho": trecho})
                if len(achados) >= maximo:
                    return achados
    return achados


def ler_paginas(doc, de, ate, maximo=30):
    n = len(doc["paginas"])
    de = max(1, int(de))
    ate = min(n, int(ate), de + maximo - 1)
    if de > n:
        raise ValueError(f"{doc['nome']} tem {n} páginas")
    partes = [f"[pág. {i}]\n{doc['paginas'][i - 1].strip()}" for i in range(de, ate + 1)]
    return {"documento": doc["nome"], "de": de, "ate": ate, "total_paginas": n,
            "texto": "\n\n".join(partes)}


def aviso_sem_texto(doc):
    """Texto de aviso se o PDF parece escaneado (sem texto)."""
    n = len(doc["paginas"])
    s = doc["paginas_sem_texto"]
    if n and s / n > 0.5:
        return (f"{doc['nome']}: {s} de {n} páginas sem texto — parece escaneado. "
                "Use um PDF pesquisável (com OCR) para a IA conseguir ler.")
    return ""
