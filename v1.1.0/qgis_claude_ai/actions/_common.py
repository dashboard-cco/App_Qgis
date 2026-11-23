# -*- coding: utf-8 -*-
"""Helpers compartilhados pelas ações."""
import os
from contextlib import contextmanager

from qgis.core import (
    QgsProject, QgsMapLayer, QgsVectorLayer, QgsRasterLayer, QgsApplication,
    QgsProcessingFeedback, QgsProcessingParameterDefinition,
    QgsProcessingFeatureSourceDefinition,
)

LAYER_PARAM_TYPES = {"source", "vector", "raster", "layer", "mesh",
                     "pointcloud", "annotation", "vectortile"}
DEST_TYPES = {"sink", "vectorDestination", "rasterDestination"}

# Algoritmos que executam código arbitrário ou baixam arquivos: nunca liberados.
BLOCKED_PREFIXES = ("script:", "model:")
BLOCKED_IDS = {"native:filedownloader", "native:pythoncode"}


def get_layer(layer_name):
    """Acha camada por nome exato, depois sem diferenciar maiúsculas, depois por id."""
    proj = QgsProject.instance()
    found = proj.mapLayersByName(layer_name)
    if found:
        return found[0]
    low = str(layer_name).lower()
    for l in proj.mapLayers().values():
        if l.name().lower() == low:
            return l
    lyr = proj.mapLayer(str(layer_name))
    if lyr:
        return lyr
    names = [l.name() for l in proj.mapLayers().values()]
    raise ValueError(f"Camada não encontrada: '{layer_name}'. Camadas existentes: {names}")


def get_vector(layer_name):
    l = get_layer(layer_name)
    if not isinstance(l, QgsVectorLayer):
        raise ValueError(f"'{layer_name}' não é uma camada vetorial")
    return l


def get_raster(layer_name):
    l = get_layer(layer_name)
    if not isinstance(l, QgsRasterLayer):
        raise ValueError(f"'{layer_name}' não é uma camada raster")
    return l


@contextmanager
def editing(layer):
    """Edita e grava; se o usuário já estava em edição, deixa no buffer."""
    was = layer.isEditable()
    if not was and not layer.startEditing():
        raise RuntimeError(f"Não foi possível iniciar edição de '{layer.name()}' (somente leitura?)")
    try:
        yield
    except Exception:
        if not was:
            layer.rollBack()
        raise
    else:
        if not was and not layer.commitChanges():
            errs = "; ".join(layer.commitErrors())
            layer.rollBack()
            raise RuntimeError(f"Falha ao gravar edição: {errs}")


def to_py(v):
    """Converte valores Qt/QVariant em tipos JSON-safe."""
    try:
        from qgis.PyQt.QtCore import QVariant
        if v is None or (hasattr(v, "isNull") and v.isNull()):
            return None
    except Exception:
        pass
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


# ---------------------------------------------------------------- Processing

def _is_optional(d):
    try:
        return bool(d.flags() & QgsProcessingParameterDefinition.FlagOptional)
    except Exception:
        return False


def _ref(value, allow_selected=True):
    if isinstance(value, dict) and "layer" in value:
        lyr = get_layer(value["layer"])
        if allow_selected and value.get("selected_only"):
            return QgsProcessingFeatureSourceDefinition(lyr.id(), True)
        return lyr
    if isinstance(value, str):
        proj = QgsProject.instance()
        if proj.mapLayersByName(value):
            return proj.mapLayersByName(value)[0]
        if proj.mapLayer(value):
            return proj.mapLayer(value)
    return value


def resolve_params(alg, params):
    out = {}
    valid = [d.name() for d in alg.parameterDefinitions()]
    for key, value in (params or {}).items():
        k = key if key in valid else (key.upper() if key.upper() in valid else key)
        d = alg.parameterDefinition(k)
        if d is None:
            raise ValueError(f"Parâmetro '{key}' não existe em {alg.id()}. Válidos: {valid}. "
                             f"Use describe_algorithm('{alg.id()}').")
        t = d.type()
        if t in LAYER_PARAM_TYPES:
            out[k] = _ref(value)
        elif t == "multilayer":
            vals = value if isinstance(value, list) else [value]
            out[k] = [_ref(v, False) for v in vals]
        else:
            out[k] = value
    for d in alg.parameterDefinitions():
        if d.type() in DEST_TYPES and d.name() not in out and not _is_optional(d):
            out[d.name()] = "TEMPORARY_OUTPUT"
    return out


def _load_output(value, key, dtype, name):
    """Transforma o valor de saída (camada, id ou caminho) em camada do projeto."""
    proj = QgsProject.instance()
    lyr = None
    if isinstance(value, QgsMapLayer):
        lyr = value
    elif isinstance(value, str) and value:
        lyr = proj.mapLayer(value)
        if lyr is None and os.path.exists(value.split("|")[0]):
            if dtype == "rasterDestination":
                lyr = QgsRasterLayer(value, name)
            else:
                lyr = QgsVectorLayer(value, name, "ogr")
            if not lyr.isValid():
                lyr = None
    if lyr is None:
        return None
    if proj.mapLayer(lyr.id()) is None:     # não renomeia/readiciona camadas de entrada
        lyr.setName(name)
        proj.addMapLayer(lyr)
    return lyr


def run_alg(algorithm_id, params=None, output_name=None, output_path=None):
    """Executa um algoritmo do Processing, carrega as saídas e devolve resumo."""
    import processing
    low = algorithm_id.lower()
    if low.startswith(BLOCKED_PREFIXES) or low in BLOCKED_IDS or "pythoncode" in low:
        raise PermissionError(f"Algoritmo bloqueado por segurança: {algorithm_id}")
    alg = QgsApplication.processingRegistry().algorithmById(algorithm_id)
    if alg is None:
        tail = algorithm_id.split(":")[-1].lower()
        similar = [a.id() for a in QgsApplication.processingRegistry().algorithms()
                   if tail in a.id().lower()][:8]
        raise ValueError(f"Algoritmo '{algorithm_id}' não existe. Parecidos: {similar}. "
                         f"Use list_algorithms.")
    p = resolve_params(alg, params)
    if output_path:
        p["OUTPUT"] = output_path
    result = processing.run(algorithm_id, p, feedback=QgsProcessingFeedback())

    dests = {d.name(): d.type() for d in alg.parameterDefinitions() if d.type() in DEST_TYPES}
    base = output_name or alg.displayName()
    layers, other = [], {}
    for key, value in result.items():
        if key in dests or isinstance(value, QgsMapLayer):
            nm = base if not layers else f"{base}_{key.lower()}"
            lyr = _load_output(value, key, dests.get(key), nm)
            if lyr is not None:
                info = {"name": lyr.name()}
                if isinstance(lyr, QgsVectorLayer):
                    info["feature_count"] = lyr.featureCount()
                layers.append(info)
                continue
        other[key] = value if isinstance(value, (str, int, float, bool, type(None))) else str(value)
    out = {"output_layers": layers}
    if layers:
        out["output_layer"] = layers[0]["name"]
        if "feature_count" in layers[0]:
            out["feature_count"] = layers[0]["feature_count"]
    if other:
        out["other_outputs"] = other
    return out
