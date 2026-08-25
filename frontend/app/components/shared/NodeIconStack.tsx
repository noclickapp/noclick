// Horizontal stack of node/integration brand logos for a workflow.
// Used by the workflow-browser list rows and the command palette. Resolves node
// brand icons from the serialized node-icon singleton (populated by the dashboard
// loader) rather than the heavy node registry, so these always-mounted surfaces
// stay off the registry's ~4.7MB component graph. Icons render via SerializedIcon
// (pre-rendered HTML); the public templates/integration pages use the parallel
// SerializedNodeIconStack fed from their own loaders.
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';
import { SerializedIcon } from '~/components/shared/SerializedIcon';
import { cn } from '~/lib/utils';

const SIZES = {
    sm: {
        box: 'w-6 h-6 rounded-md',
        icon: 'w-3.5 h-3.5',
        iconBare: 'h-3.5',
        gap: 'gap-1',
        overflow: 'text-[0.625rem]',
    },
    md: {
        box: 'w-8 h-8 rounded-lg',
        icon: 'w-4 h-4',
        iconBare: 'h-4',
        gap: 'gap-2',
        overflow: 'text-xs',
    },
    lg: {
        box: 'w-9 h-9 rounded-xl',
        icon: 'w-5 h-5',
        iconBare: 'h-5',
        gap: 'gap-2.5',
        overflow: 'text-xs',
    },
} as const;

interface NodeIconStackProps {
    nodeTypes: string[];
    size?: keyof typeof SIZES;
    /** Cap on rendered icons; the rest collapse into a "+N" chip. */
    maxShown?: number;
    /** Total for the "+N" chip (e.g. a template's full node_count). Defaults to the resolved-icon count. */
    totalCount?: number;
    /** Optional pre-filter on node types (e.g. drop bare control-flow utilities). */
    filter?: (type: string) => boolean;
    /** Render bare glyphs with no boxed background/border (e.g. command palette). */
    bare?: boolean;
    className?: string;
}

export function NodeIconStack({
    nodeTypes,
    size = 'md',
    maxShown = Infinity,
    totalCount,
    filter,
    bare = false,
    className,
}: NodeIconStackProps) {
    const entries = nodeTypes
        .filter((t) => (filter ? filter(t) : true))
        .map((type) => {
            const meta = getNodeIconMeta(type);
            return meta?.iconHtml
                ? {
                      type,
                      iconHtml: meta.iconHtml,
                      color: meta.iconColor,
                      label: meta.label,
                  }
                : null;
        })
        .filter(
            (
                x
            ): x is {
                type: string;
                iconHtml: string;
                color: string;
                label: string;
            } => x !== null
        );
    if (entries.length === 0) return null;

    const shown = entries.slice(0, maxShown);
    const extra = (totalCount ?? entries.length) - shown.length;
    const s = SIZES[size];

    return (
        <div className={cn('flex items-center', s.gap, className)}>
            {shown.map(({ type, iconHtml, color, label }) => {
                // Bare <img> marks keep their intrinsic aspect (height-only class +
                // autoWidth) so tall/wide marks don't carry contain-fit side margins
                // that read as uneven gaps; inline <svg> glyphs stay square (they
                // have no reliable intrinsic ratio). Boxed chips are always square.
                const bareImg = bare && iconHtml.trimStart().startsWith('<img');
                return (
                    <div
                        key={type}
                        title={label || type}
                        className={cn(
                            'flex items-center justify-center',
                            // Boxed: fixed-size chip with bg/border. Bare: no box —
                            // the glyph sizes itself (s.icon) and the row gap spaces
                            // them, so the icons read a touch larger and tighter.
                            bare
                                ? 'shrink-0'
                                : cn(s.box, 'bg-foreground/[0.04] border border-border dark:border-white/[0.08]')
                        )}
                    >
                        <SerializedIcon
                            html={iconHtml}
                            iconColor={color}
                            className={bareImg ? s.iconBare : s.icon}
                            autoWidth={bareImg}
                        />
                    </div>
                );
            })}
            {extra > 0 && (
                <span className={cn(s.overflow, 'text-muted-foreground/70 dark:text-white/30')}>
                    +{extra}
                </span>
            )}
        </div>
    );
}
