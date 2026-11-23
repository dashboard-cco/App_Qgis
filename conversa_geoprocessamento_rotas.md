# Conversa: IA para geoprocessamento e rotas de serviços urbanos

**Período registrado:** 16 a 19 de novembro de 2026  
**Idioma:** português  
**Objetivo:** registrar o contexto, os dados, as decisões e as análises realizadas para planejar rotas de coleta de resíduos e varrição com IA, usando QGIS ou ArcGIS Desktop.

> Este documento reúne os pontos substantivos da conversa e os resultados técnicos. Não reproduz mensagens automáticas da interface nem cada chamada de ferramenta.

## 1. Necessidade apresentada

O usuário trabalha com rotas de:

- coleta convencional;
- coleta seletiva;
- varrição manual;
- varrição mecanizada.

A ideia é conversar com a IA em linguagem simples para criar, revisar e analisar rotas. A operação usa ArcGIS Desktop 10.8, mas pode utilizar QGIS. O formato oficial de entrega deve continuar sendo File Geodatabase (.gdb).

## 2. Fluxo de trabalho discutido

A IA funcionaria como uma interface conversacional que interpreta pedidos, verifica parâmetros e aciona operações GIS controladas. O GIS calcula e registra o resultado; uma pessoa revisa a rota no mapa antes da entrega.

1. A pessoa pede a criação, ajuste ou análise de uma rota.
2. O assistente confirma a modalidade, área, turno, pontos de início/fim, veículo e regras relevantes.
3. QGIS ou ArcGIS executa as ferramentas de rede configuradas.
4. A pessoa revisa o mapa e corrige exceções operacionais.
5. As camadas e resumos acordados são exportados para uma .gdb.

O QGIS foi considerado uma boa base para automação nova com PyQGIS e Processing. O ArcGIS Desktop 10.8 pode continuar como referência ou destino, mas o ArcMap 10.8 usa Python 2.7, o que restringe bibliotecas e integrações recentes. A compatibilidade de leitura/gravação de File Geodatabase pelo QGIS deve ser validada com cópias das bases reais.

## 3. Geodatabases de serviços

Na pasta indicada pelo usuário foram encontradas quatro bases:

- CC01.gdb
- CS01.gdb
- VA01.gdb
- VE01.gdb

### CC01 e CS01

As camadas observadas incluem:

- st_circuito_planejado — circuitos/rotas planejados;
- lm_area_circuito_planejado — áreas dos circuitos;
- st_circuito_inicio_fim — pontos de início e término dos circuitos;
- st_conteiner — pontos de coleta em contêineres semienterrados;
- camadas auxiliares de erros e edição do Network Dataset.

### VA01 e VE01

Têm camadas de circuitos planejados, áreas planejadas, início/fim e camadas auxiliares. Também incluem st_quantificacao.

O usuário explicou que st_quantificacao é a soma linear de sarjeta dos circuitos de varrição.

### Referência espacial

As geodatabases examinadas usam SIRGAS 2000 / UTM zona 23S, EPSG:31983.

## 4. Rede de ruas para cálculo

O usuário informou que havia uma rede Network Analyst em Vias, utilizada no ArcGIS, e que precisava ser reconstruída no QGIS. Também esclareceu que a rede não tinha regra de circulação. Foi discutido o uso do OpenStreetMap (OSM), e não a cópia de informações do Google Maps para uma geodatabase externa.

### Rede atualizada examinada

- RedeNetworkAnalyst.gdb
- camada ArquivoRua
- 130.465 feições
- geometria linear 3D medida, lida na análise como MultiLineString Z
- EPSG:31983
- campos principais: ID, compriment, tempo_s, tempo_m e Shape_Length

O usuário informou que os custos de tempo estavam em segundos e minutos. Os valores amostrados confirmaram tempo_s em segundos e tempo_m em minutos decimais. A camada pode ser usada como base para calcular caminhos, mas não contém o sentido de circulação.

## 5. OpenStreetMap e QuickOSM

O usuário instalou QuickOSM, baixou a camada de ruas e salvou um GeoPackage:

- vias_osm_referencia.gpkg
- camada Camada_OSM
- 127.395 feições lineares
- EPSG:31983
- atributos relevantes: osm_id, highway, name, oneway, junction, surface, tracktype, access, hgv e motor_vehicle, entre outros.

A atribuição © OpenStreetMap contributors e referência à licença ODbL devem acompanhar o uso/distribuição dos dados, de acordo com as condições OSM.

### Estatísticas do campo oneway

| Valor | Feições | Percentual aproximado |
|---|---:|---:|
| vazio | 97.698 | 76,7% |
| yes | 26.922 | 21,1% |
| no | 2.773 | 2,2% |
| -1 | 1 | menos de 0,01% |
| reversible | 1 | menos de 0,01% |

oneway=yes indica o sentido em que a linha OSM foi desenhada; oneway=-1 indica o sentido oposto. O campo vazio normalmente significa ausência de marcação de mão única e o padrão costuma ser bidirecional, mas existem exceções, incluindo rotatórias (junction=roundabout) e algumas classes de via. A direção depende também da orientação geométrica da linha.

Foram encontrados 1.299 elementos junction=roundabout; 1.053 deles tinham oneway vazio. Por isso, rotatórias não devem ser tratadas automaticamente como mão dupla só porque oneway está vazio.

### Classes de vias e pavimento

A camada contém vias que não devem entrar automaticamente numa rede de caminhões, como footway, path, steps, cycleway e pedestrian, além de track e linhas auxiliares.

| Atributo | Observação |
|---|---:|
| surface vazio | 95.721 (75,1%) |
| superfícies explicitamente não pavimentadas/terra | cerca de 5.652 (4,4%) |
| tracktype vazio | 127.128 (99,8%) |
| highway=track | 2.544 |

surface vazio não significa pavimentada: significa que o OSM não informa a superfície. Classes track e valores como unpaved, ground, dirt, gravel ou compacted devem gerar revisão de acesso/adequação do veículo, não exclusão automática.

## 6. Cruzamento preliminar entre ArquivoRua e OSM

Foi feita uma análise espacial de vizinho mais próximo. A proximidade espacial é forte em grande parte da área, mas não prova que as duas linhas representem o mesmo trecho nem que tenham a mesma segmentação.

| Distância até a linha OSM mais próxima | Trechos da rede |
|---|---:|
| até 1 m | 119.041 |
| até 2 m | 125.986 |
| até 5 m | 129.060 |
| acima de 5 m | 1.405 |

As fontes não estão sempre segmentadas da mesma forma. Uma linha OSM pode corresponder a vários trechos de ArquivoRua, ou uma linha da rede pode se relacionar com várias linhas OSM. A rede não tinha campo de nome de via para uma junção simples por nome.

### Camada de revisão preliminar

Foi criado o arquivo ArquivoRua_OSM_Revisao.gpkg, camada ArquivoRua_OSM_Revisao, com 130.465 feições. Mantém os atributos da rede e acrescenta os atributos do candidato OSM mais próximo, distâncias e indicadores de revisão.

| status_match | Feições | Interpretação |
|---|---:|---|
| CANDIDATO_ALINHADO | 14.490 | candidato mais bem alinhado, ainda sujeito a conferência |
| PROXIMO_REVISAR_SEGMENTACAO | 111.496 | linha próxima, mas a correspondência não foi confirmada devido à segmentação |
| PROXIMO_REVISAR | 3.074 | linha próxima que requer revisão |
| SEM_CORRESPONDENCIA_5M | 1.405 | nenhum candidato até 5 m |

orient_linha compara a orientação projetada da linha candidata com a linha de ArquivoRua. sentido_cand representa valores candidatos, não uma regra operacional homologada.

## 7. Proposta de sentidos solicitada

O usuário pediu para ignorar os 1.405 casos sem correspondência e propor sentidos para todos os demais. Foi criado um novo arquivo, sem alterar as geodatabases de origem:

- ArquivoRua_OSM_Sentidos_Propostos.gpkg
- camada Sentidos_Propostos
- 129.060 feições

A proposta inclui os campos sentido_proposto, regra_sentido, confianca_proposta, perfil_veiculo e alerta_superficie.

### Contagem das propostas

| sentido_proposto | Feições | Interpretação |
|---|---:|---|
| FT | 18.260 | sentido da linha de ArquivoRua |
| TF | 17.186 | sentido contrário à linha de ArquivoRua |
| B | 3.813 | mão dupla explicitamente indicada no OSM (oneway=no) |
| B_PADRAO_OSM | 89.655 | mão dupla inferida como padrão quando não há tag nem regra implícita identificada |
| REVISAR_ORIENTACAO | 139 | candidato OSM indica mão única, mas a orientação não foi determinada com segurança |
| REVISAR_ROTATORIA | 7 | orientação de rotatória não determinada |

### Origem da regra

| regra_sentido | Feições |
|---|---:|
| OSM_ONEWAY_YES | 33.369 |
| OSM_ONEWAY_MENOS1 | 5 |
| OSM_ONEWAY_NO | 3.813 |
| OSM_ROTATORIA_SENTIDO_DA_LINHA | 2.218 |
| OSM_PADRAO_SEM_TAG_BIDIRECIONAL | 89.655 |

FT e TF foram calculados em relação à direção digitalizada de ArquivoRua. Para oneway=-1, o sentido OSM foi invertido em relação à linha da rede. Para rotatórias sem oneway, o sentido da linha OSM foi usado como proposta implícita quando a orientação pôde ser determinada.

### Confiança e ressalvas

| confianca_proposta | Feições |
|---|---:|
| MELHOR_CANDIDATO_GEOMETRICO | 14.490 |
| BAIXA_SEGMENTACAO | 111.355 |
| BAIXA_DISTANCIA | 3.069 |
| INDETERMINADA | 146 |

A maioria das propostas tem baixa confiança geométrica por causa da segmentação diferente. B_PADRAO_OSM é inferência pela ausência de tag, não indicação explícita nem verificação em campo. Os 146 casos indeterminados não receberam FT/TF definitivo.

### Adequação a veículos e superfície

| Aviso | Feições |
|---|---:|
| perfil_veiculo=VALIDAR_ACESSO_DO_VEICULO | 4.843 |
| perfil_veiculo=VALIDAR_SE_VIA_ATENDE_O_SERVICO | 433 |
| alerta_superficie=SUPERFICIE_NAO_PAVIMENTADA_OU_TRACK | 5.612 |
| alerta_superficie=SUPERFICIE_NAO_INFORMADA | 85.336 |
| alerta_superficie=SUPERFICIE_TAGUEADA | 38.112 |

As propostas não devem ser usadas diretamente como regras finais de tráfego antes de revisar correspondência, perfil do veículo, sinalização e exceções operacionais. Coleta convencional/seletiva, varrição mecanizada e varrição manual podem exigir perfis de acesso diferentes.

## 8. Arquivos citados ou produzidos

Arquivos de entrada mencionados:

- CC01.gdb, CS01.gdb, VA01.gdb e VE01.gdb;
- Vias\RedeNetworkAnalyst.gdb;
- Vias\RedeNetworkAnalystQgis.gdb;
- Vias\vias_osm_referencia.gpkg.

Arquivos de análise criados:

- Vias\ArquivoRua_OSM_Revisao.gpkg;
- Vias\ArquivoRua_OSM_Sentidos_Propostos.gpkg.

Durante a análise, os arquivos estavam no caminho E:\Relatorios\Hermes\Plataforma_qgis\Vias\. Na sessão atual de 19/11/2026, esse caminho não está montado/acessível. Este Markdown registra o histórico e os resultados, mas não confirma que os GeoPackages gerados continuam disponíveis no ambiente atual.

## 9. Próximas etapas recomendadas

1. Abrir ArquivoRua_OSM_Sentidos_Propostos.gpkg no QGIS e simbolizar por sentido_proposto e confianca_proposta.
2. Conferir os 14.490 melhores candidatos e amostras das classes de baixa confiança.
3. Investigar correspondência de múltiplos trechos OSM por feição de ArquivoRua.
4. Revisar REVISAR_ORIENTACAO, rotatórias, sentidos sinalizados e vias track/não pavimentadas com a equipe operacional ou fonte oficial.
5. Confirmar regras de acesso para caminhões, equipamentos mecanizados e varrição manual.
6. Só então gerar um campo de circulação homologado e exportar uma camada final para uma nova .gdb de produção, preservando a geodatabase original.
7. Registrar atribuição OSM e licença ODbL na documentação/entrega.

## 10. Síntese

A conversa definiu um fluxo em que a IA interpreta pedidos e aciona ferramentas GIS, com QGIS como opção para reconstrução da análise e File Geodatabase como entrega. Foram examinadas as estruturas de rotas, a rede de ruas e a camada OSM. A proposta foi criada em GeoPackage separado para revisão, cobre 129.060 trechos e exclui os 1.405 sem correspondência até 5 m. A maior parte das propostas ainda requer validação por causa de segmentação diferente e baixa confiança espacial; os dados não foram incorporados às geodatabases de serviço.
