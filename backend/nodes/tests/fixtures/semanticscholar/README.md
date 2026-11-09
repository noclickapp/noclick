The batch JSON fixtures are copied from the provider-authored Python response
examples in the pinned Academic Graph API v1 Swagger document:

- https://api.semanticscholar.org/graph/v1/swagger.json
- Paper batch docs: https://api.semanticscholar.org/api-docs/graph#tag/Paper-Data/operation/post_graph_get_papers
- Author batch docs: https://api.semanticscholar.org/api-docs/graph#tag/Author-Data/operation/post_graph_get_authors

Both examples return arrays. The same document's response schemas incorrectly
reference a single FullPaper / AuthorWithPapers object. Tests deliberately pin
the documented arrays rather than accepting a fabricated object response.
