TripWorks fixture provenance

Source: https://api-docs.tripworks.com/openapi.json, REST API 1.1.6,
SHA-256 db4b033788a8bad7e4016ef20106498dfd948f607c571b4d660e77ac3d979c7b.

`request_examples.json` uses the operation request examples, with a synthetic
public UUID for path parameters. `customers.json` and `trips.json` copy the
Customer and Trip schema examples into their documented list envelopes with
terminal pagination metadata. These are local unit fixtures, not live recordings
or provider-authored full-response witnesses. Tests add pagination cursors and
HTTP errors to exercise failure handling.
