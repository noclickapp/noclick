# noclick

The SDK for NoClick workflows. To run an instance of your own, see the
[self-hosting guide](https://github.com/noclickapp/noclick/blob/main/docs/self-hosting.md).

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
[the docs](https://www.noclick.com/docs) for the full surface.

For external WebSocket clients, omitting `url` intentionally connects to the
managed `https://api.noclick.io` service. Self-hosted applications should pass
their own backend URL as shown above.

## License

[Apache License 2.0](./LICENSE). The SDK is deliberately permissive so that the
code you write against it stays under whatever license you choose. NoClick
itself is AGPL-3.0-only. Versions up to 0.1.3 on npm were published under the
Sustainable Use License 1.0 and remain available under it.
