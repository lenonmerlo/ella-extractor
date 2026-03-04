# Invoice Parser Contract v1 (Fase 1)

Este contrato define um payload canônico **aditivo** para parsers de fatura.

## Objetivo

- Manter compatibilidade com o formato legado (`bank`, `dueDate`, `total`, `transactions`)
- Incluir metadados padronizados para reconciliação e observabilidade
- Permitir evolução entre repos (`extractor`, `backend`, `frontend`) com versionamento explícito

## Campos obrigatórios (legado)

- `bank`: string
- `dueDate`: `YYYY-MM-DD | null`
- `total`: number | null
- `transactions`: array

Transação:

- `date`: `YYYY-MM-DD`
- `description`: string
- `amount`: number (assinado)
- `cardFinal?`: string
- `installment?`: `{ current: number, total: number }`

## Campos canônicos v1 (novos, aditivos)

- `parserContractVersion`: string (ex.: `1.0.0`)
- `summary`:
  - `invoiceTotal`: number | null
  - `expensesTotal`: number
  - `creditsTotalAbs`: number
  - `signedTransactionsTotal`: number
  - `transactionCount`: number
- `reconciliation`:
  - `difference`: number | null (`invoiceTotal - signedTransactionsTotal`)
  - `isBalanced`: boolean | null
  - `threshold`: number (ex.: `0.01`)
- `diagnostics`:
  - `sourceParser`: string
  - `notes`: string[]

## Compatibilidade

- O backend pode ignorar campos novos sem quebrar desserialização.
- Mudanças de contrato devem ser aditivas dentro da mesma major version.
- Qualquer mudança breaking requer nova major (ex.: `2.x`).

## Status da Fase 1

- Piloto implementado no parser Sicredi.
- Próximo passo: aplicar o mesmo envelope aos demais parsers de fatura.
