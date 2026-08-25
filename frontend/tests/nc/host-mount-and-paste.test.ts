// Verifies (1) the client host-mount transform mirrors the backend — self-mount
// code is untouched, Artifacts-style export-default code is rewritten to mount
// its default, idempotent — and (2) the React/HTML clipboard parser classifies
// and routes correctly without hijacking non-code pastes.
import { applyHostMount } from '~/hooks/useClientTranspile';
import {
    detectCodeKind,
    reactHtmlParser,
} from '~/utils/clipboard-parsers/react-html-parser';
import { parseClipboardContent } from '~/utils/clipboard-parsers';
import { nc } from '~/lib/nc';
import componentCode from './fixtures/user-growth-model.txt?raw';

const SELF_MOUNT = `import React from 'react';
import ReactDOM from 'react-dom/client';
function App(){ return React.createElement('div', null, 'x'); }
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(App));`;

const ARTIFACT_NO_IMPORT = `export default function App(){ return <div className="p-4">hi</div>; }`;
const HTML_DOC = `<!DOCTYPE html><html><body><div class="card"><h1>Title</h1></div></body></html>`;

export default function () {
    // --- host-mount transform ---
    nc.assert.equal(
        applyHostMount(SELF_MOUNT),
        SELF_MOUNT,
        'self-mounting code is byte-identical'
    );

    const fixed = applyHostMount(componentCode);
    nc.assert.truthy(
        fixed.includes('const __ncDefault = CollectionBoard;'),
        'captures the default export'
    );
    nc.assert.truthy(
        !/export\s+default\s+function/.test(fixed),
        'strips the export default statement'
    );
    nc.assert.equal(applyHostMount(fixed), fixed, 'idempotent');

    // --- clipboard classification ---
    nc.assert.equal(
        detectCodeKind(componentCode),
        'react',
        'substantial component → react'
    );
    nc.assert.equal(
        detectCodeKind(ARTIFACT_NO_IMPORT),
        'react',
        'export-default JSX → react'
    );
    nc.assert.equal(detectCodeKind(HTML_DOC), 'html', 'html doc → html');
    nc.assert.equal(
        detectCodeKind('export function id<T>(x:T){return x;}'),
        null,
        'TS generic not misread as JSX'
    );
    nc.assert.equal(
        detectCodeKind('Just a sentence with a < character.'),
        null,
        'plain text ignored'
    );
    nc.assert.equal(
        detectCodeKind('https://docs.google.com/spreadsheets/d/abc/edit'),
        null,
        'url ignored'
    );
    nc.assert.equal(
        detectCodeKind(
            '# README\n```jsx\nimport React; const x = <div/>;\n```'
        ),
        null,
        'markdown with code fence ignored'
    );
    nc.assert.equal(
        detectCodeKind('{"code":"import React; export default () => <div/>"}'),
        null,
        'JSON with embedded JSX ignored'
    );

    // A non-React method named createRoot must NOT suppress host-mount.
    const methodCase = applyHostMount(
        "import React from 'react';\nconst o={createRoot(){}};\nexport default function App(){ o.createRoot(); return <div/>; }"
    );
    nc.assert.truthy(
        methodCase.includes('const __ncDefault = App;'),
        'method .createRoot() is not a self-mount'
    );

    // --- node construction + registry routing ---
    const reactNode = reactHtmlParser.parse(componentCode)?.nodes[0];
    nc.assert.equal(
        reactNode?.type,
        'interface-html-react',
        'builds an interface-html-react node'
    );
    nc.assert.equal(
        reactNode?.data?.operation,
        'render_jsx_react_interface',
        'JSX operation'
    );
    const reactData = reactNode?.data as
        { config?: { jsx_source?: string } } | undefined;
    nc.assert.gt(
        reactData?.config?.jsx_source?.length ?? 0,
        1000,
        'jsx_source filled'
    );
    // Pasted node must carry the interface block's default dimensions (not auto-size).
    const reactStyle = reactNode?.style as
        { width?: number; height?: number } | undefined;
    nc.assert.gt(reactStyle?.width ?? 0, 500, 'node has a real default width');
    nc.assert.gt(
        reactStyle?.height ?? 0,
        400,
        'node has a real default height'
    );

    const htmlNode = reactHtmlParser.parse(HTML_DOC)?.nodes[0];
    nc.assert.equal(
        htmlNode?.data?.operation,
        'render_html_interface',
        'HTML operation'
    );
    const htmlData = htmlNode?.data as { content?: string } | undefined;
    nc.assert.gt(
        htmlData?.content?.length ?? 0,
        10,
        'content filled (top-level field)'
    );

    // A Sheets URL still routes to its own parser, not the code parser.
    nc.assert.equal(
        parseClipboardContent(
            'https://docs.google.com/spreadsheets/d/abc123/edit'
        )?.nodes[0]?.type,
        'automation-google-sheets',
        'sheets URL still wins'
    );

    return { ok: true };
}
