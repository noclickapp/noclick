// The look a terminal on an agent's machine takes (LiveTerminal, the machine page's shell): xterm.js's font, its
// palette read from the theme in use (the code tokens for its hues, the well's own colour behind), and the well it
// sits in.

/** What a terminal's owner asks of it: Copy, the selection or everything. */
export interface TerminalApi {
    /** Copies the selection, or everything when nothing's selected; says which. */
    copy(): Promise<'selection' | 'all'>;
}

export const FONT = 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Monaco, Consolas, monospace';

function hsl(token: string): string {
    const raw = getComputedStyle(document.documentElement).getPropertyValue(`--${token}`).trim();
    const [h, s, l] = raw.split(/\s+/).map((v) => parseFloat(v));
    return hslHex(h, s, l);
}

function hslHex(h: number, s: number, l: number): string {
    const a = (s / 100) * Math.min(l / 100, 1 - l / 100);
    const f = (n: number) => {
        const k = (n + h / 30) % 12;
        const v = l / 100 - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
        return Math.round(v * 255)
            .toString(16)
            .padStart(2, '0');
    };
    return `#${f(0)}${f(8)}${f(4)}`;
}

function rgbHex(css: string): string {
    const [r, g, b] = (css.match(/[\d.]+/g) ?? ['0', '0', '0']).map(Number);
    return `#${[r, g, b].map((v) => Math.round(v).toString(16).padStart(2, '0')).join('')}`;
}

/** The terminal's palette from the theme in use: the code tokens for its hues, the well's own colour behind. */
export function themeOf(well: HTMLElement) {
    const dark = document.documentElement.classList.contains('dark');
    const background = rgbHex(getComputedStyle(well).backgroundColor);
    const cyan = dark ? hslHex(187, 62, 64) : hslHex(190, 80, 28);
    return {
        background,
        foreground: dark ? '#e4e4e7' : '#27272a',
        cursor: background,
        cursorAccent: background,
        selectionBackground: dark ? 'rgba(250,250,250,0.24)' : 'rgba(9,9,11,0.14)',
        selectionInactiveBackground: dark ? 'rgba(250,250,250,0.16)' : 'rgba(9,9,11,0.09)',
        black: dark ? '#52525b' : '#27272a',
        red: hsl('code-keyword'),
        green: hsl('code-tag'),
        yellow: hsl('code-variable'),
        blue: hsl('code-number'),
        magenta: hsl('code-function'),
        cyan,
        white: dark ? '#d4d4d8' : '#3f3f46',
        brightBlack: hsl('muted-foreground'),
        brightRed: hsl('code-keyword'),
        brightGreen: hsl('code-tag'),
        brightYellow: hsl('code-variable'),
        brightBlue: hsl('code-number'),
        brightMagenta: hsl('code-function'),
        brightCyan: cyan,
        brightWhite: dark ? '#fafafa' : '#09090b',
        scrollbarSliderBackground: dark ? 'rgba(250,250,250,0.14)' : 'rgba(9,9,11,0.14)',
        scrollbarSliderHoverBackground: dark ? 'rgba(250,250,250,0.24)' : 'rgba(9,9,11,0.24)',
        scrollbarSliderActiveBackground: dark ? 'rgba(250,250,250,0.32)' : 'rgba(9,9,11,0.32)',
    };
}

/** The well a terminal sits in: the theme's sunken surface with a hairline, rounded to fit where it is. */
export const WELL = 'bg-muted ring-1 ring-inset ring-border/70 dark:bg-sunken dark:ring-foreground/[0.07]';
