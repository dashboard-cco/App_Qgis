# -*- coding: utf-8 -*-
"""Ações: camadas, projeto e visualização do mapa."""
import os
from urllib.parse import quote

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsRasterLayer, QgsFeature, QgsGeometry,
    QgsField, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsVectorFileWriter, QgsWkbTypes, QgsProviderRegistry, QgsMapLayer,
)
from qgis.PyQt.QtCore import QVariant

from ..registry import register
from ._common import get_layer, get_vector, get_raster, to_py

C = "Camadas e projeto"

FIELD_TYPES = {
    "string": QVariant.String, "text": QVariant.String,
    "int": QVariant.Int, "integer": QVariant.Int,
    "double": QVariant.Double, "float": QVariant.Double, "real": QVariant.Double,
    "bool": QVariant.Bool, "boolean": QVariant.Bool,
    "date": QVariant.Date, "datetime": QVariant.DateTime,
}


def _iface():
    from qgis.utils import iface
    return iface


@register(C, "info")
def list_layers():
    """Lista camadas do projeto (nome, tipo, geometria, CRS, nº de feições)."""
    out = []
    for l in QgsProject.instance().mapLayers().values():
        d = {"name": l.name(), "crs": l.crs().authid()}
        if isinstance(l, QgsVectorLayer):
            d.update(type="vector", geometry=QgsWkbTypes.displayString(l.wkbType()),
                     features=l.featureCount())
        elif isinstance(l, QgsRasterLayer):
            d["type"] = "raster"
        else:
            d["type"] = "other"
        out.append(d)
    return out


@register(C, "info")
def layer_info(layer_name):
    """Detalhes de uma camada: fonte, CRS, extensão, campos e tipos, seleção, filtro."""
    l = get_layer(layer_name)
    e = l.extent()
    d = {"name": l.name(), "source": l.source(), "crs": l.crs().authid(),
         "extent": [e.xMinimum(), e.yMinimum(), e.xMaximum(), e.yMaximum()]}
    if isinstance(l, QgsVectorLayer):
        d.update(type="vector", geometry=QgsWkbTypes.displayString(l.wkbType()),
                 features=l.featureCount(), selected=l.selectedFeatureCount(),
                 filter=l.subsetString(), editable=l.isEditable(),
                 fields=[{"name": f.name(), "type": f.typeName()} for f in l.fields()])
    elif isinstance(l, QgsRasterLayer):
        d.update(type="raster", bands=l.bandCount(), width=l.width(), height=l.height(),
                 pixel_size=[l.rasterUnitsPerPixelX(), l.rasterUnitsPerPixelY()])
    return d


@register(C, "info")
def list_sublayers(file_path):
    """Lista camadas dentro de um GeoPackage/.gdb/arquivo multi-camada."""
    subs = QgsProviderRegistry.instance().querySublayers(file_path)
    return [{"name": s.name(), "uri": s.uri()} for s in subs]


@register(C, "create")
def add_vector_layer(file_path, layer_name=None, sublayer=None):
    """Carrega vetor (shp, gpkg, geojson, .gdb...). Em gpkg/gdb use sublayer=nome da camada."""
    uri = f"{file_path}|layername={sublayer}" if sublayer else file_path
    name = layer_name or sublayer or os.path.basename(file_path)
    layer = QgsVectorLayer(uri, name, "ogr")
    if not layer.isValid():
        raise RuntimeError(f"Falha ao carregar camada vetorial: {uri}. "
                           f"Se for gpkg/gdb, use list_sublayers.")
    QgsProject.instance().addMapLayer(layer)
    return {"layer_name": layer.name(), "feature_count": layer.featureCount()}


@register(C, "create")
def add_raster_layer(file_path, layer_name=None):
    """Carrega um raster (GeoTIFF etc.)."""
    layer = QgsRasterLayer(file_path, layer_name or os.path.basename(file_path))
    if not layer.isValid():
        raise RuntimeError(f"Falha ao carregar raster: {file_path}")
    QgsProject.instance().addMapLayer(layer)
    return {"layer_name": layer.name()}


@register(C, "create")
def add_csv_layer(file_path, x_field, y_field, crs="EPSG:4326", delimiter=",", layer_name=None):
    """Carrega CSV com colunas de coordenadas como camada de pontos."""
    path = file_path.replace("\\", "/")
    uri = (f"file:///{quote(path, safe='/:')}?delimiter={quote(delimiter)}"
           f"&xField={x_field}&yField={y_field}&crs={crs}")
    layer = QgsVectorLayer(uri, layer_name or os.path.basename(file_path), "delimitedtext")
    if not layer.isValid():
        raise RuntimeError(f"Falha ao carregar CSV: {file_path}")
    QgsProject.instance().addMapLayer(layer)
    return {"layer_name": layer.name(), "feature_count": layer.featureCount()}


@register(C, "create")
def add_basemap(kind="osm"):
    """Adiciona mapa base online: 'osm' (OpenStreetMap) ou 'satellite' (Esri)."""
    urls = {
        "osm": ("OpenStreetMap", "https://tile.openstreetmap.org/{z}/{x}/{y}.png", 19),
        "satellite": ("Esri World Imagery",
                      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", 19),
    }
    if kind not in urls:
        raise ValueError(f"kind deve ser um de {list(urls)}")
    name, url, zmax = urls[kind]
    enc = url.replace("{", "%7B").replace("}", "%7D")
    layer = QgsRasterLayer(f"type=xyz&url={enc}&zmax={zmax}&zmin=0", name, "wms")
    if not layer.isValid():
        raise RuntimeError("Falha ao adicionar mapa base (sem internet?)")
    QgsProject.instance().addMapLayer(layer, False)
    QgsProject.instance().layerTreeRoot().insertLayer(-1, layer)
    return {"layer_name": name}


@register(C, "destructive")
def remove_layer(layer_name):
    """Remove uma camada do projeto (não apaga o arquivo)."""
    layer = get_layer(layer_name)
    QgsProject.instance().removeMapLayer(layer.id())
    return {"removed": layer_name}


@register(C, "create")
def duplicate_layer(layer_name, new_name=None):
    """Duplica uma camada vetorial como camada temporária (memória)."""
    import processing
    src = get_vector(layer_name)
    res = processing.run("native:savefeatures", {"INPUT": src, "OUTPUT": "TEMPORARY_OUTPUT"})
    out = res["OUTPUT"]
    out.setName(new_name or f"{layer_name}_copia")
    QgsProject.instance().addMapLayer(out)
    return {"layer_name": out.name(), "feature_count": out.featureCount()}


@register(C, "view")
def rename_layer(layer_name, new_name):
    """Renomeia uma camada."""
    get_layer(layer_name).setName(new_name)
    return {"new_name": new_name}


@register(C, "view")
def set_layer_visibility(layer_name, visible=True):
    """Liga/desliga a visibilidade da camada no mapa."""
    layer = get_layer(layer_name)
    node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
    if node is None:
        raise RuntimeError("Camada fora da árvore de camadas")
    node.setItemVisibilityChecked(bool(visible))
    return {"layer": layer_name, "visible": bool(visible)}


@register(C, "view")
def set_layer_opacity(layer_name, opacity=1.0):
    """Define opacidade (0 a 1) de vetor ou raster."""
    layer = get_layer(layer_name)
    layer.setOpacity(float(opacity))
    layer.triggerRepaint()
    return {"layer": layer_name, "opacity": float(opacity)}


@register(C, "view")
def group_layers(group_name, layer_names):
    """Move camadas para um grupo (cria o grupo se não existir)."""
    root = QgsProject.instance().layerTreeRoot()
    grp = root.findGroup(group_name) or root.addGroup(group_name)
    for n in layer_names:
        lyr = get_layer(n)
        node = root.findLayer(lyr.id())
        if node is None:
            continue
        grp.addLayer(lyr)
        node.parent().removeChildNode(node)
    return {"group": group_name, "layers": list(layer_names)}


@register(C, "view")
def set_layer_crs(layer_name, crs):
    """Define (não reprojeta!) o CRS de uma camada sem CRS/errado. Ex: 'EPSG:31983'."""
    c = QgsCoordinateReferenceSystem(crs)
    if not c.isValid():
        raise ValueError(f"CRS inválido: {crs}")
    get_layer(layer_name).setCrs(c)
    return {"layer": layer_name, "crs": crs}


@register(C, "view")
def set_project_crs(crs):
    """Define o CRS do projeto. Ex: 'EPSG:31983'."""
    c = QgsCoordinateReferenceSystem(crs)
    if not c.isValid():
        raise ValueError(f"CRS inválido: {crs}")
    QgsProject.instance().setCrs(c)
    return {"project_crs": crs}


@register(C, "modify")
def save_project(path=None):
    """Salva o projeto (path opcional para 'salvar como', .qgz)."""
    proj = QgsProject.instance()
    if path:
        proj.setFileName(path)
    if not proj.fileName():
        raise ValueError("Projeto sem arquivo: informe path (.qgz)")
    if not proj.write():
        raise RuntimeError("Falha ao salvar o projeto")
    return {"saved": proj.fileName()}


@register(C, "create")
def export_layer(layer_name, output_path, format=None, selected_only=False, crs=None):
    """Exporta camada vetorial. format: GPKG, ESRI Shapefile, GeoJSON, CSV, KML, DXF (padrão: pela extensão). .gdb pode não ter gravação: prefira GPKG."""
    layer = get_vector(layer_name)
    ext_map = {".gpkg": "GPKG", ".shp": "ESRI Shapefile", ".geojson": "GeoJSON",
               ".json": "GeoJSON", ".csv": "CSV", ".kml": "KML", ".dxf": "DXF"}
    driver = format or ext_map.get(os.path.splitext(output_path)[1].lower(), "GPKG")
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = driver
    opts.onlySelectedFeatures = bool(selected_only)
    opts.fileEncoding = "UTF-8"
    if crs:
        dest = QgsCoordinateReferenceSystem(crs)
        if not dest.isValid():
            raise ValueError(f"CRS inválido: {crs}")
        opts.ct = QgsCoordinateTransform(layer.crs(), dest, QgsProject.instance())
    err = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, output_path, QgsProject.instance().transformContext(), opts)
    if err[0] != QgsVectorFileWriter.NoError:
        raise RuntimeError(f"Falha ao exportar: {err[1]}")
    return {"output_path": output_path, "driver": driver}


@register(C, "view")
def zoom_to_layer(layer_name):
    """Ajusta o mapa à extensão da camada."""
    ifc = _iface()
    layer = get_layer(layer_name)
    ext = layer.extent()
    if layer.crs() != ifc.mapCanvas().mapSettings().destinationCrs():
        ext = QgsCoordinateTransform(layer.crs(), ifc.mapCanvas().mapSettings().destinationCrs(),
                                     QgsProject.instance()).transformBoundingBox(ext)
    ifc.mapCanvas().setExtent(ext)
    ifc.mapCanvas().refresh()
    return {"layer": layer_name}


@register(C, "view")
def zoom_to_selection(layer_name):
    """Ajusta o mapa às feições selecionadas."""
    ifc = _iface()
    layer = get_vector(layer_name)
    if layer.selectedFeatureCount() == 0:
        raise ValueError("Nenhuma feição selecionada")
    ifc.mapCanvas().zoomToSelected(layer)
    return {"selected": layer.selectedFeatureCount()}


@register(C, "view")
def set_map_scale(scale):
    """Define a escala do mapa (ex: 5000 para 1:5000)."""
    ifc = _iface()
    ifc.mapCanvas().zoomScale(float(scale))
    return {"scale": float(scale)}


@register(C, "view")
def select_by_expression(layer_name, expression, behavior="new"):
    """Seleciona feições por expressão QGIS. behavior: new|add|remove|intersect."""
    layer = get_vector(layer_name)
    mode = {"new": QgsVectorLayer.SetSelection, "add": QgsVectorLayer.AddToSelection,
            "remove": QgsVectorLayer.RemoveFromSelection,
            "intersect": QgsVectorLayer.IntersectSelection}.get(behavior)
    if mode is None:
        raise ValueError("behavior deve ser new|add|remove|intersect")
    layer.selectByExpression(expression, mode)
    return {"selected_count": layer.selectedFeatureCount()}


@register(C, "view")
def clear_selection(layer_name=None):
    """Limpa a seleção de uma camada (ou de todas se omitido)."""
    layers = [get_vector(layer_name)] if layer_name else [
        l for l in QgsProject.instance().mapLayers().values() if isinstance(l, QgsVectorLayer)]
    for l in layers:
        l.removeSelection()
    return {"cleared": len(layers)}


@register(C, "view")
def invert_selection(layer_name):
    """Inverte a seleção da camada."""
    layer = get_vector(layer_name)
    layer.invertSelection()
    return {"selected_count": layer.selectedFeatureCount()}


@register(C, "create")
def create_memory_layer(name, geometry_type="Point", fields=None, features=None, crs="EPSG:4326"):
    """Cria camada temporária. fields=[{name,type}], features=[{geom:'WKT', attrs:[...]}]."""
    layer = QgsVectorLayer(f"{geometry_type}?crs={crs}", name, "memory")
    if not layer.isValid():
        raise RuntimeError("Falha ao criar camada em memória")
    prov = layer.dataProvider()
    if fields:
        prov.addAttributes([QgsField(f.get("name", "campo"),
                                     FIELD_TYPES.get(str(f.get("type", "String")).lower(), QVariant.String))
                            for f in fields])
        layer.updateFields()
    if features:
        feats = []
        for f in features:
            feat = QgsFeature(layer.fields())
            if f.get("geom"):
                g = QgsGeometry.fromWkt(f["geom"])
                if g.isNull():
                    raise ValueError(f"WKT inválido: {f['geom']}")
                feat.setGeometry(g)
            feat.setAttributes(f.get("attrs", []))
            feats.append(feat)
        prov.addFeatures(feats)
        layer.updateExtents()
    QgsProject.instance().addMapLayer(layer)
    return {"layer_name": layer.name(), "feature_count": layer.featureCount()}
