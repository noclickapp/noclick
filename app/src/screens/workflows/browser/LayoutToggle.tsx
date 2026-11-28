// How a list of automations draws, cards or rows: the Automations page's header toggle, which a space's Automations
// wears too. The choice is a local view preference (useBrowserPreference), never the account's.
import { LayoutGrid, List } from 'lucide-react';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { cn } from '@/ui/utils';

export type BrowserLayoutMode = 'grid' | 'list';

const BUTTON = 'grid h-8 w-8 place-items-center rounded-full transition-colors';
const ON = 'bg-background text-foreground shadow-sm dark:bg-foreground/[0.12] dark:shadow-none';
const OFF = 'text-muted-foreground hover:text-foreground';

export function LayoutToggle({ mode, onChange }: { mode: BrowserLayoutMode; onChange: (mode: BrowserLayoutMode) => void }) {
    return (
        <div className="flex shrink-0 items-center gap-0.5 rounded-full bg-foreground/[0.05] p-0.5">
            <ShortcutTooltip label="Card view" keys={['C']} sideOffset={7}>
                <button type="button" onClick={() => onChange('grid')} aria-label="Card view" aria-pressed={mode === 'grid'} className={cn(BUTTON, mode === 'grid' ? ON : OFF)}>
                    <LayoutGrid className="w-3.5 h-3.5" />
                </button>
            </ShortcutTooltip>
            <ShortcutTooltip label="List view" keys={['L']} sideOffset={7}>
                <button type="button" onClick={() => onChange('list')} aria-label="List view" aria-pressed={mode === 'list'} className={cn(BUTTON, mode === 'list' ? ON : OFF)}>
                    <List className="w-3.5 h-3.5" />
                </button>
            </ShortcutTooltip>
        </div>
    );
}
