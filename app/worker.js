// The app as a Worker: the same server build `pnpm start` serves with Node, answered by a fetch handler instead, for
// hosts that run Workers (../wrangler.jsonc is the config they read). The server's code keeps to web standards
// (fetch, Web Crypto, web streams), so nothing in it changes; its settings arrive as the Worker's secrets, which the
// runtime's Node compatibility hands to `process.env`. The files in build/client are served by the host before this
// runs.
import { createRequestHandler } from 'react-router';
import * as build from './build/server/index.js';

const handle = createRequestHandler(build, 'production');

export default {
    fetch(request) {
        return handle(request);
    },
};
