// Hero brand lockup for a CLI harness on the /agents pages. When the vendor has a
// full wordmark SVG (OpenCode/OpenClaw/Hermes — getHarnessNodeIcon returns
// includesName=true) we render that wordmark at logo size. Otherwise (Claude
// Code/Codex have only a brand mark) we compose the boxed mark + the name set in
// the brand font: Outfit is a geometric/rounded sans close to OpenAI Sans and an
// acceptable stand-in for Anthropic's Styrene (both vendors' real wordmark fonts
// are proprietary and can't be embedded). Added so every agent-page hero shows a
// full brand lockup, not just the small square.

import { SerializedIcon } from '~/components/shared/SerializedIcon';

export function HarnessWordmark({
    iconHtml,
    iconColor,
    includesName,
    name,
    slug,
    size = 'hero',
}: {
    iconHtml: string;
    iconColor: string;
    includesName: boolean;
    name: string;
    slug: string;
    /** 'card' is the compact lockup for pickers/tiles; 'hero' is the page header. */
    size?: 'hero' | 'card';
}) {
    const card = size === 'card';
    // Full wordmark: render the (wide) <img> height-driven so its aspect is
    // preserved — SerializedIcon would force w-full/h-full and squish it.
    if (includesName && iconHtml) {
        return (
            <span
                className={
                    card
                        ? 'inline-flex items-center [&>img]:h-6 [&>img]:w-auto'
                        : 'inline-flex items-center [&>img]:h-12 [&>img]:w-auto'
                }
                dangerouslySetInnerHTML={{ __html: iconHtml }}
            />
        );
    }
    // No wordmark — bare brand mark + the harness name in the brand font, no
    // boxed badge so the mark reads as part of one seamless lockup with the name.
    // clawd.svg (Claude) has heavy internal whitespace so it renders small in a
    // square box — scale it up to sit at the same visual size as the others (the
    // transparent overflow is harmless since there's no box to clip it).
    const markScale = slug === 'claude-code' ? 'scale-[1.4]' : '';
    return (
        <span className={card ? 'inline-flex items-center gap-1.5' : 'inline-flex items-center gap-2.5'}>
            <SerializedIcon
                html={iconHtml}
                iconColor={iconColor}
                className={`${card ? 'w-6 h-6' : 'w-11 h-11'} ${markScale}`}
            />
            <span
                className={
                    card
                        ? 'font-brand text-[17px] font-semibold tracking-tight text-white leading-none'
                        : 'font-brand text-4xl font-semibold tracking-tight text-white leading-none'
                }
            >
                {name}
            </span>
        </span>
    );
}
