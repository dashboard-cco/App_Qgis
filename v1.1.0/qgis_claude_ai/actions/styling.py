# -*- coding: utf-8 -*-
"""Ações: simbologia e rótulos."""
from qgis.core import (
    QgsSymbol, QgsSingleSymbolRenderer, QgsCategorizedSymbolRenderer, QgsRendererCategory,
    QgsGraduatedSymbolRenderer, QgsClassificationQuantile, QgsClassificationJenks,
    QgsClassificationEqualInterval, QgsStyle, QgsGradientColorRamp, QgsPalLayerSettings,
    QgsTextFormat, QgsVectorLayerSimpleLabeling, QgsVectorLayer,
)
from qgis.PyQt.QtGui import QColor

from ..registry import register
from ._common import get_vector
from .layers import _iface

C = "Estilo e rótulos"


def _color(c):
    q = QColor(c)
    if not q.isValid():
        raise ValueError(f"Cor inválida: '{c}'. Use nome em inglês (red) ou hex (#ff0000)")
    return q


def _ramp(name):
    r = QgsStyle.defaultStyle().colorRamp(name) if name else None
    return r if r is not None else QgsGradientColorRamp(QColor("#ffffb2"), QColor("#bd0026"))


def _refresh(layer):
    layer.triggerRepaint()
    try:
        _iface().layerTreeView().refreshLayerSymbology(layer.id())
    except Exception:
        pass


@register(C, "view")
def set_single_color(layer_name, color="#3388ff", outline_color=None, opacity=None):
    """Simbologia simples: cor de preenchimento/traço (nome ou #hex), cor de contorno e opacidade 0-1."""
    layer = get_vector(layer_name)
    sym = QgsSymbol.defaultSymbol(layer.geometryType())
    sym.setColor(_color(color))
    if outline_color:
        sl = sym.symbolLayer(0)
        if hasattr(sl, "setStrokeColor"):
            sl.setStrokeColor(_color(outline_color))
    if opacity is not None:
        sym.setOpacity(float(opacity))
    layer.setRenderer(QgsSingleSymbolRenderer(sym))
    _refresh(layer)
    return {"layer": layer_name, "color": color}


@register(C, "view")
def set_categorized(layer_name, field, color_ramp="Spectral"):
    """Simbologia categorizada por valores únicos de um campo. color_ramp: Spectral, Viridis, Blues, Reds, Greens..."""
    layer = get_vector(layer_name)
    idx = layer.fields().indexOf(field)
    if idx < 0:
        raise ValueError(f"Campo '{field}' não existe")
    values = sorted(layer.uniqueValues(idx), key=lambda v: (v is None, str(v)))
    if len(values) > 300:
        raise ValueError(f"{len(values)} valores únicos: muitos para categorizar")
    ramp = _ramp(color_ramp)
    cats = []
    n = max(len(values) - 1, 1)
    for i, v in enumerate(values):
        sym = QgsSymbol.defaultSymbol(layer.geometryType())
        sym.setColor(ramp.color(i / n))
        cats.append(QgsRendererCategory(v, sym, str(v) if v is not None else "(vazio)"))
    layer.setRenderer(QgsCategorizedSymbolRenderer(field, cats))
    _refresh(layer)
    return {"layer": layer_name, "categories": len(cats)}


@register(C, "view")
def set_graduated(layer_name, field, classes=5, mode="quantile", color_ramp="YlOrRd"):
    """Simbologia graduada por campo numérico. mode: quantile|jenks|equal."""
    layer = get_vector(layer_name)
    if layer.fields().indexOf(field) < 0:
        raise ValueError(f"Campo '{field}' não existe")
    method = {"quantile": QgsClassificationQuantile, "jenks": QgsClassificationJenks,
              "equal": QgsClassificationEqualInterval}.get(mode)
    if method is None:
        raise ValueError("mode deve ser quantile|jenks|equal")
    r = QgsGraduatedSymbolRenderer(field)
    r.setSourceSymbol(QgsSymbol.defaultSymbol(layer.geometryType()))
    r.setSourceColorRamp(_ramp(color_ramp))
    r.setClassificationMethod(method())
    r.updateClasses(layer, int(classes))
    layer.setRenderer(r)
    _refresh(layer)
    return {"layer": layer_name, "classes": len(r.ranges())}


@register(C, "view")
def set_labels(layer_name, field_or_expression, size=10, color="#000000", is_expression=False):
    """Ativa rótulos usando um campo (ou expressão com is_expression=true)."""
    layer = get_vector(layer_name)
    s = QgsPalLayerSettings()
    s.fieldName = field_or_expression
    s.isExpression = bool(is_expression)
    fmt = QgsTextFormat()
    fmt.setSize(float(size))
    fmt.setColor(_color(color))
    s.setFormat(fmt)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(s))
    layer.setLabelsEnabled(True)
    layer.triggerRepaint()
    return {"layer": layer_name, "label": field_or_expression}


@register(C, "view")
def remove_labels(layer_name):
    """Desativa rótulos da camada."""
    layer = get_vector(layer_name)
    layer.setLabelsEnabled(False)
    layer.triggerRepaint()
    return {"layer": layer_name}
