# -*- coding: utf-8 -*-
"""Ações: layouts de impressão e exportação de mapas."""
from qgis.core import (
    QgsProject, QgsLayoutExporter, QgsPrintLayout, QgsLayoutItemMap, QgsLayoutItemLabel,
    QgsLayoutItemLegend, QgsLayoutItemScaleBar, QgsLayoutItemPage, QgsLayoutPoint,
    QgsUnitTypes,
)
from qgis.PyQt.QtCore import QRectF
from qgis.PyQt.QtGui import QFont

from ..registry import register
from .layers import _iface

C = "Layout e exportação de mapa"


def _layout(name):
    mgr = QgsProject.instance().layoutManager()
    lay = mgr.layoutByName(name)
    if not lay:
        raise ValueError(f"Layout '{name}' não encontrado. Disponíveis: {[l.name() for l in mgr.layouts()]}")
    return lay


@register(C, "info")
def list_layouts():
    """Lista layouts de impressão do projeto."""
    return [l.name() for l in QgsProject.instance().layoutManager().layouts()]


@register(C, "create")
def create_simple_layout(name, title=None, paper="A4", orientation="landscape",
                         legend=True, scalebar=True):
    """Cria layout com mapa (extensão atual), título, legenda e barra de escala. paper: A4|A3. orientation: landscape|portrait."""
    proj = QgsProject.instance()
    if proj.layoutManager().layoutByName(name):
        raise ValueError(f"Já existe layout '{name}'")
    dims = {"A4": (297, 210), "A3": (420, 297)}
    if paper not in dims:
        raise ValueError("paper deve ser A4 ou A3")
    w, h = dims[paper]
    land = orientation != "portrait"
    if not land:
        w, h = h, w
    lay = QgsPrintLayout(proj)
    lay.initializeDefaults()
    lay.setName(name)
    lay.pageCollection().page(0).setPageSize(
        paper, QgsLayoutItemPage.Landscape if land else QgsLayoutItemPage.Portrait)
    mm = QgsUnitTypes.LayoutMillimeters

    top = 22 if title else 10
    m = QgsLayoutItemMap(lay)
    m.attemptSetSceneRect(QRectF(10, top, w - 20, h - top - 10))
    m.setFrameEnabled(True)
    lay.addLayoutItem(m)
    m.setExtent(_iface().mapCanvas().extent())

    if title:
        lb = QgsLayoutItemLabel(lay)
        lb.setText(title)
        f = QFont()
        f.setPointSize(18)
        f.setBold(True)
        lb.setFont(f)
        lb.adjustSizeToText()
        lb.attemptMove(QgsLayoutPoint(10, 8, mm))
        lay.addLayoutItem(lb)
    if legend:
        lg = QgsLayoutItemLegend(lay)
        lg.setLinkedMap(m)
        lg.setAutoUpdateModel(True)
        lay.addLayoutItem(lg)
        lg.attemptMove(QgsLayoutPoint(14, top + 4, mm))
    if scalebar:
        sb = QgsLayoutItemScaleBar(lay)
        sb.setStyle("Single Box")
        sb.setLinkedMap(m)
        sb.applyDefaultSize()
        lay.addLayoutItem(sb)
        sb.attemptMove(QgsLayoutPoint(14, h - 22, mm))
    proj.layoutManager().addLayout(lay)
    return {"layout": name}


@register(C, "create")
def export_layout_pdf(layout_name, output_path):
    """Exporta um layout para PDF."""
    ex = QgsLayoutExporter(_layout(layout_name))
    r = ex.exportToPdf(output_path, QgsLayoutExporter.PdfExportSettings())
    if r != QgsLayoutExporter.Success:
        raise RuntimeError(f"Falha ao exportar PDF (código {r})")
    return {"output_path": output_path}


@register(C, "create")
def export_layout_image(layout_name, output_path, dpi=300):
    """Exporta um layout para imagem (png/jpg)."""
    ex = QgsLayoutExporter(_layout(layout_name))
    s = QgsLayoutExporter.ImageExportSettings()
    s.dpi = int(dpi)
    r = ex.exportToImage(output_path, s)
    if r != QgsLayoutExporter.Success:
        raise RuntimeError(f"Falha ao exportar imagem (código {r})")
    return {"output_path": output_path}


@register(C, "create")
def export_map_image(output_path):
    """Salva uma imagem do mapa como está na tela (sem layout)."""
    _iface().mapCanvas().saveAsImage(output_path)
    return {"output_path": output_path}
