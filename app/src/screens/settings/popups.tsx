// Settings → Popups: which of the app's popups and banners appear, one switch each, so one dismissed with "Don't show
// again" can be turned back on. `PopupsView` draws what it's told; `PopupsSection` is the section with its read
// (popupReads.ts).
import { Switch } from '@/ui/switch';
import popupList from './popups.json';
import { SettingsGroup, SettingsHeader, SettingsRow } from './parts';
import { usePopups, type PopupsShown } from './popupReads';

/** A popup's key (as NoClick names it), and what a person reads for it. */
export interface PopupDef {
    key: string;
    label: string;
    description: string;
}

/** Each popup a person can turn off, in the order the section lists them: one table, `popups.json`, which the backend's
 *  own list of popups is held to. */
export const POPUPS: readonly PopupDef[] = popupList;

/** The section: its header and a switch per popup, each on until it's read off. `shown` null while they're read: the
 *  switches wait, dimmed. */
export function PopupsView({ shown, onToggle }: { shown: PopupsShown | null; onToggle: (key: string, shown: boolean) => void }) {
    const isLoading = shown === null;
    return (
        <div>
            <SettingsHeader title="Popups" description="Choose which in-app popups and banners appear. Turn one back on after dismissing it." />
            <SettingsGroup className={isLoading ? 'opacity-60' : undefined}>
                {POPUPS.map(({ key, label, description }) => (
                    <SettingsRow
                        key={key}
                        label={label}
                        description={description}
                        control={<Switch checked={shown?.[key] ?? true} disabled={isLoading} aria-label={label} onCheckedChange={(checked) => onToggle(key, checked)} />}
                    />
                ))}
            </SettingsGroup>
        </div>
    );
}

/** The section with its read: the client and live frames its host hands it. */
export function PopupsSection() {
    const { shown, toggle } = usePopups();
    return <PopupsView shown={shown} onToggle={(key, value) => void toggle(key, value)} />;
}
