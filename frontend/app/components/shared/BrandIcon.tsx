// BrandIcon is the single, canonical way to render a node / service / credential
// brand logo with its brand color. It applies one color rule everywhere: a
// Tailwind `text-*` iconColor is passed as a class, a raw hex/rgb value as an
// inline `style.color`, and an empty/absent color leaves multicolor brand SVGs
// to paint their own fills (falling back to white on the dark icon wells). It was
// extracted from the rule previously duplicated across NodeIconStack,
// workflow diagnostics, WorkflowEditEventView and the credential surfaces so the
// rule lives in exactly one place and brand colors can't drift between surfaces.
import { type ComponentType, type CSSProperties } from 'react';
import { cn } from '~/lib/utils';

export type BrandIconComponent = ComponentType<{
    className?: string;
    style?: CSSProperties;
}>;

interface BrandIconProps {
    Icon: BrandIconComponent;
    /** Tailwind `text-*` class, a raw hex/rgb value, or '' for multicolor marks. */
    iconColor?: string;
    className?: string;
    /** Extra inline styles (e.g. a drop-shadow); merged with the color branch. */
    style?: CSSProperties;
}

export function BrandIcon({ Icon, iconColor, className, style }: BrandIconProps) {
    const c = iconColor || 'text-foreground';
    const isTw = c.startsWith('text-');
    return (
        <Icon
            className={cn(className, isTw && c)}
            style={!isTw && c ? { ...style, color: c } : style}
        />
    );
}
