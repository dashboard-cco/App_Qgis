# -*- coding: utf-8 -*-
"""Ações: geoprocessamento (Processing). Atalhos para as ferramentas mais usadas
+ acesso genérico (list/describe/run_algorithm) a QUALQUER algoritmo do QGIS."""
from qgis.core import QgsApplication, QgsProject, QgsVectorLayer

from ..registry import register
from ._common import get_layer, get_vector, get_raster, run_alg

C = "Geoprocessamento vetorial"
G = "Acesso genérico ao Processing (qualquer algoritmo)"
R = "Raster"

PREDICATES = {"intersects": 0, "contains": 1, "disjoint": 2, "equals": 3,
              "touches": 4, "overlaps": 5, "within": 6, "crosses": 7}
OPERATORS = {"=": 0, "!=": 1, ">": 2, ">=": 3, "<": 4, "<=": 5, "begins with": 6,
             "contains": 7, "is null": 8, "is not null": 9, "does not contain": 10}
SEL_METHODS = {"new": 0, "add": 1, "remove": 2, "within": 3}
STATS = {"count": 0, "sum": 1, "mean": 2, "median": 3, "stdev": 4, "min": 5,
         "max": 6, "range": 7, "minority": 8, "majority": 9, "variety": 10, "variance": 11}


def _pred(p):
    ps = p if isinstance(p, list) else [p]
    out = []
    for x in ps:
        if x not in PREDICATES:
            raise ValueError(f"predicate inválido '{x}'. Use: {list(PREDICATES)}")
        out.append(PREDICATES[x])
    return out


# ------------------------------------------------------------------ genérico
@register(G, "info")
def list_algorithms(search_text="", provider=None):
    """Busca algoritmos do Processing por texto (id/nome). Retorna até 60."""
    s = (search_text or "").lower()
    res = []
    for a in QgsApplication.processingRegistry().algorithms():
        if provider and a.provider().id() != provider:
            continue
        if s and s not in a.id().lower() and s not in a.displayName().lower() \
                and s not in (a.group() or "").lower():
            continue
        res.append({"id": a.id(), "name": a.displayName(), "group": a.group()})
    return {"total": len(res), "algorithms": res[:60]}


@register(G, "info")
def describe_algorithm(algorithm_id):
    """Mostra parâmetros EXATOS (nome, tipo, opções de enum, padrão) de um algoritmo. Use antes de run_algorithm."""
    alg = QgsApplication.processingRegistry().algorithmById(algorithm_id)
    if alg is None:
        raise ValueError(f"Algoritmo '{algorithm_id}' não existe. Use list_algorithms.")
    params = []
    for d in alg.parameterDefinitions():
        if d.isDestination() and d.type() not in ("sink", "vectorDestination", "rasterDestination"):
            continue
        item = {"name": d.name(), "type": d.type(), "description": d.description()}
        try:
            from ._common import _is_optional
            if _is_optional(d):
                item["optional"] = True
        except Exception:
            pass
        if hasattr(d, "options"):
            try:
                item["options"] = {i: o for i, o in enumerate(d.options())}
            except Exception:
                pass
        dv = d.defaultValue()
        if dv not in (None, "", []):
            item["default"] = dv if isinstance(dv, (str, int, float, bool, list)) else str(dv)
        params.append(item)
    return {"id": alg.id(), "name": alg.displayName(),
            "help": (alg.shortDescription() or alg.shortHelpString() or "")[:500],
            "parameters": params}


@register(G, "create")
def run_algorithm(algorithm_id, params=None, output_name=None, output_path=None):
    """Executa qualquer algoritmo. params usa nomes EXATOS (ex.{'INPUT':'camada','DISTANCE':50}); camada pode ser 'nome' ou {'layer':'nome','selected_only':true}. Saídas temporárias são carregadas no projeto; output_path salva em arquivo."""
    return run_alg(algorithm_id, params, output_name, output_path)


# ----------------------------------------------------------------- vetoriais
@register(C)
def run_buffer(input_layer, distance, segments=5, dissolve=False, output_name="buffer"):
    """Buffer (zona de influência). distance na unidade do CRS da camada (m se projetado)."""
    return run_alg("native:buffer", {"INPUT": input_layer, "DISTANCE": distance,
                                    "SEGMENTS": segments, "DISSOLVE": dissolve}, output_name)


@register(C)
def run_intersection(input_layer, overlay_layer, output_name="intersecao"):
    """Interseção entre duas camadas."""
    return run_alg("native:intersection", {"INPUT": input_layer, "OVERLAY": overlay_layer}, output_name)


@register(C)
def run_difference(input_layer, overlay_layer, output_name="diferenca"):
    """Diferença (A menos B)."""
    return run_alg("native:difference", {"INPUT": input_layer, "OVERLAY": overlay_layer}, output_name)


@register(C)
def run_union(input_layer, overlay_layer, output_name="uniao"):
    """União de duas camadas de polígonos."""
    return run_alg("native:union", {"INPUT": input_layer, "OVERLAY": overlay_layer}, output_name)


@register(C)
def run_dissolve(input_layer, field=None, output_name="dissolvido"):
    """Dissolve feições (opcionalmente por campo ou lista de campos)."""
    f = [field] if isinstance(field, str) else (field or [])
    return run_alg("native:dissolve", {"INPUT": input_layer, "FIELD": f}, output_name)


@register(C)
def run_clip(input_layer, overlay_layer, output_name="recorte"):
    """Recorta input_layer pelo limite de overlay_layer."""
    return run_alg("native:clip", {"INPUT": input_layer, "OVERLAY": overlay_layer}, output_name)


@register(C)
def run_merge_layers(input_layers, output_name="mesclado"):
    """Mescla várias camadas vetoriais numa só."""
    return run_alg("native:mergevectorlayers", {"LAYERS": input_layers}, output_name)


@register(C)
def run_reproject(input_layer, target_crs, output_name="reprojetado"):
    """Reprojeta camada vetorial para outro CRS. Ex: 'EPSG:31983'."""
    return run_alg("native:reprojectlayer", {"INPUT": input_layer, "TARGET_CRS": target_crs}, output_name)


@register(C)
def run_centroids(input_layer, output_name="centroides"):
    """Centroides das feições."""
    return run_alg("native:centroids", {"INPUT": input_layer}, output_name)


@register(C)
def run_convex_hull(input_layer, output_name="fecho_convexo"):
    """Fecho convexo de cada feição."""
    return run_alg("native:convexhull", {"INPUT": input_layer}, output_name)


@register(C)
def run_simplify(input_layer, tolerance=1.0, output_name="simplificado"):
    """Simplifica geometrias (tolerância na unidade do CRS)."""
    return run_alg("native:simplifygeometries", {"INPUT": input_layer, "METHOD": 0,
                                                "TOLERANCE": tolerance}, output_name)


@register(C)
def run_spatial_join(input_layer, join_layer, predicate="intersects", join_type="one-to-many",
                     output_name="join_espacial"):
    """Junta atributos de join_layer por relação espacial. join_type: one-to-many|one-to-one."""
    return run_alg("native:joinattributesbylocation",
                   {"INPUT": input_layer, "JOIN": join_layer, "PREDICATE": _pred(predicate),
                    "METHOD": 1 if join_type == "one-to-one" else 0}, output_name)


@register(C)
def join_by_field(input_layer, field, join_layer, join_field, prefix="", output_name="join_atributos"):
    """Junta tabela/camada por campo em comum (join de atributos)."""
    return run_alg("native:joinattributestable",
                   {"INPUT": input_layer, "FIELD": field, "INPUT_2": join_layer,
                    "FIELD_2": join_field, "PREFIX": prefix}, output_name)


@register(C)
def join_by_nearest(input_layer, join_layer, neighbors=1, max_distance=None, output_name="vizinho_proximo"):
    """Junta atributos do(s) vizinho(s) mais próximo(s)."""
    p = {"INPUT": input_layer, "INPUT_2": join_layer, "NEIGHBORS": neighbors}
    if max_distance:
        p["MAX_DISTANCE"] = max_distance
    return run_alg("native:joinbynearest", p, output_name)


@register(C)
def extract_by_attribute(input_layer, field, operator, value=None, output_name="extraido"):
    """Extrai feições por atributo. operator: = != > >= < <= 'begins with' contains 'is null' 'is not null'."""
    if operator not in OPERATORS:
        raise ValueError(f"operator inválido. Use: {list(OPERATORS)}")
    return run_alg("native:extractbyattribute",
                   {"INPUT": input_layer, "FIELD": field, "OPERATOR": OPERATORS[operator],
                    "VALUE": "" if value is None else str(value)}, output_name)


@register(C)
def extract_by_expression(input_layer, expression, output_name="extraido"):
    """Extrai feições que satisfazem uma expressão QGIS."""
    return run_alg("native:extractbyexpression", {"INPUT": input_layer, "EXPRESSION": expression}, output_name)


@register(C)
def extract_by_location(input_layer, intersect_layer, predicate="intersects", output_name="extraido_local"):
    """Extrai feições por relação espacial. predicate: intersects contains disjoint equals touches overlaps within crosses."""
    return run_alg("native:extractbylocation", {"INPUT": input_layer, "INTERSECT": intersect_layer,
                                               "PREDICATE": _pred(predicate)}, output_name)


@register(C)
def extract_selected(input_layer, output_name="selecionadas"):
    """Cria nova camada só com as feições selecionadas."""
    return run_alg("native:saveselectedfeatures", {"INPUT": input_layer}, output_name)


@register("Seleção", "view")
def select_by_location(input_layer, intersect_layer, predicate="intersects", method="new"):
    """Seleciona feições por relação espacial. method: new|add|remove|within(refina seleção atual)."""
    lyr = get_vector(input_layer)
    run_alg("native:selectbylocation",
            {"INPUT": input_layer, "INTERSECT": intersect_layer, "PREDICATE": _pred(predicate),
             "METHOD": SEL_METHODS[method]})
    return {"selected_count": lyr.selectedFeatureCount()}


@register(C)
def fix_geometries(input_layer, output_name="geometrias_corrigidas"):
    """Corrige geometrias inválidas."""
    return run_alg("native:fixgeometries", {"INPUT": input_layer}, output_name)


@register(C)
def delete_duplicate_geometries(input_layer, output_name="sem_duplicatas"):
    """Remove feições com geometria duplicada."""
    return run_alg("native:deleteduplicategeometries", {"INPUT": input_layer}, output_name)


@register(C)
def multipart_to_singleparts(input_layer, output_name="partes_simples"):
    """Explode multipartes em partes simples."""
    return run_alg("native:multiparttosingleparts", {"INPUT": input_layer}, output_name)


@register(C)
def collect_geometries(input_layer, field=None, output_name="coletado"):
    """Agrupa feições em multipartes (opcionalmente por campo)."""
    return run_alg("native:collect", {"INPUT": input_layer, "FIELD": [field] if field else []}, output_name)


@register(C)
def polygons_to_lines(input_layer, output_name="linhas"):
    """Converte polígonos em linhas (contornos)."""
    return run_alg("native:polygonstolines", {"INPUT": input_layer}, output_name)


@register(C)
def lines_to_polygons(input_layer, output_name="poligonos"):
    """Converte linhas fechadas em polígonos."""
    return run_alg("native:linestopolygons", {"INPUT": input_layer}, output_name)


@register(C)
def layer_extent_polygon(input_layer, output_name="extensao"):
    """Cria um retângulo com a extensão da camada."""
    return run_alg("native:polygonfromlayerextent", {"INPUT": input_layer}, output_name)


@register(C)
def count_points_in_polygon(polygon_layer, point_layer, field="NUMPOINTS", output_name="contagem_pontos"):
    """Conta pontos dentro de cada polígono."""
    return run_alg("native:countpointsinpolygon",
                   {"POLYGONS": polygon_layer, "POINTS": point_layer, "FIELD": field}, output_name)


@register(C)
def voronoi_polygons(input_layer, output_name="voronoi"):
    """Polígonos de Voronoi (Thiessen) a partir de pontos."""
    return run_alg("native:voronoipolygons", {"INPUT": input_layer}, output_name)


@register(C)
def add_geometry_attributes(input_layer, output_name="com_geometria"):
    """Adiciona campos de área/perímetro (polígono) ou comprimento (linha), ou X/Y (ponto)."""
    return run_alg("native:exportaddgeometrycolumns", {"INPUT": input_layer, "CALC_METHOD": 0}, output_name)


@register(C)
def create_grid(extent_layer, spacing, grid_type="rectangle", output_name="grade"):
    """Cria grade sobre a extensão de uma camada. grid_type: point|line|rectangle|diamond|hexagon. spacing na unidade do CRS."""
    types = {"point": 0, "line": 1, "rectangle": 2, "diamond": 3, "hexagon": 4}
    if grid_type not in types:
        raise ValueError(f"grid_type deve ser {list(types)}")
    lyr = get_layer(extent_layer)
    e = lyr.extent()
    ext = f"{e.xMinimum()},{e.xMaximum()},{e.yMinimum()},{e.yMaximum()} [{lyr.crs().authid()}]"
    return run_alg("native:creategrid", {"TYPE": types[grid_type], "EXTENT": ext,
                                        "HSPACING": spacing, "VSPACING": spacing,
                                        "CRS": lyr.crs().authid()}, output_name)


@register(C)
def random_points_in_polygons(input_layer, points_number, output_name="pontos_aleatorios"):
    """Gera pontos aleatórios dentro dos polígonos (N por polígono)."""
    return run_alg("native:randompointsinpolygons",
                   {"INPUT": input_layer, "POINTS_NUMBER": points_number}, output_name)


# -------------------------------------------------------------------- raster
@register(R)
def clip_raster_by_mask(input_raster, mask_layer, output_name="raster_recortado", crop_to_cutline=True):
    """Recorta raster por camada de polígonos."""
    get_raster(input_raster)
    return run_alg("gdal:cliprasterbymasklayer",
                   {"INPUT": input_raster, "MASK": mask_layer, "CROP_TO_CUTLINE": crop_to_cutline,
                    "KEEP_RESOLUTION": True}, output_name)


@register(R)
def hillshade(input_raster, z_factor=1.0, output_name="sombreamento"):
    """Relevo sombreado a partir de MDE."""
    return run_alg("native:hillshade", {"INPUT": input_raster, "Z_FACTOR": z_factor}, output_name)


@register(R)
def slope(input_raster, z_factor=1.0, output_name="declividade"):
    """Declividade (graus) a partir de MDE."""
    return run_alg("native:slope", {"INPUT": input_raster, "Z_FACTOR": z_factor}, output_name)


@register(R)
def contours(input_raster, interval, output_name="curvas_de_nivel"):
    """Curvas de nível de um MDE (intervalo na unidade da elevação)."""
    return run_alg("gdal:contour", {"INPUT": input_raster, "BAND": 1, "INTERVAL": interval,
                                   "FIELD_NAME": "ELEV"}, output_name)


@register(R)
def polygonize_raster(input_raster, output_name="poligonizado"):
    """Converte raster em polígonos."""
    return run_alg("gdal:polygonize", {"INPUT": input_raster, "BAND": 1, "FIELD": "DN"}, output_name)


@register(R)
def zonal_statistics(polygon_layer, raster_layer, stats=("mean",), prefix="_", output_name="estatistica_zonal"):
    """Estatísticas de raster por polígono. stats: count sum mean median stdev min max range majority minority variety variance."""
    codes = []
    for s in stats:
        if s not in STATS:
            raise ValueError(f"stat inválida '{s}'. Use {list(STATS)}")
        codes.append(STATS[s])
    return run_alg("native:zonalstatisticsfb",
                   {"INPUT": polygon_layer, "INPUT_RASTER": raster_layer, "RASTER_BAND": 1,
                    "COLUMN_PREFIX": prefix, "STATISTICS": codes}, output_name)


@register(R, "info")
def raster_statistics(raster_layer, band=1):
    """Mín, máx, média e desvio de uma banda do raster."""
    from qgis.core import QgsRasterBandStats
    r = get_raster(raster_layer)
    st = r.dataProvider().bandStatistics(int(band), QgsRasterBandStats.All)
    return {"min": st.minimumValue, "max": st.maximumValue, "mean": st.mean, "stdev": st.stdDev}
