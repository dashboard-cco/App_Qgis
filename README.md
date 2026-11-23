# QgisIA

Plugin QGIS com assistente de IA (Claude) para geoprocessamento.

A partir da v2.1.0, gera e confere os **Planos de Serviço do SLU-DF** no padrão do
Anexo G do Edital do Pregão Presencial nº 90005/2026 (pasta `Edital/`): File Geodatabase
(.gdb), tabelas (.xlsx), texto (.docx) e shapefile. Detalhes em
[src/qgis_ia/README.md](src/qgis_ia/README.md).

## Versões

| Versão | Arquivo |
|--------|---------|
| v1.0.0 | `qgis-claude-ai-v1.0.0.zip` |
| v1.1.0 | `qgis-claude-ai-v1.1.0.zip` (código-fonte em `v1.1.0/`) |
| v2.0.0 | `qgis_ia-v2.0.0.zip` |
| v2.1.0 | `qgis_ia-v2.1.0.zip` (código-fonte em `src/qgis_ia/`) — Planos de Serviço SLU-DF |

Os zips também estão publicados na aba **Releases** do repositório.

## Instalação

No QGIS: *Complementos → Gerenciar e instalar complementos → Instalar a partir de ZIP* e selecione o zip da versão desejada.

## Testes

```
"C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat" tests\test_slu.py
"C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat" tests\test_registro.py
```
