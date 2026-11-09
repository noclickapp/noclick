The OpenAPI fixture is the unmodified Flashquotes 1.0.0 contract published at
https://docs.flashquotes.com/api-reference/openapi.json (SHA-256
`7b54c490a5b5f5f5e4af7284264181f80047cef9022f7a246635bee86461a9bc`).
It pins the routes exercised by this integration's native factory tests.

Modern response fixtures are copied from that contract's default examples.
The form response is the example at
https://docs.flashquotes.com/api-reference/form-response/get.md and the invoice
object is copied from
https://docs.flashquotes.com/api-reference/invoice/list-invoices.md.
The two legacy event fixtures are synthetic examples of the declared shapes.

The invoice page documents an object with `bookingId`, `invoiceIds`, and
`invoiceUrls`, while the pinned aggregate contract declares an array of
`LegacyInvoice`. The native parser preserves both shapes; its regression test
exercises both. Invoice URLs are returned as data and are never fetched.

This contract has eleven GET operations and no mutations. Although the task
creation page describes a write, that route is absent from this pin, so this
integration exposes the eleven contracted reads. The legacy event operations
are explicitly labeled as legacy; prefer modern events with cursor pagination.
