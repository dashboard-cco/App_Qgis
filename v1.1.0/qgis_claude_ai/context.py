# -*- coding: utf-8 -*-
"""Monta o resumo do projeto enviado à IA (camadas, tipos, CRS e campos)."""
import json
from qgis.core import QgsProject, QgsVectorLayer, QgsRasterLayer, QgsWkbTypes


def _layer_summary(l, detailed):
    d = {"name": l.name(), "crs": l.crs().authid()}
    if isinstance(l, QgsVectorLayer):
        d["type"] = "vector"
        d["geometry"] = QgsWkbTypes.displayString(l.wkbType())
        d["features"] = l.featureCount()
        if l.selectedFeatureCount():
            d["selected"] = l.selectedFeatureCount()
        fields = [f"{f.name()}:{f.typeName()}" for f in l.fields()]
        d["fields"] = fields[:40] if detailed else fields[:15]
    elif isinstance(l, QgsRasterLayer):
        d["type"] = "raster"
        d["bands"] = l.bandCount()
    else:
        d["type"] = "other"
    return d


def build_context(focus_layer_name=None, max_layers=60):
    proj = QgsProject.instance()
    layers = list(proj.mapLayers().values())[:max_layers]
    ctx = {
        "project_crs": proj.crs().authid(),
        "layers": [_layer_summary(l, l.name() == focus_layer_name) for l in layers],
        "layouts": [l.name() for l in proj.layoutManager().layouts()],
    }
    if focus_layer_name:
        ctx["focus_layer"] = focus_layer_name
    return json.dumps(ctx, ensure_ascii=False)
