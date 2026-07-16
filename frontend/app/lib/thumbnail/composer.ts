// Browser-only helpers for the thumbnail generator (`/thumbnail-generator`):
// glow extraction, SVG dimension-normalization, file→image loading, the built-in
// Claude sunburst icon, and parsing a pasted NoClick-workflow clipboard blob into
// the raw backend {nodes,edges} shape that ReadOnlyFlowCanvas consumes. Kept
// framework-agnostic so it can be unit-tested and reused outside the route.

export const THUMB_W = 1280;
export const THUMB_H = 720;

export type Separator = 'plus' | 'arrow' | 'none';
export type Fit = 'cover' | 'contain';
export type BackgroundType = 'black' | 'canvas';
export type ContentMode = 'images' | 'workflow';
export type ClaudeVariant = 'orange' | 'white';

export const CLAUDE_ORANGE = '#e0673c';
export const CLAUDE_GLOW_LIGHT = '#f0d9ce';

export interface ImageLayer {
    id: 'A' | 'B';
    src: string | null;
    label: string;
    glow: string;
    glowAuto: boolean;
    bg: string;
    frame: boolean;
    fit: Fit;
}

export interface WorkflowGraph {
    // Backend-shaped nodes: each carries a top-level `config` (NOT `data.config`).
    nodes: Array<{
        id: string;
        type: string;
        position: { x: number; y: number };
        config: unknown;
        width?: number;
        height?: number;
    }>;
    edges: Array<Record<string, unknown>>;
}

export function newImageLayer(id: 'A' | 'B'): ImageLayer {
    return {
        id,
        src: null,
        label: '',
        glow: id === 'A' ? CLAUDE_ORANGE : CLAUDE_GLOW_LIGHT,
        glowAuto: true,
        bg: '#ffffff',
        frame: true,
        fit: 'cover',
    };
}

export interface ComposerState {
    title: string;
    underlineWord: number | 'auto'; // which word gets the underline
    showUnderline: boolean;
    background: BackgroundType;
    contentMode: ContentMode;
    images: [ImageLayer, ImageLayer];
    separator: Separator;
    workflow: WorkflowGraph | null;
    iconSize: number;
    glowStrength: number;
    titleSize: number; // 0 = auto-fit to width
    seed: number;
    workflowKey: number; // bump to force ReadOnlyFlowCanvas to re-mount + re-fit
    nodeGlow: string; // glow color behind workflow nodes
}

export function initialComposerState(): ComposerState {
    return {
        title: 'Feels illegal.',
        underlineWord: 'auto',
        showUnderline: true,
        background: 'black',
        contentMode: 'images',
        images: [newImageLayer('A'), newImageLayer('B')],
        separator: 'plus',
        workflow: null,
        iconSize: 300,
        glowStrength: 70,
        titleSize: 0,
        seed: 1234,
        workflowKey: 0,
        nodeGlow: '#3f7bff',
    };
}

export function titleWords(title: string): string[] {
    return title.trim().length ? title.trim().split(/\s+/) : [];
}
export function stripPunct(w: string): string {
    return w.replace(/[.,!?;:]+$/, '');
}

const BRAND_FONT = (size: number) =>
    `800 ${size}px "Outfit Variable", "Outfit", ui-sans-serif, system-ui, sans-serif`;

// Width (px) of `text` at the given brand-font size — used to size the underline.
// Deterministic (recomputes on render) unlike a ResizeObserver, which doesn't
// reliably fire when a parent font-size cascades down.
export function measureWordWidth(text: string, fontSize: number): number {
    if (typeof document === 'undefined' || !text) return 0;
    const c = document.createElement('canvas');
    const ctx = c.getContext('2d');
    if (!ctx) return 0;
    ctx.font = BRAND_FONT(fontSize);
    try {
        (
            ctx as CanvasRenderingContext2D & { letterSpacing: string }
        ).letterSpacing = `${-fontSize * 0.02}px`;
    } catch {
        /* letterSpacing unsupported */
    }
    return ctx.measureText(text).width;
}

// Largest single-line font size (px) that fits `text` within maxWidth, using the
// brand face. Mirrors the DOM title's font so the measured size doesn't overflow.
export function measureTitleFontSize(text: string, maxWidth = 1120): number {
    if (typeof document === 'undefined' || !text.trim()) return 150;
    const c = document.createElement('canvas');
    const ctx = c.getContext('2d');
    if (!ctx) return 150;
    let size = 190;
    while (size > 60) {
        ctx.font = BRAND_FONT(size);
        try {
            (
                ctx as CanvasRenderingContext2D & { letterSpacing: string }
            ).letterSpacing = `${-size * 0.02}px`;
        } catch {
            /* letterSpacing unsupported — measurement is a hair wide, which is safe */
        }
        if (ctx.measureText(text).width <= maxWidth) break;
        size -= 3;
    }
    return size;
}

// ---------- color ----------
function rgbToHsl(r: number, g: number, b: number) {
    r /= 255;
    g /= 255;
    b /= 255;
    const mx = Math.max(r, g, b);
    const mn = Math.min(r, g, b);
    let h = 0;
    let s = 0;
    const l = (mx + mn) / 2;
    if (mx !== mn) {
        const d = mx - mn;
        s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn);
        switch (mx) {
            case r:
                h = (g - b) / d + (g < b ? 6 : 0);
                break;
            case g:
                h = (b - r) / d + 2;
                break;
            default:
                h = (r - g) / d + 4;
        }
        h /= 6;
    }
    return { h: h * 360, s, l };
}
function rgbToHex(r: number, g: number, b: number): string {
    const h = (n: number) =>
        Math.max(0, Math.min(255, Math.round(n)))
            .toString(16)
            .padStart(2, '0');
    return '#' + h(r) + h(g) + h(b);
}
function hslToHex(h: number, s: number, l: number): string {
    h /= 360;
    const f = (n: number) => {
        const k = (n + h * 12) % 12;
        const a = s * Math.min(l, 1 - l);
        return l - a * Math.max(-1, Math.min(k - 3, Math.min(9 - k, 1)));
    };
    return rgbToHex(f(0) * 255, f(8) * 255, f(4) * 255);
}

// Average + punch-up an image's color for a matching glow.
export function extractGlow(img: HTMLImageElement): string {
    const s = 24;
    const oc = document.createElement('canvas');
    oc.width = s;
    oc.height = s;
    const octx = oc.getContext('2d');
    if (!octx) return '#888888';
    octx.drawImage(img, 0, 0, s, s);
    let data: Uint8ClampedArray;
    try {
        data = octx.getImageData(0, 0, s, s).data;
    } catch {
        return '#888888';
    }
    let r = 0;
    let g = 0;
    let b = 0;
    let n = 0;
    for (let i = 0; i < data.length; i += 4) {
        if (data[i + 3] < 40) continue;
        const pr = data[i];
        const pg = data[i + 1];
        const pb = data[i + 2];
        const { s: sat, l } = rgbToHsl(pr, pg, pb);
        const w = Math.max(
            0.05,
            0.25 + sat * 1.2 * (1 - Math.abs(l - 0.55) * 1.4)
        );
        r += pr * w;
        g += pg * w;
        b += pb * w;
        n += w;
    }
    if (n === 0) return '#888888';
    const hsl = rgbToHsl(r / n, g / n, b / n);
    const sat = Math.min(1, hsl.s * 1.35 + 0.08);
    const l = Math.min(0.72, Math.max(0.5, hsl.l + 0.08));
    return hslToHex(hsl.h, sat, l);
}

// Does the image carry meaningful transparency (i.e. it's a logo, not a full tile)?
export function detectTransparency(img: HTMLImageElement): boolean {
    try {
        const s = 26;
        const oc = document.createElement('canvas');
        oc.width = s;
        oc.height = s;
        const g = oc.getContext('2d');
        if (!g) return false;
        g.drawImage(img, 0, 0, s, s);
        const d = g.getImageData(0, 0, s, s).data;
        let trans = 0;
        for (let i = 3; i < d.length; i += 4) if (d[i] < 230) trans++;
        return trans > s * s * 0.06;
    } catch {
        return false;
    }
}

// Ensure an SVG has explicit width/height so it rasterizes crisply.
export function normalizeSvg(svgText: string): string | null {
    try {
        const doc = new DOMParser().parseFromString(svgText, 'image/svg+xml');
        const svg = doc.documentElement;
        if (!svg || svg.nodeName.toLowerCase() !== 'svg') return null;
        let w = parseFloat(svg.getAttribute('width') || '');
        let h = parseFloat(svg.getAttribute('height') || '');
        const vb = svg.getAttribute('viewBox');
        if ((!w || !h) && vb) {
            const p = vb.split(/[\s,]+/).map(Number);
            if (p.length === 4) {
                w = w || p[2];
                h = h || p[3];
            }
        }
        w = w || 512;
        h = h || 512;
        const scale = 512 / Math.max(w, h);
        svg.setAttribute('width', String(Math.round(w * scale)));
        svg.setAttribute('height', String(Math.round(h * scale)));
        return new XMLSerializer().serializeToString(svg);
    } catch {
        return null;
    }
}

// ---------- file → image ----------
function readFile(file: File, mode: 'text' | 'dataurl'): Promise<string> {
    return new Promise((resolve, reject) => {
        const rd = new FileReader();
        rd.onload = () => resolve(rd.result as string);
        rd.onerror = () => reject(rd.error);
        if (mode === 'text') rd.readAsText(file);
        else rd.readAsDataURL(file);
    });
}

// Turn a dropped/uploaded File into a canvas-ready src (SVGs get dimension-normalized).
export async function fileToImageSrc(
    file: File
): Promise<{ src: string; label: string }> {
    const isSvg =
        file.type === 'image/svg+xml' || /\.svg$/i.test(file.name || '');
    if (isSvg) {
        const text = await readFile(file, 'text');
        const norm = normalizeSvg(text) || text;
        return {
            src: 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(norm),
            label: file.name || 'image.svg',
        };
    }
    return {
        src: await readFile(file, 'dataurl'),
        label: file.name || 'image',
    };
}

export function loadImage(src: string): Promise<HTMLImageElement> {
    return new Promise((resolve, reject) => {
        const im = new Image();
        im.onload = () => resolve(im);
        im.onerror = reject;
        im.src = src;
    });
}

// ---------- built-in Claude sunburst icon ----------
export function makeClaudeIconDataUrl(variant: ClaudeVariant): string {
    const S = 512;
    const c = document.createElement('canvas');
    c.width = S;
    c.height = S;
    const g = c.getContext('2d')!;
    const bg = variant === 'orange' ? CLAUDE_ORANGE : '#ffffff';
    const fg = variant === 'orange' ? '#ffffff' : CLAUDE_ORANGE;
    const r = S * 0.225;
    g.fillStyle = bg;
    g.beginPath();
    g.moveTo(r, 0);
    g.arcTo(S, 0, S, S, r);
    g.arcTo(S, S, 0, S, r);
    g.arcTo(0, S, 0, 0, r);
    g.arcTo(0, 0, S, 0, r);
    g.closePath();
    g.fill();

    const cx = S / 2;
    const cy = S / 2;
    const rOut = S * 0.34;
    const rIn = S * 0.045;
    const halfW = S * 0.052;
    const spokes = 12;
    g.fillStyle = fg;
    for (let i = 0; i < spokes; i++) {
        const a = (i / spokes) * Math.PI * 2 - Math.PI / 2;
        const ca = Math.cos(a);
        const sa = Math.sin(a);
        const pa = a + Math.PI / 2;
        const px = Math.cos(pa);
        const py = Math.sin(pa);
        const mid = rIn + (rOut - rIn) * 0.5;
        const tipX = cx + ca * rOut;
        const tipY = cy + sa * rOut;
        const inX = cx + ca * rIn;
        const inY = cy + sa * rIn;
        g.beginPath();
        g.moveTo(inX, inY);
        g.quadraticCurveTo(
            cx + ca * mid + px * halfW,
            cy + sa * mid + py * halfW,
            tipX,
            tipY
        );
        g.quadraticCurveTo(
            cx + ca * mid - px * halfW,
            cy + sa * mid - py * halfW,
            inX,
            inY
        );
        g.closePath();
        g.fill();
    }
    g.beginPath();
    g.arc(cx, cy, S * 0.075, 0, Math.PI * 2);
    g.fill();
    return c.toDataURL('image/png');
}

// ---------- paste a workflow ----------
export type ParseWorkflowResult =
    | { ok: true; graph: WorkflowGraph; count: number }
    | { ok: false; error: string };

// Parse a pasted NoClick clipboard blob (⌘C in the editor) OR a full
// workflow/template export into the raw backend {nodes,edges}. We deliberately do
// NOT route through noClickParser: that converts nodes into the internal
// `data.config` model and regenerates ids, whereas ReadOnlyFlowCanvas wants the
// backend shape (top-level `config`). For a static thumbnail we keep ids as-is.
interface RawBlob {
    type?: string;
    nodes?: unknown[];
    edges?: unknown[];
    workflow_data?: { nodes?: unknown[]; edges?: unknown[] };
}

export function parsePastedWorkflow(text: string): ParseWorkflowResult {
    let data: RawBlob;
    try {
        data = JSON.parse(text.trim()) as RawBlob;
    } catch {
        return {
            ok: false,
            error: "That doesn't look like workflow JSON. Copy nodes in the editor (⌘C) and paste here.",
        };
    }
    let nodes: unknown[] | undefined;
    let edges: unknown[] | undefined;
    if (data?.type === 'noclick-workflow' && Array.isArray(data.nodes)) {
        nodes = data.nodes;
        edges = data.edges;
    } else if (Array.isArray(data?.workflow_data?.nodes)) {
        nodes = data.workflow_data.nodes;
        edges = data.workflow_data.edges;
    } else if (Array.isArray(data?.nodes) && Array.isArray(data?.edges)) {
        nodes = data.nodes;
        edges = data.edges;
    }
    if (!nodes || !nodes.length) {
        return {
            ok: false,
            error: 'No nodes found. Select some nodes in the editor, copy (⌘C), and paste here.',
        };
    }
    const missing = nodes.find(
        (n) =>
            !n ||
            typeof n !== 'object' ||
            (n as { config?: unknown }).config === undefined
    );
    if (missing) {
        return {
            ok: false,
            error: 'These nodes are missing config — copy them fresh from the editor canvas (⌘C).',
        };
    }
    return {
        ok: true,
        count: nodes.length,
        graph: {
            nodes: nodes as WorkflowGraph['nodes'],
            edges: (edges || []) as WorkflowGraph['edges'],
        },
    };
}
