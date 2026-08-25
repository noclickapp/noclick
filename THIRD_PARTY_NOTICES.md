# Third-party notices

NoClick Community uses third-party dependencies identified in the package
manifests and lockfiles. Those components remain under their respective
licenses; the repository license does not replace their terms.

## Simple Icons

Some integration marks in `frontend/public/icons/` are generated from
[Simple Icons](https://simpleicons.org/) version 16.12.0, distributed under
CC0 1.0. Other entries use neutral monograms generated in-repository rather
than copied provider artwork. The reproducible mapping and fallback generator
are in `scripts/sync-simple-icons.mjs`.

Simple Icons notes that brand icons may be subject to trademark and brand-use
rules independently of copyright. Product names and marks identify compatible
third-party services. Their inclusion does not imply affiliation or
endorsement, and all marks remain the property of their respective owners.

The complete reviewed inventory is in `scripts/asset-provenance.json`. Entries
without a reviewed upstream icon are generated as neutral monograms and do not
copy third-party artwork. The custom-asset exception list is explicit and is
empty at this release; adding an exception requires its source, license, and
SHA-256 digest.

## Sucrase browser bundle

`backend/utils/sucrase_bundle.js` is a reproducible browser bundle of
[Sucrase](https://github.com/alangpierce/sucrase) version 3.35.1, distributed
under the MIT License. It is built with esbuild 0.25.12 from the exact package
graph in `package-lock.json`; `scripts/build-sucrase-bundle.mjs` and
`backend/utils/sucrase_bundle.provenance.json` record the build recipe and
artifact hash.

The emitted code also contains `@jridgewell/gen-mapping`,
`@jridgewell/resolve-uri`, `@jridgewell/sourcemap-codec`,
`@jridgewell/trace-mapping`, and `lines-and-columns`, each under the MIT
License, plus `ts-interface-checker` under the Apache License 2.0. The complete
copyright and license texts for every package included in the bundle are
retained in `backend/utils/sucrase_bundle.LICENSES.txt`.

## Fonts and packages

The bundled Inter and Outfit fonts are distributed under the SIL Open Font
License 1.1. Browser-compatibility data from `caniuse-lite` is distributed
under CC BY 4.0, and SPDX exception data is distributed under CC BY 3.0.

JavaScript and Python dependencies retain their package-level copyright
notices and licenses. Some dependencies offer a choice of licenses; NoClick
selects the permissive option where one is offered (for example, Apache-2.0 for
DOMPurify). Release artifacts must be produced from the committed lockfiles so
the dependency inventory is reproducible.

The dependency tree may contain reciprocal-license components used as
unmodified, separable libraries. Their terms continue to apply to those
components and must be reviewed when distributing binaries or containers. A
release owner must regenerate and review the full dependency-license inventory
before every public release.

## React Flow / XYFlow

The workflow canvas uses `@xyflow/react` 12.10.0 (React Flow) and
`@xyflow/system` 0.0.74, distributed under the MIT License. NoClick does not
display React Flow's optional in-product attribution; the copyright and
permission notice required by the MIT License is retained here instead.

MIT License

Copyright (c) 2019-2025 webkid GmbH

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

The Python runtime currently includes `chardet` under LGPL-2.1-or-later and
`psycopg2-binary` under LGPL-3.0-or-later with its documented exceptions.
Python SoundFile is BSD-licensed; its binary wheels may bundle `libsndfile`,
which is LGPL-2.1-or-later. The JavaScript development and build trees include
components under MPL-2.0, while DOMPurify is used under its Apache-2.0 option.
These packages are consumed as unmodified dependencies; redistributors must
retain their applicable notices and satisfy their license terms. This summary
is not a substitute for the full release-specific dependency inventory.

## Container services

The default Docker Compose stack runs MinIO as a separate S3-compatible object
storage service. MinIO uses the GNU Affero General Public License, version 3.
Its source and license are available from
[minio/minio](https://github.com/minio/minio).

The optional `redis` Compose profile runs Valkey, a Redis-protocol-compatible
cache server, under the BSD 3-Clause License. Its source and license are
available from [valkey-io/valkey](https://github.com/valkey-io/valkey). The
service/profile retains the name `redis` for configuration compatibility; the
shipped container image is `valkey/valkey:8.1.3-alpine`, pinned by manifest
digest in `docker-compose.yml`.
