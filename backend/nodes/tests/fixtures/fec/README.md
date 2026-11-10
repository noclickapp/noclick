Synthetic filing page, using the `FilingsPage`, `Filings` and `OffsetInfo` schemas in the FEC's published Swagger 1.0: https://api.open.fec.gov/swagger . File numbers are filing identifiers; the trigger handles amendments that receive a new file number. This is a schema fixture, not a recorded provider response.

Evidence files retain the unchanged harness report/verdict (authentication is blocked by the provider contract's combined security requirement), documented spec contradiction, lossless dialect conversion audit, and supplemental parameter/body audit. The latter uses openapi-core's original parameter/body validators directly because its security validator otherwise returns before validating parameters. It does not change the contract or turn the main verdict green. The trigger itself emits a new filing and passes all schema-read checks in the report.

Reproduction uses the external conformance catalog `fec` with the original Swagger pin and its audited swagger2openapi 7.0.8 conversion. No provider credential or live response was used.

After installing the harness, run from `backend`: `PYTHONPATH=. CONFORMANCE_CATALOG=/path/to/catalog/fec python nodes/tests/fixtures/fec/audit_parameters.py /path/to/catalog/fec`. The catalog supplies the pinned converted document and the untouched main report.
