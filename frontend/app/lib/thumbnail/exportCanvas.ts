// Dependency-free 2D-canvas export for the app-icon ("X + Y") thumbnail mode.
// Redraws the same fixed template as ThumbnailStage (background, glowing icons,
// title + hand-drawn underline) onto a 1280×720 canvas so the PNG
// download is robust (no html-to-image / font-embed / CORS fragility). Reuses the
// shared underline geometry via Path2D so the marker stroke matches the preview.
import {
    THUMB_W,
    THUMB_H,
    titleWords,
    stripPunct,
    measureTitleFontSize,
    loadImage,
    type ComposerState,
    type ImageLayer,
} from './composer';
import { buildUnderline } from './underline';

const BRAND_STACK =
    '"Outfit Variable", "Outfit", ui-sans-serif, system-ui, sans-serif';
const CANVAS_SURFACE = '#09090b';
const CANVAS_GRID = '#27272a';
const GRID_GAP = 14;

function roundRectPath(
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
    w: number,
    h: number,
    r: number
) {
    const rr = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + rr, y);
    ctx.arcTo(x + w, y, x + w, y + h, rr);
    ctx.arcTo(x + w, y + h, x, y + h, rr);
    ctx.arcTo(x, y + h, x, y, rr);
    ctx.arcTo(x, y, x + w, y, rr);
    ctx.closePath();
}

function setTracking(ctx: CanvasRenderingContext2D, px: number) {
    try {
        (
            ctx as CanvasRenderingContext2D & { letterSpacing: string }
        ).letterSpacing = `${px}px`;
    } catch {
        /* unsupported */
    }
}

function drawGrid(ctx: CanvasRenderingContext2D) {
    ctx.save();
    ctx.strokeStyle = CANVAS_GRID;
    ctx.lineWidth = 1;
    ctx.lineCap = 'round';
    ctx.beginPath();
    for (let y = GRID_GAP / 2; y < THUMB_H; y += GRID_GAP) {
        for (let x = GRID_GAP / 2; x < THUMB_W; x += GRID_GAP) {
            ctx.moveTo(x, y - 0.5);
            ctx.lineTo(x, y + 0.5);
            ctx.moveTo(x - 0.5, y);
            ctx.lineTo(x + 0.5, y);
        }
    }
    ctx.stroke();
    ctx.restore();
}

function coverDraw(
    ctx: CanvasRenderingContext2D,
    img: HTMLImageElement,
    x: number,
    y: number,
    w: number,
    h: number
) {
    const ir = img.width / img.height;
    const dr = w / h;
    let sw: number, sh: number, sx: number, sy: number;
    if (ir > dr) {
        sh = img.height;
        sw = sh * dr;
        sx = (img.width - sw) / 2;
        sy = 0;
    } else {
        sw = img.width;
        sh = sw / dr;
        sx = 0;
        sy = (img.height - sh) / 2;
    }
    ctx.drawImage(img, sx, sy, sw, sh, x, y, w, h);
}

function containDraw(
    ctx: CanvasRenderingContext2D,
    img: HTMLImageElement,
    x: number,
    y: number,
    w: number,
    h: number,
    pad: number
) {
    const bw = w * pad;
    const bh = h * pad;
    const s = Math.min(bw / img.width, bh / img.height);
    const dw = img.width * s;
    const dh = img.height * s;
    ctx.drawImage(img, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh);
}

function drawIcon(
    ctx: CanvasRenderingContext2D,
    layer: ImageLayer,
    img: HTMLImageElement,
    x: number,
    y: number,
    size: number,
    glow: number
) {
    const r = size * 0.225;
    if (layer.frame) {
        if (glow > 0) {
            ctx.save();
            ctx.shadowColor = layer.glow;
            ctx.shadowBlur = glow;
            ctx.fillStyle = layer.bg;
            roundRectPath(ctx, x, y, size, size, r);
            ctx.fill();
            ctx.shadowBlur = glow * 0.55;
            roundRectPath(ctx, x, y, size, size, r);
            ctx.fill();
            ctx.restore();
        }
        ctx.save();
        roundRectPath(ctx, x, y, size, size, r);
        ctx.clip();
        ctx.fillStyle = layer.bg;
        ctx.fillRect(x, y, size, size);
        if (layer.fit === 'contain')
            containDraw(ctx, img, x, y, size, size, 0.7);
        else coverDraw(ctx, img, x, y, size, size);
        ctx.restore();
    } else {
        if (glow > 0) {
            ctx.save();
            ctx.shadowColor = layer.glow;
            ctx.shadowBlur = glow * 1.1;
            containDraw(ctx, img, x, y, size, size, 0.9);
            ctx.shadowBlur = glow * 0.6;
            containDraw(ctx, img, x, y, size, size, 0.9);
            ctx.restore();
        }
        containDraw(ctx, img, x, y, size, size, 0.9);
    }
}

function drawPlaceholder(
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
    size: number
) {
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.14)';
    ctx.lineWidth = 2;
    ctx.setLineDash([9, 9]);
    roundRectPath(ctx, x, y, size, size, size * 0.225);
    ctx.stroke();
    ctx.restore();
}

function drawPlus(
    ctx: CanvasRenderingContext2D,
    cx: number,
    cy: number,
    size: number
) {
    const t = size * 0.26;
    const r = t * 0.42;
    ctx.fillStyle = '#ffffff';
    roundRectPath(ctx, cx - size / 2, cy - t / 2, size, t, r);
    ctx.fill();
    roundRectPath(ctx, cx - t / 2, cy - size / 2, t, size, r);
    ctx.fill();
}

function drawArrow(
    ctx: CanvasRenderingContext2D,
    cx: number,
    cy: number,
    size: number
) {
    const w = size * 1.15;
    const shaftT = size * 0.24;
    const shaftLen = w * 0.6;
    const head = size * 0.5;
    const x0 = cx - w / 2;
    ctx.fillStyle = '#ffffff';
    roundRectPath(ctx, x0, cy - shaftT / 2, shaftLen, shaftT, shaftT * 0.35);
    ctx.fill();
    ctx.beginPath();
    ctx.moveTo(x0 + shaftLen * 0.86, cy - head / 2);
    ctx.lineTo(x0 + w, cy);
    ctx.lineTo(x0 + shaftLen * 0.86, cy + head / 2);
    ctx.closePath();
    ctx.fill();
}

// Render the app-icon-mode thumbnail to a fresh 1280×720 canvas.
export async function renderThumbnailCanvas(
    state: ComposerState
): Promise<HTMLCanvasElement> {
    const canvas = document.createElement('canvas');
    canvas.width = THUMB_W;
    canvas.height = THUMB_H;
    const ctx = canvas.getContext('2d')!;

    // ensure the brand font is ready so the title doesn't fall back
    try {
        await Promise.all([
            document.fonts.load('800 150px "Outfit Variable"'),
            document.fonts.load('700 30px "Outfit Variable"'),
        ]);
    } catch {
        /* fonts may 404 in a churned dev server; proceed with fallback */
    }

    // background
    ctx.fillStyle = state.background === 'canvas' ? CANVAS_SURFACE : '#000000';
    ctx.fillRect(0, 0, THUMB_W, THUMB_H);
    if (state.background === 'canvas') drawGrid(ctx);

    // icons — mirror ThumbnailStage: centred, nudged down by 8% of height
    const iS = state.iconSize;
    const rowCY = THUMB_H / 2 + THUMB_H * 0.08;
    const present = state.images.filter((im) => im.src);
    const imgs = await Promise.all(
        present.map((im) => loadImage(im.src as string))
    );
    const sepW = iS * 0.5;
    const sizeOf = (im: ImageLayer) => iS * im.sizeScale;
    // Mirror ThumbnailStage: each icon owns its gap toward the separator; with
    // no separator the two half-gaps meet (0.28 total default).
    const sideGap = (im: ImageLayer) =>
        iS *
        (state.separator === 'none' ? 0.14 : 0.2) *
        state.gapScale *
        im.gapScale;

    if (present.length === 2) {
        const sA = sizeOf(present[0]);
        const sB = sizeOf(present[1]);
        const gapA = sideGap(present[0]);
        const gapB = sideGap(present[1]);
        const midW = state.separator === 'none' ? 0 : sepW;
        const rowW = sA + gapA + midW + gapB + sB;
        let x = (THUMB_W - rowW) / 2;
        drawIcon(
            ctx,
            present[0],
            imgs[0],
            x,
            rowCY - sA / 2,
            sA,
            state.glowStrength
        );
        x += sA + gapA;
        if (state.separator !== 'none') {
            if (state.separator === 'plus')
                drawPlus(ctx, x + sepW / 2, rowCY, sepW);
            else drawArrow(ctx, x + sepW / 2, rowCY, sepW);
            x += sepW;
        }
        x += gapB;
        drawIcon(
            ctx,
            present[1],
            imgs[1],
            x,
            rowCY - sB / 2,
            sB,
            state.glowStrength
        );
    } else if (present.length === 1) {
        const s = sizeOf(present[0]);
        drawIcon(
            ctx,
            present[0],
            imgs[0],
            (THUMB_W - s) / 2,
            rowCY - s / 2,
            s,
            state.glowStrength
        );
    } else {
        const sA = sizeOf(state.images[0]);
        const sB = sizeOf(state.images[1]);
        const gapA = sideGap(state.images[0]);
        const gapB = sideGap(state.images[1]);
        const rowW = sA + gapA + sepW + gapB + sB;
        const x = (THUMB_W - rowW) / 2;
        drawPlaceholder(ctx, x, rowCY - sA / 2, sA);
        drawPlaceholder(ctx, x + sA + gapA + sepW + gapB, rowCY - sB / 2, sB);
    }

    // title
    const words = titleWords(state.title);
    const fontSize =
        state.titleSize > 0
            ? state.titleSize
            : measureTitleFontSize(state.title);
    const topY = 46;
    ctx.font = `800 ${fontSize}px ${BRAND_STACK}`;
    setTracking(ctx, -fontSize * 0.02);
    ctx.textBaseline = 'alphabetic';
    ctx.fillStyle = '#ffffff';
    const fullW = ctx.measureText(state.title).width;
    const startX = (THUMB_W - fullW) / 2;
    const baseY = topY + fontSize * 0.8;
    ctx.fillText(state.title, startX, baseY);

    // underline under the chosen word
    if (state.showUnderline && words.length) {
        const idx =
            state.underlineWord === 'auto'
                ? words.length - 1
                : Math.min(state.underlineWord, words.length - 1);
        const prefix = words.slice(0, idx).join(' ') + (idx > 0 ? ' ' : '');
        const wx0 = startX + ctx.measureText(prefix).width;
        const bare = stripPunct(words[idx]);
        const wordW = ctx.measureText(bare).width;
        const thickness = Math.max(6, fontSize * 0.06);
        const geo = buildUnderline(wordW, thickness, state.seed);
        const uy = topY + fontSize - geo.height * 0.5;
        ctx.save();
        ctx.translate(wx0, uy);
        ctx.fillStyle = '#ffffff';
        ctx.fill(new Path2D(geo.fillPath));
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = geo.strokeWidth;
        ctx.lineCap = 'round';
        ctx.stroke(new Path2D(geo.flickPath));
        ctx.restore();
    }
    setTracking(ctx, 0);

    return canvas;
}
