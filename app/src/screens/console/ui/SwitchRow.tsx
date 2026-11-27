// One on-or-off choice in a form, as a Settings row: its name and what it does on the left (an id it goes by, small,
// under them), the app's switch on the right. Rows stand on their own, divided by hairlines (`SWITCH_ROWS` on their
// list), never in a card.
import type { ReactNode } from 'react';
import { HAIRLINE } from '@/ui/primitives';
import { Switch } from '@/ui/switch';
import { cn } from '@/ui/utils';
import { SettingsRow } from '@/screens/settings/parts';

export const SWITCH_ROWS = cn('m-0 flex list-none flex-col divide-y p-0 dark:divide-foreground/[0.06]', HAIRLINE);

export function SwitchRow({
    label,
    description,
    id,
    checked,
    onCheckedChange,
    disabled,
}: {
    label: string;
    description?: ReactNode;
    /** What the API calls it, shown small under the words. */
    id?: string;
    checked: boolean;
    onCheckedChange: (checked: boolean) => void;
    disabled?: boolean;
}) {
    return (
        <SettingsRow
            className="min-h-0 flex-nowrap px-0 py-2.5"
            label={<span className="text-[13.5px]">{label}</span>}
            description={
                description || id ? (
                    <span className="flex flex-col gap-0.5 text-[12.5px] leading-snug">
                        {description}
                        {id && <span className="font-mono text-[11.5px] text-muted-foreground/80">{id}</span>}
                    </span>
                ) : undefined
            }
            control={<Switch aria-label={label} checked={checked} onCheckedChange={onCheckedChange} disabled={disabled} />}
        />
    );
}
