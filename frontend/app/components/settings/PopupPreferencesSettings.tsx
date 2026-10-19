// Settings section for in-app popups & banners the user can opt out of. Each row
// toggles a `useSeenOnce` flag (server-backed via the onboarding-completion blob,
// the same store the "Don't show again" controls write to), so toggling here
// re-enables a popup someone previously dismissed. Added so all the scattered
// "don't show again" opt-outs (run-results popup, ChatBox banners) live in one place.
import { Switch } from '~/components/ui/switch';
import { SettingsGroup, SettingsHeader, SettingsRow } from '~/components/settings/SettingsParts';
import { useSeenOncePref, type SeenOnceKey } from '~/hooks/useSeenOnce';

interface PopupToggle {
    prefKey: SeenOnceKey;
    label: string;
    description: string;
}

const POPUPS: PopupToggle[] = [
    {
        prefKey: 'run_results_popup_disabled',
        label: 'Run results',
        description: 'The outputs popup shown after a workflow run finishes.',
    },
    {
        prefKey: 'invite_banner_disabled',
        label: 'Collaboration invite banner',
        description: 'The nudge to share a live invite link for the workflow.',
    },
    {
        prefKey: 'quickpublish_banner_disabled',
        label: 'Publish banner',
        description: 'The nudge to publish your interface to the web.',
    },
];

// One row owns one useSeenOncePref hook (keeps the hook call out of a loop).
function PopupToggleRow({ prefKey, label, description }: PopupToggle) {
    const [disabled, setDisabled] = useSeenOncePref(prefKey);
    return (
        <SettingsRow
            label={label}
            description={description}
            control={<Switch checked={!disabled} aria-label={label} onCheckedChange={(checked) => setDisabled(!checked)} />}
        />
    );
}

export function PopupPreferencesSettings() {
    return (
        <div>
            <SettingsHeader title="Popups" description="Choose which in-app popups and banners appear. Turn one back on after dismissing it." />
            <SettingsGroup>
                {POPUPS.map((p) => (
                    <PopupToggleRow key={p.prefKey} {...p} />
                ))}
            </SettingsGroup>
        </div>
    );
}
