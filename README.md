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
   campos com domínio), sem apagar nada e com cópia de segurança.
5. **Validar** — confere o plano contra o perfil: camadas, geometria, sistema, campos, tipos,
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
```
