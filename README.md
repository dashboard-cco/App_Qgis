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
4. **Gerar** e 5. **Validar** — Fase 2.

Precisa de uma conta da IA (Anthropic). Na primeira vez que o QGIS abre numa máquina nova, o
app pede a chave, testa (chave, modelo e crédito) e grava em `ANTHROPIC_API_KEY` do usuário.
Código em [src/qgis_ia/planos/](src/qgis_ia/planos/).

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
```
