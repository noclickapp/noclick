// Verifies the cURL parser used by the HTTP Request node's "Import cURL" action.
// Pure-function test — runs against ~/lib/curlParser without needing a loaded
// workflow. Run: nc_run_test({ file: "tests/nc/curl-import.test.ts" })
import { nc } from '~/lib/nc';
import { parseCurl, methodToOperation } from '~/lib/curlParser';

export default async function () {
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
