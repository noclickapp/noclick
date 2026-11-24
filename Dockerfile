# NoClick's app (app/) as one container: a Node server on $PORT (3000 unless set), configured by the settings
# app/README.md lists. Build it from this repository's root, since the app compiles the TypeScript SDK's source
# beside it:
#
#   docker build -t noclick-app .
#   docker run --env-file app/.env -p 3000:3000 noclick-app
#
# The deploy files at this repository's root (render.yaml and the others) build this file.
FROM node:22-slim AS build
# pnpm, at the version app/package.json names.
RUN corepack enable pnpm
WORKDIR /repo/app
COPY app/package.json app/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY sdk/typescript/src /repo/sdk/typescript/src
COPY app ./
# The server build imports its packages at run time, so they stay, without the ones only the build needs.
RUN pnpm build && pnpm prune --prod --ignore-scripts

FROM node:22-slim
ENV NODE_ENV=production PORT=3000
WORKDIR /app
COPY --from=build /repo/app/package.json ./
COPY --from=build /repo/app/node_modules ./node_modules
COPY --from=build /repo/app/build ./build
USER node
EXPOSE 3000
CMD ["node_modules/.bin/react-router-serve", "./build/server/index.js"]
