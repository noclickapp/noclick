# Evolution Go test fixtures

Each fixture cites its provider documentation source. Request and response shapes,
field names, event types, and message content are taken from those examples.
Account identifiers and the event display name are replaced for public export:

| Identity role | Fictional test value |
| --- | --- |
| Primary phone / message sender | `12025550100` |
| Secondary and additional participants | `12025550104` |
| Alternate sender JID | `12025550102@lid` |
| Event display name | Alex Example |

Phone numbers use the reserved NANP 555-0100 range and the reviewed fictional JIDs
accepted by the community boundary check. Device suffixes and JID domains retain
their documented shape. These fixtures are mock-only; no live account is used.
Unmodified provider examples remain in the separate conformance evidence catalog.
