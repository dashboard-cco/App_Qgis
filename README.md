# QgisIA

Plugin QGIS com assistente de IA (Claude) para geoprocessamento.

A partir da v2.1.0, gera e confere os **Planos de Serviço do SLU-DF** no padrão do
Anexo G do Edital do Pregão Presencial nº 90005/2026 (pasta `Edital/`): File Geodatabase
(.gdb), tabelas (.xlsx), texto (.docx) e shapefile. Detalhes em
[src/qgis_ia/README.md](src/qgis_ia/README.md).

## Janela inicial: tipos de projeto

O ícone **QGIS_IA** abre uma janela com quatro tipos de projeto: **Coleta Convencional** (P1),
**Coleta Seletiva** (P2), **Varrição Manual** (P5) e **Varrição Mecanizada** (P6).

1. Clique no tipo e escolha a **pasta com os arquivos** (edital, plano atual .gdb, planilhas…).
   O app lê a pasta e mostra o que achou: documentos, planos e camadas (serviço, lote,
   circuitos, turnos e km de vias de cada .gdb) e planilhas.
2. **Detalhes** já vêm sugeridos pelo que foi lido: lote, turnos, plano de partida (o plano
   atual da pasta ou um novo vazio no padrão do edital), empresa, pasta de saída e o texto do
   plano por seção (o que é o serviço, material, horários dos turnos, caminhões do Anexo R,
   resumo dos circuitos). Confira e complete.
3. **Criar plano** gera o plano de serviço do edital (.gdb, tabela .xlsx e texto .docx) e
   confere o .gdb com as regras do Anexo G (planilha de conferência). *Ler o edital com IA /
   frota e equipe* abre os Planos do Contrato já com a pasta e os documentos do projeto.

**Criar Todos** (botão da janela inicial) serve para **qualquer licitação**. Escolha a pasta
do contrato, mesmo que tenha só o edital.

- **Perfil do contrato.** Tudo sai do perfil (`contrato.json`), que o Claude monta lendo o
  edital (botão *Ler o edital com o Claude*). Ele traz os serviços, lotes, camadas, frota,
  pessoal, turnos, município/UF e, para cada arquivo exigido, o **padrão do nome**
  (ex.: `{sigla}{lote}.gdb`), o formato, as **seções** do texto e **como fazer**. O edital do
  SLU-DF (Pregão 90005/2026) já tem perfil pronto, e para ele o app usa o gerador do Anexo G.
- **Planos que o contrato pede.** Em qualquer edital, os planos são **os documentos que o
  edital exige**: ex.: "Plano de Trabalho Operacional" dos itens 1.1 a 1.5, com as seções
  pedidas. Os arquivos do mesmo conjunto de serviços (texto, mapa, tabela) ficam juntos, um
  plano por lote. O **Claude redige cada seção** a partir das páginas do edital e dos anexos
  citadas no perfil, com a frota, o pessoal e os dados da empresa. O que só a empresa ou o
  órgão definem sai em vermelho como `[A DEFINIR: …]`. Quando o documento pede setorização ou
  rotas, o plano ganha um mapa `.gpkg` (setores, rotas e pontos, ou as camadas do edital)
  sobre as vias do OpenStreetMap, com **circuitos e ordem de passagem** (ver
  *Dimensionamento* abaixo). No SLU-DF continua um plano por serviço e lote (Anexo G).
  Cada um mostra de onde vem: plano atual da pasta (copiado; o original não muda), **vias do
  OpenStreetMap** quando não há plano (o limite do município vem do IBGE, e tudo fica em
  `Base/`), ou só documentos.
- **Problemas**, cada um com a solução sugerida. Lotes e planos podem ser marcados ou
  desmarcados, e a escolha fica guardada na pasta (`criar_todos.json`).
- **Etapas de *Criar*:**
  - adequação de **frota e jornada**, quando a pasta tem o histórico de operação
    (ex.: `TabelaPadrão.xlsx`);
  - **correção automática**: no SLU, preenche os campos calculáveis e divide as linhas acima
    de 130/200 m; em outro edital, cria as camadas e campos que faltam e põe os valores
    padrão;
  - **conferência** com as regras do edital;
  - tabela `.xlsx`;
  - texto `.docx` com as seções do edital.
- **Texto do plano.** A frota e o pessoal vêm do edital. Sem placa, os veículos são
  identificados por **código** (`CC01-D01` = serviço + lote, turno D/N e número). Empresa,
  contatos e procedimentos vêm da **`planilha_modelo_empresa.xlsx`** da pasta; se ela não
  existir, o app cria um modelo já preenchido com a frota e o pessoal do edital.
- **Resultado:** a planilha `Criar_Todos_<data>.xlsx`, com as abas Planos e Problemas.

### Dimensionamento, circuitos e ordem de passagem

Botão **📐 Dimensionamento** (abre sozinho antes do primeiro *Criar*): a análise de cada
serviço **antes** de criar, com os valores do edital (dá para mudar e *Recalcular*):

- **Coleta (domiciliar, seletiva):** veículos por turno, dias por semana, frequência
  (diária no centro, trissemanal nos demais… como diz o edital), jornada, tempo fora do
  circuito, velocidade, viagens por turno, carga por viagem e t/mês → **capacidade de um
  circuito** (km e t). Cada bairro (km de vias + população do IBGE) pede um nº de circuitos;
  bairros pequenos juntam com o vizinho de mesma frequência, os grandes são divididos (o
  circuito fica dentro dos bairros). A frota fecha a conta: cada veículo-turno faz 1 circuito
  diário, 2 trissemanais (`-SQS` seg/qua/sex e `-TQS` ter/qui/sáb, vizinhos), 3 bissemanais
  ou 6 semanais. Se a frota não der, o app avisa quanto passa da capacidade (ponto para o
  órgão).
- **Varrição manual (feita a pé):** km/mês ÷ dias ÷ equipes = km por equipe/dia. O km do
  edital é de **sarjeta** (campo *Sarjetas por via* = 2: cada rua conta os dois lados; use 1
  se o edital medir km de rua). Só entram ruas com casas (setor do IBGE com pelo menos 15
  domicílios por km de via): estradas e vias sem calçada ficam de fora. Bairros de varrição
  diária (centro) primeiro; nas outras equipes, as ruas de cada bairro são escolhidas
  **juntas** (começa na avenida mais movimentada e cresce rua vizinha por rua vizinha), para
  a equipe andar pouco entre uma rua e outra. O percurso a pé ignora a mão de direção,
  começa no próprio circuito e é repartido entre as **duplas**.
- **Varrição mecanizada:** avenidas; km por varredeira/turno (também em sarjetas) →
  circuitos em rodízio.
- A varrição manual e a mecanizada saem **sempre em arquivos separados** (pasta, mapa,
  planilha e texto próprios), mesmo quando o edital pede um documento só.
- **Drenagem, capina…:** uma área por equipe.

**Divisas dos circuitos:** cada circuito é feito de **quadras inteiras** (polígonos fechados
pelas vias e pelo limite do município), então a divisa entre dois circuitos é sempre uma via
ou o limite do município, nunca o meio de uma quadra.

**Base** (em `App_Qgis/Base/`, baixada uma vez): limite (IBGE), vias (OpenStreetMap),
**setores censitários do Censo 2022 com população** (lidos direto do servidor do IBGE, só o
município) e **bairros**: os do IBGE quando a prefeitura informou; senão, cada setor
censitário vai para o ponto de bairro do OSM mais próximo. `bairros.gpkg` tem o campo
`frequencia` (diaria, trissemanal, bissemanal, semanal, quinzenal ou nao): mude no QGIS e
recalcule.

**Tratamento das vias do OSM** (logo depois de baixar, e uma vez nos arquivos baixados antes):
tira as linhas duplicadas (mesma geometria, em qualquer sentido, e trechos sobrepostos) e
quebra as linhas em todos os encontros, inclusive pontas que encostam no meio de outra via
("T"). Viadutos e túneis que só se cruzam, sem nó em comum, não são quebrados. O arquivo fica
com um trecho por linha (campo `trecho`).

**Ordem de passagem** (roteirização por arcos, "carteiro chinês"): o percurso passa por
todas as vias do circuito e volta ao início, repetindo o mínimo (deslocamento), preferindo a
mão de direção. No mapa: `setores` (circuito, veículo, turno, dias, frequência, bairros, km,
km de deslocamento, t por coleta, horas) e `rotas` (um trecho por linha, campo `ordem`,
`via`, `tipo` serviço/deslocamento e `dupla`). Planilha `<plano>_circuitos.xlsx`: abas
Dimensionamento, Circuitos e Itinerários (rua a rua).

**Textos (.docx)** no padrão visual da Valor Ambiental / CCIO (o mesmo do DocumentoPadrãoCCIO):
faixa verde, logo e cabeçalho em três linhas, rodapé com a página, títulos verdes em Arial,
tabelas com cabeçalho verde e linhas zebradas, `[A DEFINIR]` em vermelho. O logo é lido de
`~/.app_qgis/logo_empresa.png` (fora do Git). Quando o plano tem circuitos, o texto ganha o
**Anexo A — Dimensionamento e circuitos** (a conta e a tabela dos circuitos). Os planos do
padrão SLU (Anexo G) continuam no formato que o edital do SLU exige.

Os detalhes ficam salvos na pasta (`qgis_ia_projeto.json`) e o projeto aparece em
*Projetos recentes*. O assistente por mensagens (chat) e os Planos do Contrato continuam no
menu *QGIS_IA* e nos botões da janela inicial.

## Planos do Contrato (em desenvolvimento)

Janela própria no QGIS (menu *QGIS_IA → Planos do Contrato*) para criar o plano que o
contrato pede, a partir do edital e das especificações técnicas:

1. **Documentos** — coloque o edital, os anexos e as especificações (PDF, DOCX ou TXT).
2. **Requisitos** — a IA lê tudo e monta o perfil do contrato (`contrato.json`): serviços,
   lotes, camadas e campos exigidos, entregáveis, insumos, regras e pendências, cada item com
   documento e página. Também há perfis prontos (SLU-DF 90005/2026).
3. **O que falta** — checklist que compara o perfil com o projeto aberto: 🟢 tem,
   🟡 incompleto, 🔴 falta, ⚪ confirmar.
4. **Plano** — *Completar perfil com modelo*: lê os .gdb/.gpkg modelo do contratante (ou um
   plano já aceito) e põe no perfil os nomes técnicos de camadas e campos, tamanhos e domínios.
   *Plano existente*: mostra o que falta no seu plano e **cria só o que falta** (camadas e
   campos com domínio), sem apagar nada e com cópia de segurança. Campos com **valor padrão**
   no perfil recebem esse valor nos registros vazios (ex.: `ciclo` e `flag_semana` = 0, pois só
   valem para coleta quinzenal/mensal e os circuitos semanais ficam zerados).
5. **Trazer dados** — copia uma camada sua (shapefile, GeoPackage, .gdb, GeoJSON, KML, CSV…)
   para uma camada do plano, ou para um **plano novo** vazio (.gdb/.gpkg) criado do perfil. A
   camada de destino é escolhida pela geometria e pelos campos; os campos são ligados pelo nome
   e o **Claude sugere o resto** (nomes abreviados, valores por extenso). Nos campos com domínio,
   cada valor da origem é ligado a um código do contrato ("SOBRADINHO" → 5). Na cópia, os tipos
   são convertidos (Sim/Não → 1/0, hora em texto, decimal com vírgula), entram o valor fixo e o
   valor padrão do perfil, e a geometria é reprojetada e ajustada (polígono → multipolígono).
   *Prévia* mostra o que vai acontecer sem gravar; *Importar* acrescenta ou substitui, com
   cópia de segurança. A ligação fica salva para a próxima vez.
6. **Frota e equipe** — adequa o plano já feito ao edital novo (seções *recursos*, *equipes*
   e *turnos* do perfil). Compara veículos (pico por dia e turno) e pessoal (veículos ×
   equipe padrão) com o edital e propõe como ficar como o edital pede:
   - **horários** de cada circuito = turno do edital (SLU P1: 06h00-14h20, munk/papa-lixo
     08h00-16h20, noturno 16h00-00h20);
   - equipamento que o edital não tem no turno **muda de turno** se o outro turno tem sobra
     (ex.: munk noturno → diurno); senão, troca pelo mais parecido com sobra;
   - veículos a mais → tira circuitos, **juntando** a um vizinho ou **dividindo** entre 2-4
     vizinhos (mesmo equipamento, turno e dias);
   - com o **histórico de operação** (planilha de RDs, ex.: `TabelaPadrão.xlsx`: tempo total,
     refeição, produtivo/improdutivo e peso/setor por viagem), cada circuito tem o seu tempo
     real (mediana) e a **jornada do edital (7h20)** vira limite: quem recebe linhas tem de
     caber nela (tempo de coleta da parte recebida + viagens a mais ao destino) e circuitos
     acima dela passam linhas a vizinhos com folga. Mostra as **horas por dia** que o plano
     precisa × veículos do edital × 7h20, e o que ainda falta;
   - **passar para outro equipamento** os circuitos que você escolher (ex.: o munk da DL Sul
     faz o Noroeste, circuito misto);
   - **desdobrar**: a sobra de munk do edital vira **circuitos novos mistos** (semienterrado +
     porta a porta) que saem da base escolhida (ex.: DL Sobradinho). Eles recebem circuitos
     inteiros do turno que falta (noturno → dia) e a parte acima da jornada dos circuitos da
     base, até 7h20 e só nos dias em que o munk sobra. O código novo segue o padrão do plano
     (ex.: 18 + região + nº);
   - **redimensionar ao máximo** (padrão): o que ainda passa do edital tira circuitos inteiros
     repartindo as linhas entre até 8 vizinhos a até 5 km, enchendo cada um até 7h20 —
     primeiro no mesmo turno, depois no outro turno —, e os circuitos acima da jornada
     passam linhas do mesmo jeito;
   - **fechar a frota com horas a mais** (opcional, ex.: até 8h50): o turno que ainda passa
     dos veículos do edital fecha no número do edital — os circuitos tirados são repartidos
     entre os vizinhos (já com a 2ª viagem ao destino) e um equilíbrio passa linhas do mais
     carregado ao vizinho até baixar o maior tempo. As horas acima de 7h20 ficam
     **especificadas por circuito** (aba *Horas a mais*: início, término real, horas a mais,
     viagens — "falta de caminhões") e o término real é gravado na cópia;
   - **pontos para levar ao órgão**: o que não coube (horas que faltam por dia, veículos e
     pessoal a mais, circuitos acima da jornada) e o que a proposta mudou e precisa de aceite
     (áreas que mudam de turno ou de frequência, circuitos mistos novos, ordem de passagem),
     cada um com situação e proposta. O plano da licitação sai conforme o edital; esses pontos
     são negociados com o órgão depois de ganhar.

   Grava numa cópia (`<plano>_adequado.gdb`); relatório em .xlsx. Sem roteirização: a ordem
   de passagem dos circuitos que receberam linhas deve ser revista.
7. **Validar** — confere o plano contra o perfil: camadas, geometria, sistema, campos, tipos,
   tamanhos, obrigatórios vazios, valores fora do domínio e geometrias inválidas. Clique duplo
   seleciona as feições no mapa; relatório em .xlsx.

A leitura usa a **conta Claude da máquina** (Claude Code logado em claude.ai), ligada ao QGIS
por MCP (ferramentas `planos_*`); a chave de API é só alternativa.

Na primeira vez que o QGIS abre numa máquina nova, o app verifica a conta Claude (Claude Code
instalado e logado) e ajuda no login; sem ela, aceita uma chave de API (testa chave, modelo e
crédito). Código em [src/qgis_ia/planos/](src/qgis_ia/planos/).

## Versões

| Versão | Arquivo |
|--------|---------|
| v1.0.0 | `qgis-claude-ai-v1.0.0.zip` |
| v1.1.0 | `qgis-claude-ai-v1.1.0.zip` (código-fonte em `v1.1.0/`) |
| v2.0.0 | `qgis_ia-v2.0.0.zip` |
| v2.1.0 | `qgis_ia-v2.1.0.zip` — Planos de Serviço SLU-DF |
| v2.2.0 | `qgis_ia-v2.2.0.zip` — `duplicar_camada_com_ra` |
| v2.3.0 | `qgis_ia-v2.3.0.zip` — redesenho do plano de coleta (`slu_redesenhar_coleta`) |
| v2.4.0 | `qgis_ia-v2.4.0.zip` (código-fonte em `src/qgis_ia/`) — planilha de soltura (`slu_planilha_soltura`) |

Os zips também estão publicados na aba **Releases** do repositório.

## Instalação

No QGIS: *Complementos → Gerenciar e instalar complementos → Instalar a partir de ZIP* e selecione o zip da versão desejada.

## Testes

```
"C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat" tests\test_slu.py
"C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat" tests\test_registro.py
"C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat" tests\test_duplicar_ra.py
"C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat" tests\test_redesenho.py
"C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat" tests\test_soltura.py
"C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat" tests\test_planos.py
"C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat" tests\test_planos_fase2.py
"C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat" tests\test_planos_frota.py
"C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat" tests\test_planos_importacao.py
"C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat" tests\test_projetos.py
```
