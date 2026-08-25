# noclick

Two things in one package, because they are two halves of the same product.

## Run an instance

```bash
npx noclick
```

Fetches [NoClick](https://github.com/noclickapp/noclick), generates the secrets
that have to be unique to your installation, and starts it. Docker is the only
prerequisite. Then:

```bash
npx noclick logs        # follow them
npx noclick update      # fetch the latest version and restart
npx noclick stop        # stop, keeping the data
npx noclick help        # the rest
```

Back up the `.env` it writes (`npx noclick where` prints the directory). Every
stored integration credential is encrypted with the `CREDENTIALS_ENCRYPTION_KEY`
in it, and a restored database without that key cannot read any of them.

## Build against one

```bash
npm install noclick
```

```ts
import { init, execution } from 'noclick';

await init({
  url: 'https://automation.example.com',
  apiKey: process.env.NOCLICK_API_KEY,
  workflowId: 'a1b2c3…',
});

const outputs = await execution
  .runNodesAndGetOutput(['start-node'], ['result-node'])
  .all();
console.log(outputs['result-node']);
```

The SDK talks to a NoClick instance — self-hosted or managed — over its socket
API: running workflows and individual nodes, streaming their output, reading and
writing state, and uploading resources. Inside a custom interface component it
initialises itself over `postMessage` and needs no key. See
[the docs](https://docs.noclick.com) for the full surface.

For external WebSocket clients, omitting `url` intentionally connects to the
managed `https://api.noclick.io` service. Self-hosted applications should pass
their own backend URL as shown above.

## License

Source-available under the [Sustainable Use License](./LICENSE.md).
