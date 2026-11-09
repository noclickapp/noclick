# OnePageCRM published examples

`responses.json` preserves the first JSON response published on each official endpoint page named by `source`. Empty responses have a null body. `inputs.json` uses the same pages' request examples and resource IDs, selecting the fields this integration supports. An empty linked deal ID is normalized to an absent optional link.

The pinned OnePageCRM v3 OpenAPI document references `Lead_source.id` (readOnly) from the contact-create and contact-update request `lead_source_id`. The provider's own request examples explicitly send `lead_source_id: "advertisement"`:

- https://developer.onepagecrm.com/api/reference/contacts/post-contacts/
- https://developer.onepagecrm.com/api/reference/contacts/put-contacts-contact_id/

This integration retains the documented writable input. Partial updates use the provider-wide convention documented at https://developer.onepagecrm.com/api/partial-updates/.
