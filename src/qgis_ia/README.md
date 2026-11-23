# QGIS_IA

Plugin de IA para QGIS, com dois modos de uso:

1. **Servidor MCP** — o Claude Desktop, o Claude Code ou outro cliente MCP opera o
   projeto aberto no seu QGIS. É o modo principal, equivalente ao QGIS MCP.
2. **Painel de chat** — você descreve a tarefa e o plugin executa, usando sua própria
   chave de API (`ANTHROPIC_API_KEY`).

Versão 2.1.0. Antes chamava-se "Claude AI Assistant" (pasta `qgis_claude_ai`).

## Instalação

O plugin já está em `…/QGIS3/profiles/default/python/plugins/qgis_ia`.

1. Abra o QGIS.
2. Em `Complementos` → `Gerenciar e Instalar Complementos` → aba `Instalados`,
   **desmarque o antigo "Claude AI Assistant"** e **marque "QGIS_IA"**.
   Se o QGIS já estava aberto, feche e abra de novo para ele enxergar a pasta nova.

## Modo servidor MCP

**Não precisa de `uv`, nem de `pip`, nem de internet.** A ponte usa só a biblioteca
padrão do Python e roda com o Python que já vem no QGIS.

1. No QGIS, abra o painel **QGIS_IA** (menu `Complementos` → `QGIS_IA`, ou o ícone na
   barra de ferramentas).
2. Clique em **Iniciar servidor**.
3. Clique em **Copiar comando (Claude Code)** ou **Copiar JSON (Claude Desktop)**:
   - *Claude Code*: cole o comando no terminal e tecle Enter.
   - *Claude Desktop*: cole o JSON em `claude_desktop_config.json`
     (`%APPDATA%\Claude\claude_desktop_config.json`), depois feche e reabra o app.
4. Peça ao Claude para chamar a ferramenta `ping`. Resposta esperada: `{"pong": true}`.

Mantenha o QGIS aberto e o servidor iniciado enquanto usar.

### Como funciona

```
Claude  ⇄  mcp_server.py (stdio, fora do QGIS)  ⇄  socket 127.0.0.1  ⇄  plugin no QGIS  ⇄  PyQGIS
```

O servidor escuta **apenas em 127.0.0.1** (porta 9876, ou a próxima livre) e exige um
token aleatório, gerado a cada início e gravado em `~/.qgis_ia/server.json`. Ao parar
o servidor, o arquivo é apagado e o token deixa de valer.

### Segurança

- **Somente leitura** (caixa no painel): bloqueia tudo que grava arquivo, altera dados
  ou remove coisas — `remove_layer`, `export_layer`, `calculate_field`, `run_algorithm`,
  `export_layout_*`, `save_project`, `add_features`, `update_features`,
  `delete_features`, `add_field`, `delete_field`.
- **Permitir execução de código Python**: começa desligada e pede confirmação. Ligada,
  libera `execute_code`, que roda PyQGIS arbitrário — qualquer coisa que o QGIS faz,
  inclusive ler e apagar arquivos. Ligue só quando precisar e desligue depois.
- As ações rodam no thread principal do QGIS. Operações pesadas deixam a interface
  parada enquanto executam.

## As 54 ferramentas

**Inspeção** — `ping`, `get_project_info`, `get_layer_info`, `get_features`,
`get_field_statistics`, `get_unique_values`, `get_raster_stats`, `get_algorithm_help`,
`render_map`, `list_algorithms`

**Camadas** — `list_layers`, `add_vector_layer`, `add_raster_layer`, `add_basemap`,
`create_memory_layer`, `remove_layer`, `rename_layer`, `export_layer`,
`set_layer_visibility`, `zoom_to_layer`, `set_canvas_extent`, `save_project`

**Edição** — `add_features`, `update_features`, `delete_features`, `add_field`,
`delete_field`, `calculate_field`, `select_by_expression`, `filter_layer`, `clear_filter`

**Geoprocessamento** — `run_buffer`, `run_intersection`, `run_difference`, `run_union`,
`run_dissolve`, `run_clip`, `run_merge_layers`, `run_reproject`, `run_centroids`,
`run_convex_hull`, `run_simplify`, `run_spatial_join`, `run_algorithm`

`run_algorithm` alcança **qualquer** algoritmo do Processing (native, qgis, gdal, grass).
Use `list_algorithms` para achar o id e `get_algorithm_help` para os nomes dos parâmetros.

**Simbologia e mapas** — `set_layer_style`, `set_categorized_style`,
`set_graduated_style`, `set_labels`, `set_layer_opacity`, `list_layouts`,
`create_print_layout`, `export_layout_pdf`, `export_layout_image`

**Planos de Serviço SLU-DF** — `slu_info_edital`, `slu_gerar_plano`, `slu_criar_gdb`,
`slu_validar_gdb`, `slu_preencher_atributos`, `slu_exportar_xlsx`,
`slu_gerar_programacao_trimestral`, `slu_gerar_docx`, `slu_exportar_shapefile`

**Avançado** — `execute_code` (desligada por padrão)

## Planos de Serviço SLU-DF (Anexo G)

Seguem o *Roteiro de Elaboração dos Planos de Serviço — Padrão de Construção dos Dados
Geográficos Vetoriais* (Anexo G do Edital do Pregão Presencial nº 90005/2026, SLU-DF).
As regras ficam em `edital_slu.py`; as ações, em `actions/slu.py`.

| Arquivo do plano (item 3.1) | Ferramenta |
|---|---|
| `.gdb` (CC0X, CS0X, VA0X, VE0X, MA0X, ME0X, VL0X, LE0X, FR0X, PE0X, TR0X) | `slu_criar_gdb` |
| `.xlsx` tabela de atributos | `slu_exportar_xlsx` |
| `.xlsx` programação trimestral (P3, P4, P7–P12) | `slu_gerar_programacao_trimestral` |
| `.docx` texto descritivo (Arial 12/14, edital 7.8) | `slu_gerar_docx` |
| `.shp` (edital 7.8 pede mapas em shapefile) | `slu_exportar_shapefile` |
| tudo de uma vez | `slu_gerar_plano` |

Fluxo para um plano já desenhado: `slu_preencher_atributos` (faz backup do .gdb) →
`slu_validar_gdb` com `relatorio_xlsx` → corrigir → `slu_gerar_plano` com `gdb_existente`.

O que a validação confere: camadas e campos obrigatórios, SIRGAS 2000/UTM 23S, `lote`,
Código Circuito (dígitos de lote/serviço/turno, duplicidade), Código RA (1–35 e RAs do
lote pelo Quadro 01 do edital), Nome do Circuito (RA + código + lógica D1/SSEG/A3SQS/MSEG;
Plano Piloto como Asa Norte/Asa Sul), Frequência × dias, Ciclo × Semana, horários, Tipo de
Serviço/Equipamento (Tabela 4), Endereçamento, e as regras topológicas: Single Part,
50–130 m (coleta) / 50–200 m (varrição), Must Not Overlap/Intersect/Self-Intersect,
linhas e pontos dentro do polígono do circuito, ponto sobre linha, 1 início + 1 fim por
circuito, 1 linha de quantificação por circuito. *Must Not Have Dangles* não é conferida
(depende de exceções que só o técnico marca).

Decisões tomadas onde o Anexo G e os modelos divergem:
- O polígono de CC/CS ganhou `ciclo` e `flag_semana` (o item 4.4.5 exige; o modelo antigo
  não tinha). VE usava `semana_execucao`: o padrão adotado é `flag_semana` (modelo VA); a
  validação aceita os dois.
- Serviços sob demanda não têm modelo de .gdb: camada `lm_area_circuito_planejado` com os
  campos da seção 6.3.2 (inclui `numero_equipes`).
- Numeração de serviços: a do Anexo G (P1–P12). O Termo de Referência usa outra (P0–P20).

Testes: `python-qgis-ltr.bat tests\test_slu.py` (não precisa do QGIS aberto).

## Painel de chat

Precisa de `ANTHROPIC_API_KEY` nas variáveis de ambiente do Windows (cobra por uso,
à parte da assinatura). Sem chave nenhuma, o plugin avisa e não executa nada.

Se houver também `OPENROUTER_API_KEY`, ela é usada como reserva quando a Anthropic
falha — e o painel avisa no chat, porque seus dados passam a ir para outro provedor.

## Arquivos

| Arquivo | Função |
|---|---|
| `__init__.py` | Entrada do plugin: menu, barra e ciclo de vida |
| `dockwidget.py` | Painel: chat e controles do servidor |
| `mcp_socket.py` | Servidor socket dentro do QGIS |
| `mcp_server.py` | Ponte MCP (stdio), rodada pelo cliente, sem dependências |
| `protocol.py` | Formato das mensagens, token e travas de segurança |
| `tool_specs.py` | Nome, descrição e schema de cada ferramenta |
| `executor.py` | Executa o plano JSON vindo do chat |
| `ai_client.py` | Cliente da API para o modo chat |
| `actions/` | As funções que mexem no QGIS |

## Próxima etapa

Rotas ainda não estão implementadas. Quando for a hora: definir origem dos dados
(rede viária própria, OSM ou serviço externo), tipo de roteamento (ponto a ponto,
várias paradas, área de alcance) e então acrescentar as ferramentas em
`actions/routing.py`.
