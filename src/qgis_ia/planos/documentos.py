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


def aviso_sem_texto(doc):
    """Texto de aviso se o PDF parece escaneado (sem texto)."""
    n = len(doc["paginas"])
    s = doc["paginas_sem_texto"]
    if n and s / n > 0.5:
        return (f"{doc['nome']}: {s} de {n} páginas sem texto — parece escaneado. "
                "Use um PDF pesquisável (com OCR) para a IA conseguir ler.")
    return ""
