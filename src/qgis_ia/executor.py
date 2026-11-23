# -*- coding: utf-8 -*-
"""
Executor - Executa planos JSON no QGIS (sandbox seguro)
"""
import traceback
from .actions import layers, processing, layout, expressions, slu, redesenho


ACTIONS = {
    # Camadas
    "list_layers": layers.list_layers,
    "select_by_expression": layers.select_by_expression,
    "create_memory_layer": layers.create_memory_layer,
    "add_vector_layer": layers.add_vector_layer,
    "add_raster_layer": layers.add_raster_layer,
    "remove_layer": layers.remove_layer,
    "zoom_to_layer": layers.zoom_to_layer,
    "export_layer": layers.export_layer,
    "rename_layer": layers.rename_layer,
    "duplicar_camada_com_ra": layers.duplicar_camada_com_ra,

    # Geoprocessamento (vetor)
    "run_buffer": processing.run_buffer,
    "run_intersection": processing.run_intersection,
    "run_difference": processing.run_difference,
    "run_union": processing.run_union,
    "run_dissolve": processing.run_dissolve,
    "run_clip": processing.run_clip,
    "run_merge_layers": processing.run_merge_layers,
    "run_reproject": processing.run_reproject,
    "run_centroids": processing.run_centroids,
    "run_convex_hull": processing.run_convex_hull,
    "run_simplify": processing.run_simplify,
    "run_spatial_join": processing.run_spatial_join,

    # Acesso genérico a QUALQUER algoritmo de Processing do QGIS
    "run_algorithm": processing.run_algorithm,
    "list_algorithms": processing.list_algorithms,

    # Layout / exportação
    "export_layout_pdf": layout.export_pdf,
    "export_layout_image": layout.export_image,
    "list_layouts": layout.list_layouts,

    # Expressões / atributos
    "calculate_field": expressions.calculate_field,
    "filter_layer": expressions.filter_layer,
    "clear_filter": expressions.clear_filter,
}

# Planos de Serviço SLU-DF (Anexo G do edital)
ACTIONS.update(slu.TOOLS)
ACTIONS.update(redesenho.TOOLS)


def execute_plan(plan):
    """Executa lista de passos do plano. Retorna lista de resultados."""
    results = []
    for step in plan.get("steps", []):
        action_name = step.get("action")
        params = step.get("params", {})

        if action_name not in ACTIONS:
            results.append({
                "success": False,
                "error": f"Ação não permitida: {action_name}. Disponíveis: {list(ACTIONS.keys())}"
            })
            break

        try:
            func = ACTIONS[action_name]
            result = func(**params)
            results.append({"success": True, "result": result})
        except Exception as e:
            results.append({
                "success": False,
                "error": traceback.format_exc()
            })
            break
    return results