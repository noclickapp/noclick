# Owler contract coverage

Contract: [Owler Enterprise API v3.0](https://developers-v3.owler.com/apis/api3-swagger.json),
SHA-256 `327691f6c6eec8d3b5e9fe0f5ad135e1e388e66f4a57875ea096a11f79e38a2a`.
The published document was fetched again during development and matched the pin.

| Node action | Published operation |
| --- | --- |
| `get_company_by_id` | `getCompanyById` |
| `get_company_by_website` | `getCompanyByWebsite` |
| `get_competitors_by_id` | `getCompetitorsForId` |
| `get_competitors_by_website` | `getCompetitorsForWebsite` |
| `get_feeds_by_id` | `getFeeds` |
| `get_feeds_by_website` | `getFeedsByWebsite` |
| `get_funding_news` | `getFeeds`, category `FUNDING` |
| `get_acquisition_news` | `getFeeds`, category `ACQUISITION` |
| `get_people_news` | `getFeeds`, category `PEOPLE` |
| `get_press_releases` | `getFeeds`, category `PRESS` |
| `on_new_feed_by_id` | `getFeeds`, latest 100 items |
| `on_new_feed_by_website` | `getFeedsByWebsite`, latest 100 items |

All requests use the document's `api_key` security scheme (`x-api-key` header)
and request JSON. The API publishes six GET endpoints and no writes or webhook
registration. The four focused news actions use documented category values;
each makes one request to the same feed endpoint.

The feed endpoint descriptions specify latest-first results and a maximum of
100 items. Poll triggers baseline when armed, deduplicate by the documented
`FeedsVO.id`, and rebaseline when the declared company/category scope changes.
They monitor the latest 100 matching items, so more than 100 arrivals between
polls can exceed the window. Historical pagination is available in the read
actions. Agent events read only properties of `FeedsVO` and `CompanyBasicVO`.

Connection evidence reads company ID `100486`, the document's company-ID
example. This demonstrates API key reachability, not account ownership.

`schema_payloads.json` contains synthetic values shaped by the pinned response
schemas. These are offline test fixtures, not provider-authored examples or
live recordings. No external witness or input override was invented.
