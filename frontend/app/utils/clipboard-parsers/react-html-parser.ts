/**
 * Parser for pasted React/JSX or HTML code.
 *
 * Detects component/markup code on the canvas clipboard and creates an
 * interface-html-react node pre-filled with it — so importing a Claude Artifact
 * (or any snippet) from elsewhere is a single paste at the cursor. Code pasted
 * INTO an editor field is unaffected: the paste handler bails on
 * input/textarea/contenteditable targets before reaching the parser registry.
 *
 * React vs HTML split: code that carries JS (import/export/function/arrow) AND
 * JSX markup → JSX mode (jsx_source); pure markup with no JS → HTML mode
 * (content). The host-mount transform means a default-export component renders
 * without the user adding a ReactDOM mount.
 */

import { Node } from '@xyflow/react';
import { ClipboardParser, ClipboardParseResult } from './types';
import { generateNodeId } from '~/utils/nodeIdGenerator';
import { createWorkflowNode } from '~/lib/applyNodeUpdate';
import { getNodeMetadata } from '~/components/workflow/nodes/nodeRegistry';

// React code reliably imports react / react-dom — the Artifacts shape always does.
const REACT_IMPORT_RE =
    /(?:^|[\n;])\s*import\b[^\n;]*\bfrom\s+['"]react(?:-dom(?:\/client)?)?['"]/;
// A lowercase element tag (<div>, <button>, <h1> …) is JSX/HTML markup. TS
// generics never produce these (they use capitalised type names like <T>).
const MARKUP_TAG_RE =
    /<(?:div|span|button|h[1-6]|p|ul|ol|li|section|main|nav|header|footer|article|input|form|a|img|svg|table|label|select|textarea)[\s/>]/i;
// JS code signals — present in components, absent in pure HTML.
const JS_CODE_RE = /\b(?:import|export|function|const|let|var)\b|=>/;

const HTML_DOCTYPE_RE = /^\s*<!DOCTYPE\s+html/i;
const HTML_ROOT_RE = /^\s*<html[\s>]/i;
const HTML_CLOSING_TAG_RE = /<\/[a-z][\w-]*>/i;

// A fenced code block (```/~~~) at a line start means this is a markdown
// document (README, blog post, chat message), not a component to mount.
const MARKDOWN_FENCE_RE = /(?:^|\n)\s*(?:```|~~~)/;

export function detectCodeKind(text: string): 'react' | 'html' | null {
    if (!text || !text.trim()) return null;
    const t = text.trimStart();

    // JSON is handled by higher-priority parsers (noClick/n8n) and never starts
    // a component; markdown with code fences would transpile-fail. Bail on both.
    if (t.startsWith('{') || t.startsWith('[')) return null;
    if (MARKDOWN_FENCE_RE.test(t)) return null;

    const hasMarkup = MARKUP_TAG_RE.test(t);
    const hasJs = JS_CODE_RE.test(t);

    // React/JSX: an explicit react import, or JSX markup alongside JS code.
    if (REACT_IMPORT_RE.test(t) || (hasMarkup && hasJs)) return 'react';

    // Raw HTML: a document, or a markup fragment with no JS code in it.
    if (HTML_DOCTYPE_RE.test(t) || HTML_ROOT_RE.test(t)) return 'html';
    if (t.startsWith('<') && hasMarkup && HTML_CLOSING_TAG_RE.test(t) && !hasJs) return 'html';

    return null;
}

export const reactHtmlParser: ClipboardParser = {
    name: 'React/HTML code',
    priority: 20, // lowest — only after the specific JSON/URL formats decline

    parse(text: string): ClipboardParseResult | null {
        const kind = detectCodeKind(text);
        if (!kind) return null;

        const nodeId = generateNodeId('interface-html-react');
        const config =
            kind === 'react'
                ? { operation: 'render_jsx_react_interface', jsx_source: text }
                : { operation: 'render_html_interface', content: text };

        // Size the node to the interface block's default dimensions, matching
        // the click-to-add / drag-drop paths — without this the pasted node
        // renders at ReactFlow's auto size (much smaller than usual).
        const dims = getNodeMetadata('interface-html-react')?.dimensions;
        const node: Node = {
            ...createWorkflowNode(
                nodeId,
                'interface-html-react',
                { x: 0, y: 0 }, // repositioned at the cursor by the paste handler
                config,
                { configValid: false },
            ),
            selected: false,
            style: { width: dims?.width ?? 1150, height: dims?.height ?? 800 },
        };

        return { nodes: [node], edges: [] };
    },
};
