Provider-authored response examples, copied without changing their values:

- `upload.json`: https://docs.ai21.com/reference/manage-library-ref/upload-workspace-files
- `download.json`: https://docs.ai21.com/reference/manage-library-ref/get-file-download-link

Other response objects in the mock tests are synthetic cases, not provider evidence.

Contract notes (published OpenAPI version 1.0.0 at https://api.ai21.com/openapi.json):

- The contract omits authentication. AI21 requires Bearer API keys:
  https://docs.ai21.com/reference/authentication.md. The external conformance
  catalog supplies the documented host and a sourced bearer override.
- `POST /studio/v1/library/files` declares its multipart `file` as
  `type: string, format: binary` in OpenAPI 3.1. The conformance validator
  deserializes that part to bytes, then rejects it as not a string; its
  automatic repair also cannot infer a MIME type from the binary declaration.
  AI21's upload documentation explicitly requires raw file bytes and supports
  text/plain: https://docs.ai21.com/reference/manage-library-ref/upload-workspace-files.md.
  The node sends exactly that multipart file, with a filename and text/plain
  content type. The mock tests check those bytes and repeated labels; neither
  the pinned contract nor the conformance harness is changed.

The full witness run reaches ten distinct contract operations, verifies auth
placement on all ten, validates nine requests, and replays both provider
response examples successfully. The only blocking operation is upload, for
that documented binary schema/validator mismatch. This is offline evidence;
no live key or provider account was used.
