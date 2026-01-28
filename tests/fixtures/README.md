This folder is for **local-only** reference fixtures used to lock parser behavior.

## Itaú Personnalité reference invoice (text)

Create a file:

- `itau_personnalite_reference.txt`

It should contain the **raw extracted text** of the reference PDF invoice (the same kind of text passed into `parse_itau_personnalite(text)`), including the "Lançamentos: compras e saques" section and the "Compras parceladas – próximas faturas" marker.

The pytest tests will:

- Assert an expected transaction count (38) **only for this specific reference file**.
- Assert that no transactions are taken from after the "Compras parceladas" section.

You can also point to a different path using:

- `ITAU_PERSONNALITE_REFERENCE_TEXT_PATH=/absolute/path/to/file.txt`
