// Verifies the HTTP Request node's "Import cURL" integration end-to-end in the
// running app: parsing a curl command and applying it through the standard
// node:update-data event sets the node's method (operation) AND structured
// config (url, query params, headers, body) atomically.
//
// The config-panel visuals (key/value editor, body_type show-if, the Import
// cURL button) are exercised separately; this test stays panel-independent so
// it doesn't depend on canvas viewport/scroll state.
// Run: nc_run_test({ file: "tests/nc/http-node-config.test.ts" })
import { nc } from '~/lib/nc';
import { parseCurl, methodToOperation } from '~/lib/curlParser';

const applyCurl = (nodeId: string, curl: string) => {
    const parsed = parseCurl(curl);
    document.dispatchEvent(
        new CustomEvent('noclick:node:update-data', {
            detail: {
                nodeId,
                data: {
                    config: {
                        url: parsed.url,
                        query_params: parsed.queryParams,
                        headers: parsed.headers,
                        body_type: parsed.bodyType,
                        body: parsed.body,
                        body_form: parsed.bodyForm,
                    },
                    operation: methodToOperation(parsed.method),
                },
            },
        })
    );
};

export default async function () {
    const h = (window as any).__workflowTest;
    const id = 'http_ui_test_node';
    if (nc.nodes.get(id)) nc.nodes.delete(id);
    nc.nodes.add(id, 'automation-http-request', {});
    nc.nodes.update(id, { operation: 'send_http_get_request', config: { url: 'https://x' } });

    // Importing a POST cURL sets the operation + JSON body.
    applyCurl(
        id,
        `curl -X POST 'https://api.example.com/users' -H 'Content-Type: application/json' -d '{"name":"Ada"}'`
    );
    await nc.wait.until(() => h.getNodeById(id)?.data?.config?.url === 'https://api.example.com/users', 3000);
    let node = h.getNodeById(id);
    nc.assert.equal(node.data.operation, 'send_http_post_request', 'POST operation set');
    nc.assert.equal(node.data.config.body_type, 'json', 'json body type');
    nc.assert.equal(node.data.config.body, '{"name":"Ada"}', 'json body set');
    nc.assert.equal(node.data.config.headers?.[0]?.key, 'Content-Type', 'header applied');

    // Re-importing a DELETE with a query string switches the method and splits
    // the query out of the URL into structured rows.
    applyCurl(id, `curl -X DELETE 'https://api.example.com/items/42?soft=true' -H 'X-Api-Key: K'`);
    await nc.wait.until(
        () => h.getNodeById(id)?.data?.operation === 'send_http_delete_request',
        3000
    );
    node = h.getNodeById(id);
    nc.assert.equal(node.data.config.url, 'https://api.example.com/items/42', 'query stripped from url');
    nc.assert.equal(node.data.config.query_params?.[0]?.key, 'soft', 'query param row');
    nc.assert.equal(node.data.config.body_type, 'none', 'DELETE has no body');

    nc.nodes.delete(id);
    return { ok: true };
}
