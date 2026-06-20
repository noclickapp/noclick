// Verifies the cURL parser used by the HTTP Request node's "Import cURL" action.
// Pure-function test — runs against ~/lib/curlParser without needing a loaded
// workflow. Run: nc_run_test({ file: "tests/nc/curl-import.test.ts" })
import { nc } from '~/lib/nc';
import { parseCurl, methodToOperation, isCurlCommand } from '~/lib/curlParser';
import { parseClipboardContent } from '~/utils/clipboard-parsers';

export default async function () {
    // Pasting a cURL command creates a pre-configured HTTP node.
    nc.assert.truthy(isCurlCommand('curl https://x.com'), 'detects curl');
    nc.assert.truthy(isCurlCommand('$ curl -X POST https://x.com'), 'detects curl after prompt');
    nc.assert.truthy(!isCurlCommand('not a curl command'), 'rejects non-curl');
    const pasted = parseClipboardContent(
        `curl -X POST 'https://api.example.com/users?team=eng' -H 'Authorization: Bearer t' -d '{"name":"Ada"}'`
    );
    nc.assert.truthy(!!pasted && pasted.nodes.length === 1, 'one node created from curl paste');
    const created = pasted!.nodes[0];
    nc.assert.equal(created.type, 'automation-http-request', 'http node type');
    nc.assert.equal((created.data as any).operation, 'send_http_post_request', 'POST operation');
    nc.assert.equal((created.data as any).config.url, 'https://api.example.com/users', 'url set');
    nc.assert.equal((created.data as any).config.query_params?.[0]?.key, 'team', 'query param set');
    nc.assert.equal((created.data as any).config.body_type, 'json', 'json body');
    // Pasting non-curl prose must NOT create an http node.
    nc.assert.truthy(parseClipboardContent('just some text') === null, 'prose is ignored');

    // GET with a query string -> method GET, query split out of the URL
    const get = parseCurl('curl https://api.example.com/users?page=2&q=hi');
    nc.assert.equal(get.method, 'GET', 'GET method');
    nc.assert.equal(get.url, 'https://api.example.com/users', 'query stripped from url');
    nc.assert.deepEqual(
        get.queryParams.map((r) => [r.key, r.value]),
        [['page', '2'], ['q', 'hi']],
        'query params parsed'
    );

    // POST JSON
    const post = parseCurl(
        `curl -X POST https://api.example.com/users -H 'Content-Type: application/json' -d '{"name":"Ada"}'`
    );
    nc.assert.equal(post.method, 'POST', 'POST method');
    nc.assert.equal(methodToOperation(post.method), 'send_http_post_request', 'operation map');
    nc.assert.equal(post.bodyType, 'json', 'json body type');
    nc.assert.equal(post.body, '{"name":"Ada"}', 'json body preserved');

    // Form-urlencoded -> bodyForm rows (url-decoded)
    const form = parseCurl(
        `curl https://api.example.com/login -H 'Content-Type: application/x-www-form-urlencoded' --data-raw 'user=ada&pw=p%40ss'`
    );
    nc.assert.equal(form.bodyType, 'form_urlencoded', 'form body type');
    nc.assert.deepEqual(
        form.bodyForm.map((r) => [r.key, r.value]),
        [['user', 'ada'], ['pw', 'p@ss']],
        'form rows decoded'
    );

    // Basic auth + insecure
    const basic = parseCurl('curl -u me:secret https://api.example.com/x -k');
    nc.assert.truthy(
        basic.headers.some((h) => h.key === 'Authorization' && h.value.startsWith('Basic ')),
        'basic auth header'
    );
    nc.assert.equal(basic.verifySsl, false, 'insecure -> verifySsl false');

    // -G moves data into query params, forces GET
    const g = parseCurl('curl -G https://api.example.com/search -d q=hello -d limit=5');
    nc.assert.equal(g.method, 'GET', '-G forces GET');
    nc.assert.deepEqual(
        g.queryParams.map((r) => [r.key, r.value]),
        [['q', 'hello'], ['limit', '5']],
        '-G data -> query'
    );

    return { ok: true };
}
