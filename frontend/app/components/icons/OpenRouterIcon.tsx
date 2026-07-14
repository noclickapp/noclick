// Custom OpenRouter icon using the official "or" logomark SVG path + lime-green
// brand color (#C8FF00) from their 2024 rebrand. Implements the same
// .Avatar / .colorPrimary API as @lobehub/icons so both usage sites work.

import { memo, type CSSProperties } from 'react';

const COLOR = '#C8FF00';
const PATH =
    'M18.654 3.87a5.087 5.087 0 110 10.174L23.7 19.09c.64.641.187 1.737-.72 1.737H8.48a8.479 8.479 0 010-16.958h10.175zM8.479 7.26a5.087 5.087 0 100 10.176 5.087 5.087 0 000-10.175z';

const Mono = memo(function OpenRouterMono({
    size = '1em',
    className,
    style,
    ...rest
}: {
    size?: string | number;
    className?: string;
    style?: CSSProperties;
    [key: string]: unknown;
}) {
    return (
        <svg
            viewBox="0 0 24 24"
            width={size}
            height={size}
            className={className}
            fill="currentColor"
            fillRule="evenodd"
            xmlns="http://www.w3.org/2000/svg"
            style={{ flex: 'none', lineHeight: 1, ...style }}
            aria-label="OpenRouter"
            {...(rest as Record<string, unknown>)}
        >
            <title>OpenRouter</title>
            <path d={PATH} />
        </svg>
    );
});

// Avatar renders the mark in lime-green (#C8FF00) on a black rounded background,
// matching the official OpenRouter brand square (black bg + lime icon).
const Avatar = memo(function OpenRouterAvatar({
    size = 32,
    className,
    style,
}: {
    size?: number;
    className?: string;
    style?: CSSProperties;
}) {
    const pad = Math.round(size * 0.125);
    const r = Math.round(size * 0.22);
    return (
        <svg
            viewBox={`0 0 ${size} ${size}`}
            width={size}
            height={size}
            className={className}
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            style={{ flex: 'none', lineHeight: 1, ...style }}
            aria-label="OpenRouter"
        >
            <rect width={size} height={size} rx={r} fill="#000" />
            <svg
                x={pad}
                y={pad}
                width={size - pad * 2}
                height={size - pad * 2}
                viewBox="0 0 24 24"
                fill={COLOR}
                fillRule="evenodd"
            >
                <path d={PATH} />
            </svg>
        </svg>
    );
});

const OpenRouterIcon = Mono as typeof Mono & {
    Avatar: typeof Avatar;
    colorPrimary: string;
    title: string;
};
OpenRouterIcon.Avatar = Avatar;
OpenRouterIcon.colorPrimary = COLOR;
OpenRouterIcon.title = 'OpenRouter';

export default OpenRouterIcon;
