SavvyCal request and response fixtures

`contract_examples.json` copies the provider's response examples unchanged from
https://api.savvycal.com/v1/spec, version 1.0.0, SHA-256
`398985d699a35311bc837747e938a4877a110aa1c56d6333f1c0989f61162ed5`.
`cases.json` supplies request configs and expected wire representations, including
query encoding, cursor pages, private-name clearing and custom booking answers.
All credentials in tests are synthetic. No live API requests are made.

The Event example has `poll: null`, although Event.properties.poll in the
published schema is a non-nullable object. The current provider documentation
also shows `poll: null`:
https://docs.savvycal.com/developers/v1/api/get-event
The native node tests replay that exact example for listing, reading, canceling
and creating events. They demonstrate parsing despite this schema contradiction;
the conformance harness validates generated responses for those four operations.
All other operations replay the provider's unchanged examples in conformance.
