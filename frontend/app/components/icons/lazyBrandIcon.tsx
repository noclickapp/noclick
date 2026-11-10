// A @lobehub/icons brand mark loaded when it's first drawn. Each mark's module carries its avatar, mono, colour and
// wordmark drawings, so importing the forty-odd AI providers' marks up front put them in every page's first load
// (they rode in with the provider metadata most of the app reads for titles and keys). Drawn before its module has
// arrived, a mark holds its place at its size.
import type { ComponentType, CSSProperties } from 'react';
import { useLazyModule } from '~/hooks/useLazyModule';

type MarkProps = { className?: string; size?: number | string; style?: CSSProperties };

/** What a @lobehub/icons mark's module exports (OpenRouterIcon follows it too); each mark types its own props. */
interface BrandMarks {
    Avatar: ComponentType<{ size?: number }>;
    Color?: ComponentType<MarkProps>;
}

export type LoadBrandMarks = () => Promise<{ default: unknown }>;

function useBrandMarks(load: LoadBrandMarks): BrandMarks | undefined {
    return useLazyModule(load)?.default as BrandMarks | undefined;
}

function Placeholder({ size, className }: { size?: number | string; className?: string }) {
    return <span aria-hidden className={className} style={{ display: 'inline-block', width: size, height: size }} />;
}

/** The mark's avatar (its square tile). */
export function BrandAvatar({ load, size }: { load: LoadBrandMarks; size: number }) {
    const marks = useBrandMarks(load);
    return marks ? <marks.Avatar size={size} /> : <Placeholder size={size} />;
}

const glyphs = new Map<LoadBrandMarks, ComponentType<MarkProps>>();

/** The mark's own glyph, in its brand colour where it has one, as a component (the same one for the same mark). */
export function brandGlyph(load: LoadBrandMarks): ComponentType<MarkProps> {
    let glyph = glyphs.get(load);
    if (!glyph) {
        glyph = function BrandGlyph({ className, size, style }: MarkProps) {
            const marks = useBrandMarks(load);
            const Glyph = (marks?.Color ?? marks) as ComponentType<MarkProps> | undefined;
            return Glyph ? <Glyph className={className} size={size} style={style} /> : <Placeholder size={size} className={className} />;
        };
        glyphs.set(load, glyph);
    }
    return glyph;
}
