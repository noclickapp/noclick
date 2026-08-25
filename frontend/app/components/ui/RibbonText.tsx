/*
Animated typing-ribbon placeholder shared by HeroPromptShowcase and
FlowCanvasEmptyState. Desktop fades each character in on a stagger; mobile
fades the whole phrase as ONE element — the per-character variant runs a
blur-filter animation on ~45 spans per rotation, and every animating span is
promoted to its own GPU compositing layer on iOS WebKit. That recurring
layer churn (every 2.9s, forever, on an idle page) feeds the per-tab memory
kill ("A problem occurred with this webpage") — same constraint documented
in ParticlesBackground.tsx.
*/
import type { ReactNode } from 'react';
import { useIsMobile, useMediaQuery } from '~/hooks/useIsMobile';

interface RibbonTextProps {
    phrase: string;
    /** Trailing affordance (e.g. Tab/→ keycaps) revealed after the phrase types out. */
    trailing?: ReactNode;
}

export function RibbonText({ phrase, trailing }: RibbonTextProps) {
    // Coarse pointer catches the WebKit-jetsam devices the width check misses:
    // iPhones in landscape (932px CSS on a Pro Max) and iPads.
    const isMobile = useIsMobile(768);
    const isCoarsePointer = useMediaQuery('(pointer: coarse)');
    const cheap = isMobile || isCoarsePointer;

    if (cheap) {
        return (
            <span className="inline-block animate-pill-fade-in" style={{ whiteSpace: 'pre-wrap' }}>
                {phrase}
                {trailing && (
                    <span className="ml-2 inline-flex items-center gap-1 align-middle">{trailing}</span>
                )}
            </span>
        );
    }

    return (
        <>
            {phrase.split('').map((ch, i) => (
                <span
                    key={i}
                    className="inline-block animate-ribbon-fade-in"
                    style={{
                        animationDelay: `${i * 14}ms`,
                        animationFillMode: 'backwards',
                        whiteSpace: 'pre',
                    }}
                >
                    {ch}
                </span>
            ))}
            {trailing && (
                <span
                    className="ml-2 inline-flex items-center gap-1 align-middle animate-ribbon-fade-in"
                    style={{
                        animationDelay: `${phrase.length * 14 + 200}ms`,
                        animationFillMode: 'backwards',
                    }}
                >
                    {trailing}
                </span>
            )}
        </>
    );
}
