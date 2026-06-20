// curlParser - parses a `curl` command string into the HTTP Request node's
// config shape (method, url, query params, headers, body). Added so users can
// paste a cURL snippet from any API's docs and have the node configured for
// them. Pure and dependency-free so it can be unit-tested in isolation.

export interface CurlKVRow {
    key: string;
    value: string;
    enabled: boolean;
}

export type CurlBodyType = 'none' | 'json' | 'form_urlencoded' | 'raw';

export interface ParsedCurl {
    method: string; // GET / POST / PUT / PATCH / DELETE
    url: string;
    queryParams: CurlKVRow[];
    headers: CurlKVRow[];
    bodyType: CurlBodyType;
    body: string; // json / raw body text
    bodyForm: CurlKVRow[]; // form_urlencoded rows
    verifySsl?: boolean;
}

const row = (key: string, value: string): CurlKVRow => ({ key, value, enabled: true });

// Shell-style tokenizer: handles single/double quotes, backslash escapes, and
// backslash line-continuations (so multi-line copy-pasted curl works).
function tokenize(input: string): string[] {
    const tokens: string[] = [];
    let cur = '';
    let started = false;
    let i = 0;
    const s = input;

    while (i < s.length) {
        const c = s[i];
        if (c === '\\') {
            if (s[i + 1] === '\n') {
                i += 2;
                continue;
            }
            cur += s[i + 1] ?? '';
            started = true;
            i += 2;
            continue;
        }
        if (c === "'") {
            started = true;
            i++;
            while (i < s.length && s[i] !== "'") cur += s[i++];
            i++; // skip closing quote
            continue;
        }
        if (c === '"') {
            started = true;
            i++;
            while (i < s.length && s[i] !== '"') {
                if (s[i] === '\\' && ['"', '\\', '$', '`'].includes(s[i + 1])) {
                    cur += s[i + 1];
                    i += 2;
                } else {
                    cur += s[i++];
                }
            }
            i++;
            continue;
        }
        if (/\s/.test(c)) {
            if (started) {
                tokens.push(cur);
                cur = '';
                started = false;
            }
            i++;
            continue;
        }
        cur += c;
        started = true;
        i++;
    }
    if (started) tokens.push(cur);
    return tokens;
}

function methodFromFlag(value: string): string {
    return value.trim().toUpperCase();
}

function splitHeader(raw: string): CurlKVRow | null {
    const idx = raw.indexOf(':');
    if (idx === -1) return null;
    const key = raw.slice(0, idx).trim();
    const value = raw.slice(idx + 1).trim();
    if (!key) return null;
    return row(key, value);
}

function base64(input: string): string {
    if (typeof btoa === 'function') return btoa(input);
    // Node / SSR fallback
    return Buffer.from(input, 'utf-8').toString('base64');
}

function parseFormString(data: string): CurlKVRow[] {
    return data
        .split('&')
        .filter(Boolean)
        .map((pair) => {
            const eq = pair.indexOf('=');
            const k = eq === -1 ? pair : pair.slice(0, eq);
            const v = eq === -1 ? '' : pair.slice(eq + 1);
            const dec = (x: string) => {
                try {
                    return decodeURIComponent(x.replace(/\+/g, ' '));
                } catch {
                    return x;
                }
            };
            return row(dec(k), dec(v));
        });
}

/**
 * Parse a `curl` command into the HTTP Request node config shape.
 * Throws if no URL can be found.
 */
export function parseCurl(input: string): ParsedCurl {
    const tokens = tokenize(input.trim());
    if (tokens[0] === 'curl') tokens.shift();

    let url = '';
    let explicitMethod = '';
    let forceGet = false;
    let insecure = false;
    const headers: CurlKVRow[] = [];
    const dataParts: string[] = [];
    const formParts: string[] = [];

    for (let i = 0; i < tokens.length; i++) {
        const t = tokens[i];
        const next = () => tokens[++i] ?? '';

        if (t === '-X' || t === '--request') {
            explicitMethod = methodFromFlag(next());
        } else if (t === '-H' || t === '--header') {
            const h = splitHeader(next());
            if (h) headers.push(h);
        } else if (t === '-A' || t === '--user-agent') {
            headers.push(row('User-Agent', next()));
        } else if (t === '-e' || t === '--referer') {
            headers.push(row('Referer', next()));
        } else if (t === '-b' || t === '--cookie') {
            headers.push(row('Cookie', next()));
        } else if (t === '-u' || t === '--user') {
            headers.push(row('Authorization', `Basic ${base64(next())}`));
        } else if (
            t === '-d' ||
            t === '--data' ||
            t === '--data-raw' ||
            t === '--data-ascii' ||
            t === '--data-binary' ||
            t === '--data-urlencode'
        ) {
            dataParts.push(next());
        } else if (t === '-F' || t === '--form') {
            formParts.push(next());
        } else if (t === '-G' || t === '--get') {
            forceGet = true;
        } else if (t === '-k' || t === '--insecure') {
            insecure = true;
        } else if (t === '--url') {
            url = next();
        } else if (t.startsWith('-')) {
            // Unknown flag. Skip a value for the few common value-taking ones we
            // don't map; otherwise treat as a valueless flag (-L, -s, -i, ...).
            if (['-o', '--output', '-m', '--max-time', '-x', '--proxy', '--connect-timeout'].includes(t)) {
                i++;
            }
        } else if (!url) {
            url = t;
        }
    }

    if (!url) throw new Error('No URL found in the cURL command.');

    // Split any query string out of the URL into structured rows.
    const queryParams: CurlKVRow[] = [];
    try {
        const u = new URL(url);
        u.searchParams.forEach((v, k) => queryParams.push(row(k, v)));
        url = u.origin + u.pathname;
    } catch {
        /* relative/odd URL — leave as-is, no query split */
    }

    const joinedData = dataParts.join('&');

    // -G turns data into query params.
    if (forceGet && joinedData) {
        parseFormString(joinedData).forEach((r) => queryParams.push(r));
    }

    // Body classification.
    let bodyType: CurlBodyType = 'none';
    let body = '';
    let bodyForm: CurlKVRow[] = [];

    const contentTypeHeader = headers
        .find((h) => h.key.toLowerCase() === 'content-type')
        ?.value.toLowerCase();

    if (formParts.length) {
        bodyType = 'form_urlencoded';
        bodyForm = formParts.map((p) => {
            const eq = p.indexOf('=');
            const k = eq === -1 ? p : p.slice(0, eq);
            // Strip curl's @file / <file prefixes — file uploads aren't imported.
            const v = eq === -1 ? '' : p.slice(eq + 1).replace(/^[@<]/, '');
            return row(k, v);
        });
    } else if (joinedData && !forceGet) {
        const trimmed = joinedData.trim();
        const looksJson = trimmed.startsWith('{') || trimmed.startsWith('[');
        const looksForm = /^[^=&\s]+=[^&]*(&[^=&\s]+=[^&]*)*$/.test(trimmed);
        if (contentTypeHeader?.includes('json') || (looksJson && !contentTypeHeader?.includes('urlencoded'))) {
            bodyType = 'json';
            body = joinedData;
        } else if (contentTypeHeader?.includes('x-www-form-urlencoded') || looksForm) {
            bodyType = 'form_urlencoded';
            bodyForm = parseFormString(joinedData);
        } else {
            bodyType = 'raw';
            body = joinedData;
        }
    }

    // Method: explicit -X wins; else POST when there's a body; else GET. -G forces GET.
    let method = explicitMethod || (bodyType !== 'none' ? 'POST' : 'GET');
    if (forceGet) method = 'GET';

    const result: ParsedCurl = {
        method,
        url,
        queryParams,
        headers,
        bodyType,
        body,
        bodyForm,
    };
    if (insecure) result.verifySsl = false;
    return result;
}

const METHOD_TO_OPERATION: Record<string, string> = {
    GET: 'send_http_get_request',
    POST: 'send_http_post_request',
    PUT: 'send_http_put_request',
    PATCH: 'send_http_patch_request',
    DELETE: 'send_http_delete_request',
};

/** Map an HTTP method to the node's operation id (unsupported verbs -> GET). */
export function methodToOperation(method: string): string {
    return METHOD_TO_OPERATION[method.toUpperCase()] ?? 'send_http_get_request';
}
