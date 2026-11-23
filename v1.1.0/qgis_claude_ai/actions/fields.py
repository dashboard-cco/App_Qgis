# -*- coding: utf-8 -*-
"""Ações: tabela de atributos e edição de feições."""
import statistics

from qgis.core import (
    QgsField, QgsFeature, QgsGeometry, QgsExpression, QgsExpressionContext,
    QgsExpressionContextUtils, QgsFeatureRequest,
)

from ..registry import register
from ._common import get_vector, editing, to_py
from qgis.PyQt.QtCore import QVariant
from .layers import FIELD_TYPES

C = "Atributos e feições"


def _request(layer, expression=None, only_selected=False):
    if only_selected:
        return layer.getSelectedFeatures()
    if expression:
        e = QgsExpression(expression)
        if e.hasParserError():
            raise ValueError(f"Erro na expressão: {e.parserErrorString()}")
        return layer.getFeatures(QgsFeatureRequest(e))
    return layer.getFeatures()


@register(C, "info")
def get_features(layer_name, expression=None, fields=None, limit=20, only_selected=False):
    """Lê atributos (máx. 200 linhas), opcionalmente filtrando por expressão/campos/seleção."""
    layer = get_vector(layer_name)
    limit = max(1, min(int(limit), 200))
    names = fields or [f.name() for f in layer.fields()][:25]
    rows = []
    for f in _request(layer, expression, only_selected):
        rows.append({n: to_py(f[n]) for n in names})
        if len(rows) >= limit:
            break
    return {"rows": rows, "shown": len(rows)}


@register(C, "info")
def count_features(layer_name, expression=None):
    """Conta feições (todas ou que atendem a uma expressão)."""
    layer = get_vector(layer_name)
    if not expression:
        return {"count": layer.featureCount()}
    return {"count": sum(1 for _ in _request(layer, expression))}


@register(C, "info")
def unique_values(layer_name, field, limit=50):
    """Valores únicos de um campo."""
    layer = get_vector(layer_name)
    idx = layer.fields().indexOf(field)
    if idx < 0:
        raise ValueError(f"Campo '{field}' não existe. Campos: {[f.name() for f in layer.fields()]}")
    vals = sorted((to_py(v) for v in layer.uniqueValues(idx)), key=lambda x: (x is None, str(x)))
    return {"total": len(vals), "values": vals[:int(limit)]}


@register(C, "info")
def field_statistics(layer_name, field, expression=None):
    """Estatísticas de campo numérico: contagem, soma, média, mín, máx, mediana, desvio."""
    layer = get_vector(layer_name)
    if layer.fields().indexOf(field) < 0:
        raise ValueError(f"Campo '{field}' não existe")
    vals = []
    for f in _request(layer, expression):
        v = f[field]
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            vals.append(float(v))
    if not vals:
        return {"count": 0}
    return {"count": len(vals), "sum": sum(vals), "mean": statistics.fmean(vals),
            "min": min(vals), "max": max(vals), "median": statistics.median(vals),
            "stdev": statistics.pstdev(vals)}


@register(C, "modify")
def add_field(layer_name, field_name, field_type="String", length=0, precision=0):
    """Adiciona campo vazio. Tipos: String, Int, Double, Bool, Date."""
    layer = get_vector(layer_name)
    if layer.fields().indexOf(field_name) >= 0:
        raise ValueError(f"Campo '{field_name}' já existe")
    qt = FIELD_TYPES.get(field_type.lower(), None)
    if qt is None:
        raise ValueError(f"Tipo inválido: {field_type}")
    with editing(layer):
        if not layer.addAttribute(QgsField(field_name, qt, "", int(length), int(precision))):
            raise RuntimeError("Falha ao adicionar campo")
    return {"added": field_name}


@register(C, "destructive")
def delete_field(layer_name, field_name):
    """Apaga um campo da camada."""
    layer = get_vector(layer_name)
    idx = layer.fields().indexOf(field_name)
    if idx < 0:
        raise ValueError(f"Campo '{field_name}' não existe")
    with editing(layer):
        layer.deleteAttribute(idx)
    return {"deleted": field_name}


@register(C, "modify")
def rename_field(layer_name, field_name, new_name):
    """Renomeia um campo."""
    layer = get_vector(layer_name)
    idx = layer.fields().indexOf(field_name)
    if idx < 0:
        raise ValueError(f"Campo '{field_name}' não existe")
    with editing(layer):
        layer.renameAttribute(idx, new_name)
    return {"renamed": f"{field_name} -> {new_name}"}


@register(C, "modify")
def calculate_field(layer_name, field_name, expression, field_type="String",
                    field_length=0, field_precision=0, only_selected=False, where=None):
    """Calcula/atualiza campo (cria se não existir) por expressão QGIS; where=filtro opcional."""
    layer = get_vector(layer_name)
    qt = FIELD_TYPES.get(field_type.lower(), QVariant.String)
    expr = QgsExpression(expression)
    if expr.hasParserError():
        raise ValueError(f"Erro na expressão: {expr.parserErrorString()}")
    ctx = QgsExpressionContext()
    ctx.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
    count = 0
    with editing(layer):
        if layer.fields().indexOf(field_name) < 0:
            layer.addAttribute(QgsField(field_name, qt, "", int(field_length), int(field_precision)))
            layer.updateFields()
        idx = layer.fields().indexOf(field_name)
        for feat in _request(layer, where, only_selected):
            ctx.setFeature(feat)
            val = expr.evaluate(ctx)
            if expr.hasEvalError():
                raise RuntimeError(f"Erro ao avaliar: {expr.evalErrorString()}")
            layer.changeAttributeValue(feat.id(), idx, val)
            count += 1
    return {"updated_features": count, "field_name": field_name}


@register(C, "modify")
def add_feature(layer_name, geom_wkt, attributes=None):
    """Adiciona uma feição (WKT na camada do CRS da camada) com attributes={campo: valor}."""
    layer = get_vector(layer_name)
    g = QgsGeometry.fromWkt(geom_wkt)
    if g.isNull():
        raise ValueError(f"WKT inválido: {geom_wkt}")
    feat = QgsFeature(layer.fields())
    feat.setGeometry(g)
    for k, v in (attributes or {}).items():
        if layer.fields().indexOf(k) < 0:
            raise ValueError(f"Campo '{k}' não existe")
        feat[k] = v
    with editing(layer):
        if not layer.addFeature(feat):
            raise RuntimeError("Falha ao adicionar feição")
    return {"added": 1}


@register(C, "destructive")
def delete_features(layer_name, expression=None, only_selected=False):
    """Apaga feições por expressão ou seleção (exige um dos dois)."""
    layer = get_vector(layer_name)
    if not expression and not only_selected:
        raise ValueError("Informe expression ou only_selected=true (não apago tudo sem pedido explícito)")
    ids = [f.id() for f in _request(layer, expression, only_selected)]
    with editing(layer):
        layer.deleteFeatures(ids)
    return {"deleted": len(ids)}


@register(C, "view")
def filter_layer(layer_name, expression):
    """Aplica filtro (subset string, sintaxe do provedor) à camada."""
    layer = get_vector(layer_name)
    if not layer.setSubsetString(expression):
        raise RuntimeError("Filtro rejeitado pelo provedor")
    return {"filter": expression, "feature_count": layer.featureCount()}


@register(C, "view")
def clear_filter(layer_name):
    """Remove o filtro da camada."""
    layer = get_vector(layer_name)
    layer.setSubsetString("")
    return {"feature_count": layer.featureCount()}
