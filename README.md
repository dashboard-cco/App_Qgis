# QgisIA

Plugin QGIS com assistente de IA (Claude) para geoprocessamento.

A partir da v2.1.0, gera e confere os **Planos de Serviço do SLU-DF** no padrão do
Anexo G do Edital do Pregão Presencial nº 90005/2026 (pasta `Edital/`): File Geodatabase
(.gdb), tabelas (.xlsx), texto (.docx) e shapefile. Detalhes em
[src/qgis_ia/README.md](src/qgis_ia/README.md).

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
```
