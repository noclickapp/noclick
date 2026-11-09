`calendar_accepted.json` is the unmodified `202` → `application/json` → `examples.Result.value` from Hospitable's published v2 contract, `PUT /properties/{uuid}/calendar`.

Source: https://stoplight.io/api/v1/projects/hospitable-eng/public-api-docs/nodes/V2/public.json?fromExportButton=true&snapshotType=http_service

`property_documented.json` is the unmodified first `examples` entry from Hospitable's Property model:
https://stoplight.io/api/v1/projects/hospitable-eng/public-api-docs/nodes/Property.json
The provider's example has numeric coordinates where its schema declares strings, and a legacy room-details representation. The node preserves this documented body without imposing the conflicting response schema.
