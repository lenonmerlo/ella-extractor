# Extractor (serviço local de extração/parsing de PDFs)

## Deploy no Render (Docker Web Service)

Este microserviço pode ser deployado no Render como um **Web Service (Docker)** separado.

Configuração recomendada no Render:

- **Runtime**: Docker
- **Root Directory**: `extractor`
- **Dockerfile Path**: `extractor/Dockerfile` (ou apenas `Dockerfile`, dependendo da UI)
- **Health Check Path**: `/health`
- **Port**: o Render injeta a porta em `PORT`; o container sobe com `--port ${PORT:-8000}`.

Observação: não há dependências em arquivos fora de `extractor/`.

### Exemplos de curl

Defina a URL do serviço (Render):

- PowerShell:
  - `$BASE_URL = "https://SEU-SERVICO.onrender.com"`

Health:

- `curl -s "$BASE_URL/health"`

Extrair texto (upload de PDF):

- `curl -s -X POST "$BASE_URL/extract/itau-personnalite" -F "file=@/caminho/para/arquivo.pdf;type=application/pdf"`

Este diretório contém um microserviço FastAPI **local** para:

- extrair texto de PDFs (via `pdfplumber`), e
- fazer parsing de fatura **Itaú Personnalité** (PDF → JSON) via `parsers/itau_personnalite.py`.

O objetivo principal é comparar/depurar a extração de texto e travar comportamento do parser com testes automatizados.

## Requisitos

- Python 3.11+ (funciona com 3.12 também)
- Dependências em `requirements.txt`

## Instalação

No diretório `extractor/`:

- Criar/ativar venv (exemplo Windows PowerShell):
  - `python -m venv .venv`
  - `./.venv/Scripts/Activate.ps1`

- Instalar dependências:
  - `pip install -r requirements.txt`

## Rodando a API

No diretório `extractor/`:

- `uvicorn app:app --reload --host 0.0.0.0 --port 8001`

Endpoints principais:

- `GET /health`
- `POST /extract/itau-personnalite`
  - Retorna o texto extraído (normalizado para debug visual), além de metadados.
- `POST /parse/itau-personnalite`
  - Extrai o texto bruto por página, monta `raw_text` e chama o parser.
  - **Também salva o `raw_text` exatamente como montado** em:
    - `extractor/tests/fixtures/itau_personnalite_reference.txt`
    - isso acontece a cada request (pensado para uso local).

## Fixture de referência (travar comportamento)

Para travar o comportamento do parser contra uma fatura específica, usamos um fixture de texto bruto:

- `extractor/tests/fixtures/itau_personnalite_reference.txt`

Como gerar esse arquivo:

1. Suba a API (`uvicorn ...`).
2. Faça upload do PDF real no endpoint `POST /parse/itau-personnalite`.
3. O serviço irá sobrescrever o arquivo de fixture automaticamente com o `raw_text` do PDF.

Observação importante:

- A contagem de transações **não é fixa** entre faturas.
- Alguns testes de referência (marcados como `reference_invoice`) validam, para **um arquivo específico**, uma contagem esperada (ex.: 38).

## Rodando os testes

No diretório `extractor/`:

- `pytest -q`

Marcas úteis:

- `pytest -q -m reference_invoice` (somente testes que travam a fatura de referência)

Se o fixture `itau_personnalite_reference.txt` não existir, os testes de referência serão pulados (`skipped`).

## Estrutura

- `app.py`: FastAPI + extração de texto do PDF + endpoints.
- `parsers/itau_personnalite.py`: parser Itaú Personnalité (texto → JSON).
- `tests/`: testes unitários e de contrato.
- `tests/fixtures/`: fixtures locais (texto bruto de referência).

## Notas

- Este serviço foi feito para uso local de desenvolvimento/validação.
- O parser contém guardrails importantes, incluindo **STOP absoluto** em “Compras parceladas – próximas faturas”.
