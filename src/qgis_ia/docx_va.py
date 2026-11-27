# -*- coding: utf-8 -*-
"""Documento .docx no padrão visual Valor Ambiental / CCIO (o mesmo do DocumentoPadrãoCCIO,
que gera PDF): faixa verde no alto, logo e três linhas de cabeçalho em verde, rodapé com
descrição e nº da página, títulos verdes em Arial, tabelas com cabeçalho verde, linhas
zebradas e linha de total destacada, quadros de destaque.

Entrada: uma especificação igual à da skill (dict):
    {"saida": "...docx", "orientacao": "retrato"|"paisagem",
     "cabecalho": {"linha1", "linha2", "linha3"}, "rodape": "...",
     "metadados": {"titulo", "autor"}, "logo": "caminho.png" (opcional),
     "blocos": [{"tipo": "titulo"|"subtitulo"|"secao"|"subsecao"|"paragrafo"|"lista"|
                 "tabela"|"quadro"|"codigo"|"anexo"|"imagem"|"espaco"|"quebra", ...}]}
Marcação nos textos: **negrito**, *itálico*, `código`. Trechos "[A DEFINIR …]" saem em
vermelho (o que falta preencher).

Sem dependências além da biblioteca padrão (o .docx é montado direto em XML).
"""
import datetime as _dt
import os
import re
import struct
import zipfile
from xml.sax.saxutils import escape

VERDE = "1F5434"
ZEBRA = "F1F5F2"
TOTAL = "DCEBE0"
CINZA = "555555"
VERMELHO = "C00000"
FONTE = "Arial"
CM = 567                      # twips por cm
EMU_CM = 360000
QUADROS = {"verde": ("E8F5E9", "81C784"), "amarelo": ("FFF8E1", "FFB300"),
           "cinza": ("F2F4F7", "C9D1DB")}

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')


def logo_padrao():
    """Logo da empresa guardado fora do Git (~/.app_qgis/logo_empresa.png), se houver."""
    base = os.environ.get("APP_QGIS_EMPRESA")
    d = os.path.dirname(base) if base else os.path.join(os.path.expanduser("~"), ".app_qgis")
    arq = os.path.join(d, "logo_empresa.png")
    return arq if os.path.exists(arq) else None


def _tam_png(caminho):
    with open(caminho, "rb") as f:
        cab = f.read(24)
    if cab[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", cab[16:24])
    return (100, 100)


# ------------------------------------------------------------------ texto → runs
_MARCA = re.compile(r"(\*\*.+?\*\*|`.+?`|(?<![\w*])\*(?!\s).+?(?<!\s)\*(?![\w*])|\[A DEFINIR[^\]]*\])")


def _run(t, b=False, i=False, cor=None, sz=None, mono=False, fonte=None):
    rpr = ""
    f = "Courier New" if mono else fonte
    if f:
        rpr += f'<w:rFonts w:ascii="{f}" w:hAnsi="{f}" w:cs="{f}"/>'
    if b:
        rpr += "<w:b/>"
    if i:
        rpr += "<w:i/>"
    if cor:
        rpr += f'<w:color w:val="{cor}"/>'
    if sz:
        rpr += f'<w:sz w:val="{int(sz * 2)}"/><w:szCs w:val="{int(sz * 2)}"/>'
    partes = str(t).split("\n")
    xml = ""
    for k, p in enumerate(partes):
        if k:
            xml += "<w:br/>"
        xml += f'<w:t xml:space="preserve">{escape(p)}</w:t>'
    return f"<w:r>{'<w:rPr>' + rpr + '</w:rPr>' if rpr else ''}{xml}</w:r>"


def runs(texto, b=False, i=False, cor=None, sz=None):
    out = []
    for pedaco in _MARCA.split(str(texto if texto is not None else "")):
        if not pedaco:
            continue
        if pedaco.startswith("[A DEFINIR"):
            out.append(_run(pedaco, True, i, VERMELHO, sz))
        elif pedaco.startswith("**") and pedaco.endswith("**") and len(pedaco) > 4:
            out.append(_run(pedaco[2:-2], True, i, cor, sz))
        elif pedaco.startswith("`") and pedaco.endswith("`") and len(pedaco) > 2:
            out.append(_run(pedaco[1:-1], b, i, cor, sz, mono=True))
        elif pedaco.startswith("*") and pedaco.endswith("*") and len(pedaco) > 2:
            out.append(_run(pedaco[1:-1], b, True, cor, sz))
        else:
            out.append(_run(pedaco, b, i, cor, sz))
    return "".join(out)


def _p(conteudo, estilo=None, ppr_extra=""):
    ppr = (f'<w:pStyle w:val="{estilo}"/>' if estilo else "") + ppr_extra
    return f"<w:p>{'<w:pPr>' + ppr + '</w:pPr>' if ppr else ''}{conteudo}</w:p>"


# ------------------------------------------------------------------ documento
class _Doc:
    def __init__(self, spec):
        self.spec = spec
        self.base = spec.get("_base") or os.path.dirname(os.path.abspath(spec["saida"]))
        self.paisagem = spec.get("orientacao") == "paisagem"
        self.pw, self.ph = (16838, 11906) if self.paisagem else (11906, 16838)
        self.mx = int(1.9 * CM)
        self.largura = self.pw - 2 * self.mx               # twips úteis
        self.midias = []                                    # (nome, caminho)
        self.rels_doc = []                                  # (id, tipo, alvo)
        self.n_img = 0

    # ------------------------------------------------ imagens
    def _midia(self, caminho, rels):
        nome = f"imagem{len(self.midias) + 1}.png"
        self.midias.append((nome, caminho))
        rid = f"rId{100 + len(self.midias)}"
        rels.append((rid, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
                     f"media/{nome}"))
        return rid

    def desenho(self, caminho, larg_cm, alt_cm, rels):
        rid = self._midia(caminho, rels)
        self.n_img += 1
        cx, cy = int(larg_cm * EMU_CM), int(alt_cm * EMU_CM)
        return (f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
                f'<wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{self.n_img}" name="Imagem {self.n_img}"/>'
                '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
                f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{self.n_img}" name="{os.path.basename(caminho)}"/>'
                '<pic:cNvPicPr/></pic:nvPicPr>'
                f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
                f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
                '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
                '</a:graphicData></a:graphic></wp:inline></w:drawing></w:r>')

    # ------------------------------------------------ blocos
    def tabela(self, b):
        cols = b["colunas"]
        n = len(cols)
        direita = set(b.get("direita") or [])
        if b.get("larguras"):
            fix = [int(x * CM) if x else None for x in b["larguras"]]
            livre = self.largura - sum(x for x in fix if x)
            nl = sum(1 for x in fix if not x)
            larg = [x if x else max(CM, livre // max(1, nl)) for x in fix]
        else:
            larg = [self.largura // n] * n
        junto = b.get("manter_junto", len(b["linhas"]) <= 18)

        def cel(v, k, fundo=None, negrito=False, cor=None, borda_cima=False, prox=True):
            tcpr = f'<w:tcW w:w="{larg[k]}" w:type="dxa"/>'
            if fundo:
                tcpr += f'<w:shd w:val="clear" w:color="auto" w:fill="{fundo}"/>'
            if borda_cima:
                tcpr += f'<w:tcBorders><w:top w:val="single" w:sz="8" w:color="{VERDE}"/></w:tcBorders>'
            jc = '<w:jc w:val="right"/>' if k in direita else ""
            kn = "<w:keepNext/>" if (junto and prox) else ""
            return (f"<w:tc><w:tcPr>{tcpr}</w:tcPr><w:p><w:pPr><w:pStyle w:val=\"TabelaTexto\"/>"
                    f"{kn}{jc}</w:pPr>{runs('' if v is None else v, negrito, cor=cor)}</w:p></w:tc>")

        grid = "".join(f'<w:gridCol w:w="{x}"/>' for x in larg)
        xml = ('<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblLayout w:type="fixed"/>'
               '<w:tblBorders><w:top w:val="nil"/><w:left w:val="nil"/><w:bottom w:val="nil"/>'
               '<w:right w:val="nil"/><w:insideH w:val="nil"/><w:insideV w:val="nil"/></w:tblBorders>'
               '<w:tblCellMar><w:top w:w="90" w:type="dxa"/><w:left w:w="120" w:type="dxa"/>'
               '<w:bottom w:w="90" w:type="dxa"/><w:right w:w="120" w:type="dxa"/></w:tblCellMar>'
               f'</w:tblPr><w:tblGrid>{grid}</w:tblGrid>')
        xml += ('<w:tr><w:trPr><w:tblHeader/><w:cantSplit/></w:trPr>'
                + "".join(cel(c, k, VERDE, True, "FFFFFF") for k, c in enumerate(cols)) + "</w:tr>")
        corpo = b["linhas"]
        for r, row in enumerate(corpo):
            tot = bool(b.get("total")) and r == len(corpo) - 1
            fundo = TOTAL if tot else (ZEBRA if r % 2 else None)
            ult = r == len(corpo) - 1
            xml += ("<w:tr><w:trPr><w:cantSplit/></w:trPr>"
                    + "".join(cel(row[k] if k < len(row) else "", k, fundo, tot, None, tot, not ult)
                              for k in range(n)) + "</w:tr>")
        return xml + "</w:tbl>"

    def lista(self, b):
        out = []
        for k, it in enumerate(b["itens"], 1):
            texto, sub = (it, []) if isinstance(it, str) else (it["texto"], it.get("subitens") or [])
            marca = f"{k}." if b.get("numerada") else "•"
            out.append(_p(_run(marca + "\t") + runs(texto), "Lista"))
            for si in sub:
                out.append(_p(_run("–\t") + runs(si), "Lista2"))
        return "".join(out)

    def quadro(self, b):
        fundo, borda = QUADROS.get(b.get("cor") or "verde", QUADROS["verde"])
        bd = "".join(f'<w:{x} w:val="single" w:sz="5" w:space="6" w:color="{borda}"/>'
                     for x in ("top", "left", "bottom", "right"))
        ppr = (f'<w:pBdr>{bd}</w:pBdr><w:shd w:val="clear" w:color="auto" w:fill="{fundo}"/>'
               '<w:spacing w:before="120" w:after="240"/><w:ind w:left="140" w:right="140"/>')
        return _p(runs(b["texto"]), None, ppr)

    def imagem(self, b):
        arq = b["arquivo"] if os.path.isabs(b["arquivo"]) else os.path.join(self.base, b["arquivo"])
        w, h = _tam_png(arq)
        lw = self.largura / CM * float(b.get("largura") or 1.0)
        lh = lw * h / max(1, w)
        hmax = float(b.get("altura_max_cm") or (self.ph / CM - 9))
        if lh > hmax:
            lw, lh = hmax * w / max(1, h), hmax
        xml = _p(self.desenho(arq, lw, lh, self.rels_doc), None,
                 '<w:keepNext/><w:jc w:val="center"/>')
        if b.get("legenda"):
            xml += _p(runs(b["legenda"]), "Legenda")
        return xml

    def corpo(self):
        out = []
        for b in self.spec["blocos"]:
            tp = b["tipo"]
            if tp in ("titulo", "subtitulo", "secao", "subsecao"):
                est = {"titulo": "Titulo", "subtitulo": "Subtitulo", "secao": "Heading1",
                       "subsecao": "Heading2"}[tp]
                out.append(_p(runs(b["texto"]), est))
            elif tp == "anexo":
                extra = '<w:pageBreakBefore/>' if b.get("nova_pagina", True) else ""
                out.append(_p(runs(b["texto"]), "Anexo", extra))
            elif tp == "paragrafo":
                out.append(_p(runs(b["texto"])))
            elif tp == "lista":
                out.append(self.lista(b))
            elif tp == "tabela":
                if b.get("introducao"):
                    out.append(_p(runs(b["introducao"]), None, "<w:keepNext/>"))
                out.append(self.tabela(b))
                if b.get("nota"):
                    out.append(_p(runs(b["nota"]), "Legenda"))
                else:
                    out.append(_p("", None, '<w:spacing w:after="60"/>'))
            elif tp == "quadro":
                out.append(self.quadro(b))
            elif tp == "codigo":
                out.append(_p(_run(b["texto"], mono=True), "Codigo"))
            elif tp == "imagem":
                out.append(self.imagem(b))
            elif tp == "espaco":
                out.append(_p("", None, f'<w:spacing w:after="{int(float(b.get("cm", 0.5)) * CM)}"/>'))
            elif tp == "quebra":
                out.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
            else:
                raise ValueError(f"Tipo de bloco desconhecido: {tp}")
        return "".join(out)

    # ------------------------------------------------ cabeçalho / rodapé
    def cabecalho(self, rels):
        cab = self.spec.get("cabecalho") or {}
        logo = self.spec.get("logo") or logo_padrao()
        faixa = _p("", None, f'<w:pBdr><w:top w:val="single" w:sz="36" w:space="1" w:color="{VERDE}"/>'
                             '</w:pBdr><w:spacing w:before="0" w:after="120" w:line="120" w:lineRule="exact"/>')
        c1 = int(3.0 * CM)
        c2 = self.largura - c1
        if logo and os.path.exists(logo):
            w, h = _tam_png(logo)
            alt = 2.07
            larg = min(2.45, alt * w / max(1, h))
            img = _p(self.desenho(logo, larg, larg * h / max(1, w), rels), None,
                     '<w:spacing w:after="0"/>')
        else:
            img = _p("")
        linhas = (_p(_run(cab.get("linha1", ""), True, cor=VERDE, sz=10.5, fonte=FONTE), None,
                     '<w:spacing w:after="40"/>')
                  + _p(_run(cab.get("linha2", ""), True, cor=VERDE, sz=12, fonte=FONTE), None,
                       '<w:spacing w:after="40"/>')
                  + _p(_run(cab.get("linha3", ""), cor=VERDE, sz=8.5, fonte=FONTE), None,
                       '<w:spacing w:after="0"/>'))
        tab = ('<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblLayout w:type="fixed"/>'
               '<w:tblBorders><w:top w:val="nil"/><w:left w:val="nil"/><w:bottom w:val="nil"/>'
               '<w:right w:val="nil"/><w:insideH w:val="nil"/><w:insideV w:val="nil"/></w:tblBorders>'
               f'</w:tblPr><w:tblGrid><w:gridCol w:w="{c1}"/><w:gridCol w:w="{c2}"/></w:tblGrid><w:tr>'
               f'<w:tc><w:tcPr><w:tcW w:w="{c1}" w:type="dxa"/><w:vAlign w:val="center"/></w:tcPr>{img}</w:tc>'
               f'<w:tc><w:tcPr><w:tcW w:w="{c2}" w:type="dxa"/><w:vAlign w:val="center"/></w:tcPr>{linhas}</w:tc>'
               '</w:tr></w:tbl>')
        fim = _p("", None, '<w:spacing w:after="0" w:line="120" w:lineRule="exact"/>')
        return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:hdr {NS}>{faixa}{tab}{fim}</w:hdr>'

    def rodape(self):
        rod = self.spec.get("rodape") or ""
        ppr = (f'<w:pBdr><w:top w:val="single" w:sz="4" w:space="6" w:color="CCCCCC"/></w:pBdr>'
               f'<w:tabs><w:tab w:val="right" w:pos="{self.largura}"/></w:tabs><w:spacing w:after="0"/>')
        rpr = f'<w:rPr><w:color w:val="{CINZA}"/><w:sz w:val="15"/></w:rPr>'
        campo = (f'<w:r>{rpr}<w:fldChar w:fldCharType="begin"/></w:r>'
                 f'<w:r>{rpr}<w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
                 f'<w:r>{rpr}<w:fldChar w:fldCharType="separate"/></w:r>'
                 f'<w:r>{rpr}<w:t>1</w:t></w:r><w:r>{rpr}<w:fldChar w:fldCharType="end"/></w:r>')
        par = _p(_run(rod, cor=CINZA, sz=7.5) + f"<w:r>{rpr}<w:tab/></w:r>" + campo, None, ppr)
        return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr {NS}>{par}</w:ftr>'

    # ------------------------------------------------ montar
    def gravar(self):
        rels_hdr = []
        corpo = self.corpo()
        hdr = self.cabecalho(rels_hdr)
        ftr = self.rodape()
        mt = int(3.6 * CM)
        orient = ' w:orient="landscape"' if self.paisagem else ""
        sect = (f'<w:sectPr><w:headerReference w:type="default" r:id="rIdH1"/>'
                f'<w:footerReference w:type="default" r:id="rIdF1"/>'
                f'<w:pgSz w:w="{self.pw}" w:h="{self.ph}"{orient}/>'
                f'<w:pgMar w:top="{mt}" w:right="{self.mx}" w:bottom="{int(1.9 * CM)}" '
                f'w:left="{self.mx}" w:header="{int(0.35 * CM)}" w:footer="{int(0.8 * CM)}" w:gutter="0"/>'
                '</w:sectPr>')
        doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {NS}>'
               f'<w:body>{corpo}{sect}</w:body></w:document>')
        tipos = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                 '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                 '<Default Extension="xml" ContentType="application/xml"/>'
                 '<Default Extension="png" ContentType="image/png"/>'
                 '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                 '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
                 '<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>'
                 '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
                 '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
                 '</Types>')
        rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                '</Relationships>')

        def rels_xml(lst):
            return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    + "".join(f'<Relationship Id="{i}" Type="{t}" Target="{a}"/>' for i, t, a in lst)
                    + "</Relationships>")
        R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
        doc_rels = [("rIdS", R + "styles", "styles.xml"), ("rIdH1", R + "header", "header1.xml"),
                    ("rIdF1", R + "footer", "footer1.xml")] + self.rels_doc
        hdr_rels = [(i, t, a) for i, t, a in rels_hdr]
        meta = self.spec.get("metadados") or {}
        agora = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
                'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                f'<dc:title>{escape(meta.get("titulo") or (self.spec.get("cabecalho") or {}).get("linha2", ""))}</dc:title>'
                f'<dc:creator>{escape(meta.get("autor") or "")}</dc:creator>'
                f'<dcterms:created xsi:type="dcterms:W3CDTF">{agora}</dcterms:created>'
                '</cp:coreProperties>')
        destino = self.spec["saida"]
        os.makedirs(os.path.dirname(os.path.abspath(destino)), exist_ok=True)
        with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", tipos)
            z.writestr("_rels/.rels", rels)
            z.writestr("docProps/core.xml", core)
            z.writestr("word/document.xml", doc)
            z.writestr("word/styles.xml", _estilos())
            z.writestr("word/header1.xml", hdr)
            z.writestr("word/footer1.xml", ftr)
            z.writestr("word/_rels/document.xml.rels", rels_xml(doc_rels))
            z.writestr("word/_rels/header1.xml.rels", rels_xml(hdr_rels))
            for nome, caminho in self.midias:
                z.write(caminho, f"word/media/{nome}")
        return destino


def _estilos():
    rf = f'<w:rFonts w:ascii="{FONTE}" w:hAnsi="{FONTE}" w:cs="{FONTE}" w:eastAsia="{FONTE}"/>'

    def est(sid, nome, ppr="", rpr="", tipo="paragraph", base="Normal", prox=None, extra=""):
        return (f'<w:style w:type="{tipo}" w:styleId="{sid}"{" w:default=\"1\"" if sid == "Normal" else ""}>'
                f'<w:name w:val="{nome}"/>' + (f'<w:basedOn w:val="{base}"/>' if base else "")
                + (f'<w:next w:val="{prox}"/>' if prox else "") + extra
                + (f"<w:pPr>{ppr}</w:pPr>" if ppr else "") + (f"<w:rPr>{rpr}</w:rPr>" if rpr else "")
                + "</w:style>")
    verde = f'<w:color w:val="{VERDE}"/>'
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:docDefaults><w:rPrDefault><w:rPr>{rf}<w:sz w:val="20"/><w:szCs w:val="20"/>'
            '<w:lang w:val="pt-BR"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr>'
            '<w:spacing w:after="120" w:line="280" w:lineRule="exact"/></w:pPr></w:pPrDefault></w:docDefaults>'
            + est("Normal", "Normal", base=None)
            + est("Titulo", "Title", '<w:keepNext/><w:spacing w:after="120" w:line="500" w:lineRule="exact"/>',
                  f'<w:b/>{verde}<w:sz w:val="40"/><w:szCs w:val="40"/>', prox="Normal")
            + est("Subtitulo", "Subtitle", '<w:keepNext/><w:spacing w:after="200" w:line="340" w:lineRule="exact"/>',
                  f'<w:b/>{verde}<w:sz w:val="26"/><w:szCs w:val="26"/>', prox="Normal")
            + est("Heading1", "heading 1", '<w:keepNext/><w:spacing w:before="280" w:after="160" '
                  'w:line="340" w:lineRule="exact"/><w:outlineLvl w:val="0"/>',
                  f'<w:b/>{verde}<w:sz w:val="26"/><w:szCs w:val="26"/>', prox="Normal")
            + est("Heading2", "heading 2", '<w:keepNext/><w:spacing w:before="160" w:after="100" '
                  'w:line="300" w:lineRule="exact"/><w:outlineLvl w:val="1"/>',
                  '<w:b/><w:sz w:val="22"/><w:szCs w:val="22"/>', prox="Normal")
            + est("Anexo", "Anexo", '<w:keepNext/><w:spacing w:after="200" w:line="460" w:lineRule="exact"/>'
                  '<w:outlineLvl w:val="0"/>', f'<w:b/>{verde}<w:sz w:val="36"/><w:szCs w:val="36"/>',
                  prox="Normal")
            + est("Lista", "Lista VA", '<w:tabs><w:tab w:val="left" w:pos="280"/></w:tabs>'
                  '<w:spacing w:after="80"/><w:ind w:left="280" w:hanging="220"/>')
            + est("Lista2", "Lista VA 2", '<w:tabs><w:tab w:val="left" w:pos="600"/></w:tabs>'
                  '<w:spacing w:after="60"/><w:ind w:left="600" w:hanging="220"/>')
            + est("Legenda", "Legenda VA", '<w:spacing w:before="60" w:after="200" w:line="220" w:lineRule="exact"/>',
                  f'<w:i/><w:color w:val="{CINZA}"/><w:sz w:val="17"/><w:szCs w:val="17"/>')
            + est("TabelaTexto", "Tabela VA", '<w:spacing w:after="0" w:line="220" w:lineRule="exact"/>',
                  '<w:sz w:val="17"/><w:szCs w:val="17"/>')
            + est("Codigo", "Código VA", '<w:pBdr><w:top w:val="single" w:sz="4" w:space="4" w:color="C9D1DB"/>'
                  '<w:left w:val="single" w:sz="4" w:space="4" w:color="C9D1DB"/>'
                  '<w:bottom w:val="single" w:sz="4" w:space="4" w:color="C9D1DB"/>'
                  '<w:right w:val="single" w:sz="4" w:space="4" w:color="C9D1DB"/></w:pBdr>'
                  f'<w:shd w:val="clear" w:color="auto" w:fill="{ZEBRA}"/><w:spacing w:before="80" w:after="200" '
                  'w:line="200" w:lineRule="exact"/><w:ind w:left="120" w:right="120"/>',
                  '<w:sz w:val="15"/><w:szCs w:val="15"/>')
            + "</w:styles>")


def gerar(spec):
    """Grava o .docx descrito em spec["saida"] e devolve o caminho."""
    return _Doc(spec).gravar()
