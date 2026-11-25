# -*- coding: utf-8 -*-
"""Leitura do edital pela IA (Claude): devolve o perfil do contrato em JSON.

Uma chamada só, com todos os documentos (cabem na janela de 1M tokens), resposta
estruturada pelo esquema de perfil.ESQUEMA. Sem QGIS: pode ser testado sozinho.
"""
import json

from . import documentos, perfil

MODELO = "claude-opus-5-5"
PRECO_ENTRADA_USD = 4.00 / 1_000_000    # claude-opus-5-5, por token
PRECO_SAIDA_USD = 20.00 / 1_000_000
SAIDA_ESTIMADA = 25_000                  # tokens de saída (inclui raciocínio), estimativa
MAX_TOKENS = 96_000

SISTEMA = """Você é analista de contratos públicos de serviços com planejamento georreferenciado \
(limpeza urbana, coleta, varrição, manutenção urbana e similares). Sua tarefa é ler o edital, \
o termo de referência, os anexos e as especificações técnicas e levantar TUDO o que a empresa \
contratada precisa entregar e ter em mãos para elaborar o plano de serviço/plano de trabalho \
que o contrato exige.

Regras:
- Use apenas o que está nos documentos. Não invente. Se algo não estiver claro ou faltar, \
registre em "pendencias".
- Em cada item, preencha "fonte" com o nome do documento (atributo nome) e a(s) página(s) \
indicadas por [pág. N].
- As especificações técnicas podem estar dentro do próprio edital ou em documentos separados; \
procure em todos.
- "camadas": cada camada/tabela que o plano entregue deve conter, com o nome EXATO exigido, a \
geometria e todos os campos (nome exato, tipo, obrigatoriedade e valores permitidos/domínios). \
Se uma mesma camada tiver campos diferentes conforme o grupo de serviços, crie uma entrada por \
grupo e liste os serviços em "servicos".
- "insumos": dados e informações de entrada para construir o plano (bases geográficas, frota, \
equipes, locais de destinação, quantitativos...), mesmo que o edital só os cite indiretamente. \
Em "palavras_chave" ponha termos curtos, sem acento e em minúsculas, que costumam aparecer em \
nomes de camadas ou arquivos desse insumo.
- "entregaveis": arquivos/documentos que compõem o plano (formato, prazo, para quais serviços).
- "regras": exigências de formato, validação e dimensionamento que o plano precisa cumprir.
- Escreva em português do Brasil, de forma curta."""

PEDIDO = ("Leia os documentos acima e monte o perfil do contrato com o que é preciso para "
          "gerar o plano exigido.")


def estimativa(docs):
    """(tokens de entrada, custo em US$) aproximados para ler estes documentos."""
    t = documentos.tokens_estimados(docs) + 2_000
    custo = t * PRECO_ENTRADA_USD + SAIDA_ESTIMADA * PRECO_SAIDA_USD
    return t, custo


class ErroExtracao(Exception):
    pass


URL_CREDITOS = "https://console.anthropic.com/settings/billing"


def mensagem_erro(e):
    """Texto claro para um erro de status da API."""
    corpo = getattr(e, "body", None)
    msg = ""
    if isinstance(corpo, dict):
        msg = (corpo.get("error") or {}).get("message", "")
    msg = msg or str(getattr(e, "message", e))
    if "credit balance" in msg.lower():
        return ("A conta da IA está sem créditos. Compre créditos em "
                f"{URL_CREDITOS} (Plans & Billing) e tente de novo.")
    if getattr(e, "status_code", 0) == 529 or "overloaded" in msg.lower():
        return "A IA está sobrecarregada no momento. Tente de novo em alguns minutos."
    return f"Erro da IA ({getattr(e, 'status_code', '?')}): {msg}"


def extrair(docs, chave_api, progresso=None, cancelado=None):
    """Chama a IA e devolve (perfil, info). progresso(texto) recebe mensagens curtas;
    cancelado() -> True interrompe."""
    import anthropic

    cliente = anthropic.Anthropic(api_key=chave_api, max_retries=3, timeout=1800)
    conteudo = [
        {"type": "text", "text": documentos.texto_para_ia(docs),
         "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": PEDIDO},
    ]
    if progresso:
        progresso("Enviando os documentos para a IA...")
    recebidos = 0
    try:
        with cliente.beta.messages.stream(
            model=MODELO,
            max_tokens=MAX_TOKENS,
            system=SISTEMA,
            messages=[{"role": "user", "content": conteudo}],
            thinking={"type": "adaptive"},
            output_config={"effort": "high",
                           "format": {"type": "json_schema", "schema": perfil.ESQUEMA}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            for ev in stream:
                if cancelado and cancelado():
                    raise ErroExtracao("Leitura cancelada.")
                if ev.type == "content_block_delta" and getattr(ev.delta, "type", "") == "text_delta":
                    recebidos += len(ev.delta.text)
                    if progresso and recebidos % 2000 < len(ev.delta.text):
                        progresso(f"Montando o perfil... {recebidos // 1000} mil caracteres")
                elif ev.type == "content_block_start" and getattr(ev.content_block, "type", "") == "thinking":
                    if progresso:
                        progresso("A IA está lendo e analisando os documentos...")
            msg = stream.get_final_message()
    except anthropic.AuthenticationError:
        raise ErroExtracao("Chave da IA inválida. Abra Configurar IA e informe outra chave.")
    except anthropic.PermissionDeniedError as e:
        raise ErroExtracao(f"A conta da IA não tem permissão: {e.message}")
    except anthropic.RateLimitError:
        raise ErroExtracao("Limite de uso da conta da IA atingido. Tente de novo em alguns minutos.")
    except anthropic.APIStatusError as e:
        raise ErroExtracao(mensagem_erro(e))
    except anthropic.APIConnectionError:
        raise ErroExtracao("Sem conexão com a IA. Verifique a internet.")

    if msg.stop_reason == "refusal":
        raise ErroExtracao("A IA recusou a leitura destes documentos.")
    if msg.stop_reason == "max_tokens":
        raise ErroExtracao("A resposta da IA ficou grande demais e foi cortada. "
                           "Tente ler menos documentos de uma vez.")
    texto = next((b.text for b in msg.content if b.type == "text"), "")
    try:
        p = perfil.normaliza(json.loads(texto))
    except json.JSONDecodeError as e:
        raise ErroExtracao(f"A IA devolveu um perfil inválido: {e}")

    u = msg.usage
    entrada = (u.input_tokens or 0) + (u.cache_creation_input_tokens or 0) + \
              (u.cache_read_input_tokens or 0)
    custo = entrada * PRECO_ENTRADA_USD + (u.output_tokens or 0) * PRECO_SAIDA_USD
    info = {"modelo": msg.model, "tokens_entrada": entrada, "tokens_saida": u.output_tokens,
            "custo_usd": round(custo, 2)}
    p["_meta"].update({"origem": "leitura por IA", "documentos": [d["nome"] for d in docs],
                       **info})
    return p, info
