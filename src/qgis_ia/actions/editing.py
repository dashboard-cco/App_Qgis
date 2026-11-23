# -*- coding: utf-8 -*-
"""
Actions: editing - Edição de feições e campos.

Todas as funções usam startEditing/commitChanges com rollBack em caso de erro,
para não deixar a camada num estado parcial.
"""
from qgis.core import QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry, QgsField
from qgis.PyQt.QtCore import QVariant

FIELD_TYPES = {
    "string": QVariant.String,
    "integer": QVariant.Int,
    "int": QVariant.Int,
    "double": QVariant.Double,
    "float": QVariant.Double,
    "boolean": QVariant.Bool,
    "bool": QVariant.Bool,
    "date": QVariant.Date,
}


def _vector(layer_name):
    layers = QgsProject.instance().mapLayersByName(layer_name)
    if not layers:
        raise ValueError(f"Camada não encontrada: {layer_name}")
    layer = layers[0]
    if not isinstance(layer, QgsVectorLayer):
        raise ValueError(f"'{layer_name}' não é uma camada vetorial")
    return layer


def _edit(layer, fn):
    """Roda fn(layer) dentro de uma sessão de edição, com rollback em erro."""
    already = layer.isEditable()
    if not already and not layer.startEditing():
        raise RuntimeError(f"Não consegui abrir edição em '{layer.name()}'.")
    try:
        result = fn(layer)
        if not already and not layer.commitChanges():
            errors = "; ".join(layer.commitErrors())
            layer.rollBack()
            raise RuntimeError(f"Falha ao gravar as alterações: {errors}")
        return result
    except Exception:
        if not already:
            layer.rollBack()
        raise


def add_features(layer_name, features):
    """Adiciona feições. features: [{"geom": "<WKT>", "attrs": {"campo": valor}}]."""
    layer = _vector(layer_name)
    if not features:
        raise ValueError("Informe ao menos uma feição em 'features'.")
    field_names = [f.name() for f in layer.fields()]

    def do(lyr):
        feats = []
        for item in features:
            feat = QgsFeature(lyr.fields())
            wkt = item.get("geom")
            if wkt:
                geom = QgsGeometry.fromWkt(wkt)
                if geom.isNull():
                    raise ValueError(f"Geometria WKT inválida: {wkt}")
                feat.setGeometry(geom)
            attrs = item.get("attrs") or {}
            unknown = set(attrs) - set(field_names)
            if unknown:
                raise ValueError(f"Campos inexistentes em '{layer_name}': {sorted(unknown)}")
            for name, value in attrs.items():
                feat.setAttribute(name, value)
            feats.append(feat)
        if not lyr.addFeatures(feats):
            raise RuntimeError("addFeatures falhou.")
        return len(feats)

    added = _edit(layer, do)
    layer.updateExtents()
    return {"success": True, "added": added, "feature_count": layer.featureCount()}


def update_features(layer_name, expression, attributes):
    """Atualiza atributos das feições que casam com a expressão QGIS."""
    layer = _vector(layer_name)
    if not attributes:
        raise ValueError("Informe 'attributes' com os campos a atualizar.")
    idx = {}
    for name in attributes:
        i = layer.fields().indexOf(name)
        if i < 0:
            raise ValueError(f"Campo não encontrado em '{layer_name}': {name}")
        idx[name] = i

    from qgis.core import QgsFeatureRequest, QgsExpression
    expr = QgsExpression(expression)
    if expr.hasParserError():
        raise ValueError(f"Erro na expressão: {expr.parserErrorString()}")
    request = QgsFeatureRequest().setFilterExpression(expression)
    fids = [f.id() for f in layer.getFeatures(request)]

    def do(lyr):
        for fid in fids:
            for name, value in attributes.items():
                if not lyr.changeAttributeValue(fid, idx[name], value):
                    raise RuntimeError(f"Falha ao atualizar a feição {fid}, campo '{name}'.")
        return len(fids)

    return {"success": True, "updated": _edit(layer, do)}


def delete_features(layer_name, expression):
    """Apaga as feições que casam com a expressão QGIS. [destrutivo]"""
    layer = _vector(layer_name)
    from qgis.core import QgsFeatureRequest, QgsExpression
    expr = QgsExpression(expression)
    if expr.hasParserError():
        raise ValueError(f"Erro na expressão: {expr.parserErrorString()}")
    fids = [f.id() for f in layer.getFeatures(QgsFeatureRequest().setFilterExpression(expression))]
    if not fids:
        return {"success": True, "deleted": 0, "feature_count": layer.featureCount()}

    def do(lyr):
        if not lyr.deleteFeatures(fids):
            raise RuntimeError("deleteFeatures falhou.")
        return len(fids)

    deleted = _edit(layer, do)
    return {"success": True, "deleted": deleted, "feature_count": layer.featureCount()}


def add_field(layer_name, field_name, field_type="String", length=255, precision=0):
    """Cria um campo novo (vazio) na camada."""
    layer = _vector(layer_name)
    if layer.fields().indexOf(field_name) >= 0:
        raise ValueError(f"O campo '{field_name}' já existe em '{layer_name}'.")
    qtype = FIELD_TYPES.get(str(field_type).lower())
    if qtype is None:
        raise ValueError(f"Tipo inválido: {field_type}. Use: {sorted(set(FIELD_TYPES))}")
    if not layer.dataProvider().addAttributes([QgsField(field_name, qtype, len=length, prec=precision)]):
        raise RuntimeError(f"O provedor de dados recusou criar o campo '{field_name}'.")
    layer.updateFields()
    return {"success": True, "field": field_name,
            "fields": [f.name() for f in layer.fields()]}


def delete_field(layer_name, field_name):
    """Remove um campo da camada. [destrutivo]"""
    layer = _vector(layer_name)
    idx = layer.fields().indexOf(field_name)
    if idx < 0:
        raise ValueError(f"Campo não encontrado em '{layer_name}': {field_name}")
    if not layer.dataProvider().deleteAttributes([idx]):
        raise RuntimeError(f"O provedor de dados recusou remover o campo '{field_name}'.")
    layer.updateFields()
    return {"success": True, "removed": field_name,
            "fields": [f.name() for f in layer.fields()]}


TOOLS = {
    "add_features": add_features,
    "update_features": update_features,
    "delete_features": delete_features,
    "add_field": add_field,
    "delete_field": delete_field,
}
