# The app

NoClick's app: the screens for working with a NoClick account, built only on the TypeScript SDK in
[`../sdk/typescript`](../sdk/typescript). So far it is the app's shell, a React Router project with one page;
NoClick's screens move in here one at a time.

## Run it

You need Node 22.12 or later and pnpm 10 (`corepack enable pnpm` gives you the version `package.json` names).

```bash
cd app
pnpm install --frozen-lockfile
pnpm dev                    # a development server on http://localhost:5173
pnpm build && pnpm start    # the production build, served on http://localhost:3000
pnpm typecheck
pnpm test
```

`scripts/check.sh` at the repository's root installs, typechecks, tests and builds the app along with the SDKs, as CI
does.

## How it is put together

- React Router 7 in framework mode, with Vite. `src/` is the app directory: `root.tsx` is the document and the root
  route, `routes.ts` the route table, `routes/` the pages.
- `@/…` imports from `src/…`.
- `noclick` is the SDK's source in `../sdk/typescript/src`, not the package from npm, so the app always runs on the SDK
  as this repository has it, with no build step between them.
- Tailwind CSS 3, configured in `tailwind.config.ts`.
- `test/imports.test.ts` keeps the app buildable from this repository alone: no file imports a path outside it, and
  every package a file imports is one `package.json` names.

Apache-2.0, as the rest of this repository.
