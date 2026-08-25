// Settings section for in-app popups & banners the user can opt out of. Each row
// toggles a `useSeenOnce` flag (server-backed via the onboarding-completion blob,
// the same store the "Don't show again" controls write to), so toggling here
// re-enables a popup someone previously dismissed. Added so all the scattered
// "don't show again" opt-outs (run-results popup, ChatBox banners) live in one place.
import { ListChecks, UserPlus, Globe } from 'lucide-react';
import { cn } from '~/lib/utils';
import { Switch } from '~/components/ui/switch';
import { useSeenOncePref, type SeenOnceKey } from '~/hooks/useSeenOnce';

interface PopupToggle {
    prefKey: SeenOnceKey;
    label: string;
    description: string;
    icon: typeof ListChecks;
}

const POPUPS: PopupToggle[] = [
    {
        prefKey: 'run_results_popup_disabled',
        label: 'Run results',
        description: 'The outputs popup shown after a workflow run finishes.',
        icon: ListChecks,
    },
    {
        prefKey: 'invite_banner_disabled',
        label: 'Collaboration invite banner',
        description: 'The nudge to share a live invite link for the workflow.',
        icon: UserPlus,
    },
    {
        prefKey: 'quickpublish_banner_disabled',
        label: 'Publish banner',
        description: 'The nudge to publish your interface to the web.',
        icon: Globe,
    },
];

// One row owns one useSeenOncePref hook (keeps the hook call out of a loop).
function PopupToggleRow({ prefKey, label, description, icon: Icon }: PopupToggle) {
    const [disabled, setDisabled] = useSeenOncePref(prefKey);
    return (
        <div className="flex items-center gap-3.5 px-4 py-3.5">
            <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-foreground/[0.06]">
                <Icon className="h-4 w-4 stroke-[1.5] text-foreground/60" />
            </div>
            <div className="min-w-0 flex-1">
                <p className="text-[0.9375rem] font-medium leading-tight text-foreground">{label}</p>
                <p className="mt-0.5 truncate text-xs text-foreground/40">{description}</p>
            </div>
            <Switch checked={!disabled} onCheckedChange={(checked) => setDisabled(!checked)} />
        </div>
    );
}

export function PopupPreferencesSettings() {
    return (
        <div className="max-w-2xl">
            <div className="mb-6">
                <h2 className="text-lg font-semibold text-foreground">Popups</h2>
                <p className="mt-1 text-sm text-foreground/40">
                    Choose which in-app popups and banners appear. Turn one back on after dismissing it.
                </p>
            </div>

            <div className={cn(
                'overflow-hidden rounded-xl border border-border dark:border-foreground/[0.06] bg-card dark:bg-foreground/[0.03] divide-y divide-foreground/[0.06]',
            )}>
                {POPUPS.map(p => <PopupToggleRow key={p.prefKey} {...p} />)}
            </div>
        </div>
    );
}
