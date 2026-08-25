// Marketing variant of NodeIconStack. Renders a horizontal stack of node/brand
// icons from PRE-SERIALIZED markup (produced server-side by lib/nodeCatalog.server)
// instead of resolving each via getNodeMetadata at runtime — so the public templates
// page can show icon stacks without importing the heavy node registry into its client
// bundle. Layout mirrors NodeIconStack (boxed icons + "+N" overflow chip); the SIZES
// table is intentionally duplicated rather than imported from NodeIconStack, since
// that module pulls the registry.
import { cn } from '~/lib/utils';
import { SerializedIcon } from '~/components/shared/SerializedIcon';

/** Minimal serialized icon entry (structurally a subset of SerializedNodeMeta). */
export interface SerializedIconEntry {
    iconHtml: string;
    iconColor: string;
    label: string;
}

const SIZES = {
    sm: { box: 'w-6 h-6 rounded-md', icon: 'w-3.5 h-3.5', gap: 'gap-1', overflow: 'text-[0.625rem]' },
    md: { box: 'w-8 h-8 rounded-lg', icon: 'w-4 h-4', gap: 'gap-2', overflow: 'text-xs' },
    lg: { box: 'w-9 h-9 rounded-xl', icon: 'w-5 h-5', gap: 'gap-2.5', overflow: 'text-xs' },
} as const;

interface SerializedNodeIconStackProps {
    nodeTypes: string[];
    /** type → serialized icon entry, from the route loader (nodeCatalog.server). */
    icons: Record<string, SerializedIconEntry>;
    size?: keyof typeof SIZES;
    /** Cap on rendered icons; the rest collapse into a "+N" chip. */
    maxShown?: number;
    /** Total for the "+N" chip (e.g. a template's full node_count). */
    totalCount?: number;
    /** Optional pre-filter on node types. */
    filter?: (type: string) => boolean;
    /** Render bare glyphs with no boxed background/border. */
    bare?: boolean;
    className?: string;
}

export function SerializedNodeIconStack({
    nodeTypes,
    icons,
    size = 'md',
    maxShown = Infinity,
    totalCount,
    filter,
    bare = false,
    className,
}: SerializedNodeIconStackProps) {
    const entries = nodeTypes
        .filter((t) => (filter ? filter(t) : true))
        .map((type) => {
            const entry = icons[type];
            return entry && entry.iconHtml ? { type, entry } : null;
        })
        .filter((x): x is { type: string; entry: SerializedIconEntry } => x !== null);
    if (entries.length === 0) return null;

    const shown = entries.slice(0, maxShown);
    const extra = (totalCount ?? entries.length) - shown.length;
    const s = SIZES[size];

    return (
        <div className={cn('flex items-center', s.gap, className)}>
            {shown.map(({ type, entry }) => (
                <div
                    key={type}
                    title={entry.label || type}
                    className={cn(
                        'flex items-center justify-center',
                        bare ? 'shrink-0' : cn(s.box, 'bg-foreground/[0.04] border border-border dark:border-white/[0.08]')
                    )}
                >
                    <SerializedIcon html={entry.iconHtml} iconColor={entry.iconColor} className={s.icon} />
                </div>
            ))}
            {extra > 0 && <span className={cn(s.overflow, 'text-muted-foreground/70 dark:text-white/30')}>+{extra}</span>}
        </div>
    );
}
