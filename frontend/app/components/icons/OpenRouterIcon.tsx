// Custom OpenRouter icon matching their lime-green "OR" lettermark rebrand.
// Replaces the outdated purple @lobehub/icons version with a component that
// implements the same .Avatar / .colorPrimary API so both usage sites work.

import { memo, type CSSProperties } from 'react';

const COLOR = '#97E41E';

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
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            style={{ flex: 'none', lineHeight: 1, ...style }}
            aria-label="OpenRouter"
            {...(rest as Record<string, unknown>)}
        >
            <rect width="24" height="24" rx="5" fill={COLOR} />
            <text
                x="12"
                y="17"
                textAnchor="middle"
                fontFamily="-apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif"
                fontSize="11"
                fontWeight="700"
                fill="white"
                letterSpacing="-0.5"
            >
                OR
            </text>
        </svg>
    );
});

const Avatar = memo(function OpenRouterAvatar({
    size = 32,
    className,
    style,
}: {
    size?: number;
    className?: string;
    style?: CSSProperties;
}) {
    return <Mono size={size} className={className} style={style} />;
});

// Expose the same shape that @lobehub/icons exports so both call sites work:
//   credentialIcons.tsx  → OpenRouter as unknown as IconCmp  (uses Mono)
//   provider.tsx         → OpenRouter.Avatar size={32}       (uses Avatar)
const OpenRouterIcon = Mono as typeof Mono & {
    Avatar: typeof Avatar;
    colorPrimary: string;
    title: string;
};
OpenRouterIcon.Avatar = Avatar;
OpenRouterIcon.colorPrimary = COLOR;
OpenRouterIcon.title = 'OpenRouter';

export default OpenRouterIcon;
