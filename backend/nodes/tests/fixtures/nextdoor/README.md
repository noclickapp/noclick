The response examples in responses.json and string-responses.json are copied from Nextdoor's published
share-api 1.0 contract, pinned by the integration conformance catalog. Sources:

- https://developer.nextdoor.com/reference/me-1
- https://developer.nextdoor.com/reference/me-copy
- https://developer.nextdoor.com/reference/get-agency-boundaries

They retain the provider's descriptive placeholder values and array envelope.
Tests use these shapes without inventing extra requirements on API responses.

posts.json is the published Get your posts response example, including its
comment and reply shape: https://developer.nextdoor.com/reference/get-your-posts.
This feed returns the most recent posts and excludes business/entity profiles.

The string response examples preserve the published values for these writes:

- https://developer.nextdoor.com/reference/mark-fsf-sold
- https://developer.nextdoor.com/reference/delete-a-comment
- https://developer.nextdoor.com/reference/edit-a-post
- https://developer.nextdoor.com/reference/delete-a-post
