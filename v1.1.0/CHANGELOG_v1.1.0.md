# v1.1.0 — 2026-11-19

## Por que o plugin "só funcionava com alguns comandos"
- O prompt da IA e a lista de ações eram escritos à mão e divergiam (ações descritas mas não registradas).
- A IA decidia o plano às cegas: não via os campos das camadas nem os parâmetros reais dos algoritmos,
  e não recebia os resultados/erros de volta para corrigir.
- A execução rodava em QThread (o QGIS não é thread-safe para addMapLayer/Processing).

## O que mudou
- **Registro único de ações** (`registry.py`): cada função decorada vira ação permitida *e* entra no
  prompt automaticamente. 29 → 87 ações.
- **Loop de agente**: a IA recebe os resultados, consulta (`list_algorithms` → `describe_algorithm`),
  e corrige erros sozinha (até 8 rodadas / 3 correções).
- **Contexto rico**: camadas, geometria, CRS, nº de feições e campos vão em cada pedido.
- **`run_algorithm` robusto**: resolve camadas pelo tipo real do parâmetro (inclusive listas e
  `{"layer":..., "selected_only":true}`), saídas temporárias automáticas, `output_path`, valida nomes
  de parâmetro e sugere correções. Bloqueia `script:`, `model:` e algoritmos de código arbitrário.
- **Execução na thread principal**; só a chamada de IA fica em thread.
- **Confirmação** antes de ações que alteram/apagam dados (editar campos, apagar feições, remover camada...).
- Novas ações: atributos (get_features, estatísticas, add/delete/rename_field, add/delete_features),
  seleção, extrações, joins, geometrias, grade, raster (recorte, sombreado, declividade, curvas,
  zonal), estilo (cor, categorizado, graduado, rótulos), CRS do projeto, mapa base, CSV, sublayers
  de .gdb/.gpkg, layout automático (título, legenda, escala), salvar projeto.
- Botões Parar e Limpar; histórico de conversa na sessão.
