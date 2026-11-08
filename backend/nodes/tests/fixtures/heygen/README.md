# Heygen HTTP fixtures

`requests.json` contains synthetic inputs and responses for native-factory HTTP
regressions. They are not live-account evidence or copied provider responses.
The expected methods, paths, parameters and body shapes follow the provider's
published [External API contract](https://developers.heygen.com/openapi/external-api.json),
version `1.0.0`, SHA-256
`a5c5262935e55a7c2a02301555c810e2bcef3605f3b291e983811b902dfe6e9d`.

Creation returns an asynchronous job. A successful request does not mean that
rendering or translation has completed. List fixtures preserve provider cursors
and demonstrate that the node returns one page without following it.

Provider references: [create video](https://developers.heygen.com/reference/create-video),
[generate from template](https://developers.heygen.com/reference/generate-video-from-template),
[translate video](https://developers.heygen.com/reference/create-video-translation),
[current user](https://developers.heygen.com/reference/get-current-user).
