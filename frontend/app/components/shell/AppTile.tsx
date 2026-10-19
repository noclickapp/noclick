// An app tile: one white glyph on a coloured square with a lit top edge, the way a phone draws its apps. The texting
// apps NoClick answers on wear them (ChannelTile), on the sidebar's Text NoClick card and on the landing page.
import type { ComponentType } from 'react';
import { IoLogoWhatsapp } from 'react-icons/io5';
import { cn } from '~/lib/utils';
import type { TextApp } from './textApp';

type Glyph = ComponentType<{ className?: string }>;

type Size = 'sm' | 'md';

export function AppTile({
    glyph: Glyph,
    background,
    size = 'md',
    glyphClassName,
    className,
}: {
    glyph: Glyph;
    background: string;
    size?: Size;
    glyphClassName?: string;
    className?: string;
}) {
    return (
        <span
            className={cn(
                'grid shrink-0 place-items-center text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.28),0_1px_2px_rgba(0,0,0,0.3)]',
                size === 'sm' ? 'h-5 w-5 rounded-[6px]' : 'h-8 w-8 rounded-[10px]',
                className
            )}
            style={{ background }}
        >
            {/* A small glyph follows its tile, so a caller can size the tile up through className. */}
            <Glyph className={glyphClassName ?? (size === 'sm' ? 'h-[60%] w-[60%]' : 'h-[18px] w-[18px]')} />
        </span>
    );
}

/** Messages' mark: a wide white oval, about 1.2 times as wide as tall, its tail hooked at the lower left. */
function MessagesBubble({ className }: { className?: string }) {
    return (
        <svg viewBox="0 0 24 24" aria-hidden="true" className={className} fill="currentColor">
            <ellipse cx="12" cy="11" rx="11.6" ry="9.4" />
            <path d="M5.2 17.6c-.1 2-1.2 3.7-3 4.8 2.8.2 5.4-.8 7.2-2.4z" />
        </svg>
    );
}

// WhatsApp and Messages in their own greens, each mark as large in its tile as on the app's own icon: WhatsApp's
// spans about 65% of it, Messages' oval about three quarters.
const TILES: Record<TextApp, { background: string; glyph: Glyph; glyphSize?: Record<Size, string> }> = {
    whatsapp: {
        background: 'linear-gradient(180deg, #5ef87c 0%, #1fbe3b 100%)',
        glyph: IoLogoWhatsapp,
        glyphSize: { sm: 'h-[75%] w-[75%]', md: 'h-6 w-6' },
    },
    imessage: {
        background: 'linear-gradient(180deg, #6cfa84 0%, #0fb92c 100%)',
        glyph: MessagesBubble,
        glyphSize: { sm: 'h-[76%] w-[76%]', md: 'h-6 w-6' },
    },
};

export function ChannelTile({ channel, size = 'md', className }: { channel: TextApp; size?: Size; className?: string }) {
    const { background, glyph, glyphSize } = TILES[channel];
    return <AppTile glyph={glyph} background={background} size={size} glyphClassName={glyphSize?.[size]} className={className} />;
}
