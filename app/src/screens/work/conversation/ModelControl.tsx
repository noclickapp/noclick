// The box's model control: Work's shared harness and model picker (newAgent/ModelPicker) over this session's
// settings. A model on another harness moves the agent there (agents/harnessSwitch: the account it runs on is picked,
// chosen in place or connected first); the model, effort, speed, account and permissions are written back with the
// session's PATCH (only what changed: model and effort change the agent itself).
import { useEffect, useState } from 'react';
import type { Agent, ConversationSettings, HarnessName } from 'noclick';
import { useHarnessSwitch } from '../agents/harnessSwitch';
import { useModelAccounts } from '../newAgent/catalog';
import { HarnessModelPicker, type PickerValue } from '../newAgent/ModelPicker';

export type SettingsPatch = Partial<{ model: string | null; effort: string | null; speed: 'standard' | 'fast' | null; modelConnection: string | null; permissionMode: ConversationSettings['permissionMode'] }>;

/** What a pick changed, as the conversation's PATCH takes it. */
export function patchOf(before: PickerValue, after: PickerValue): SettingsPatch {
    const patch: SettingsPatch = {};
    if (after.model !== before.model) patch.model = after.model;
    if (after.effort !== before.effort) patch.effort = after.effort;
    if (after.speed !== before.speed) patch.speed = after.speed as SettingsPatch['speed'];
    if ((after.account ?? null) !== (before.account ?? null)) patch.modelConnection = after.account ?? null;
    if (after.permissions !== before.permissions) patch.permissionMode = after.permissions;
    return patch;
}

export function ModelControl({
    agent,
    harness,
    model,
    settings,
    open,
    onOpenChange,
    onChange,
    onMoved,
    fundsOwner,
}: {
    /** The agent the conversation is with; null until it's read. */
    agent: Agent | null;
    harness: HarnessName | null;
    model: string | null;
    settings: ConversationSettings | null;
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onChange: (patch: SettingsPatch) => void;
    /** After the agent moved to another harness: its settings are read again. */
    onMoved: () => void;
    fundsOwner?: string;
}) {
    const { accounts } = useModelAccounts();
    // A move shows at once, until the conversation's settings read it or it's refused.
    const [shown, setShown] = useState<PickerValue | null>(null);
    const moves = useHarnessSwitch(agent, { onMoved, onRefused: () => setShown(null) });
    useEffect(() => {
        if (shown && settings?.harness === shown.harness) setShown(null);
    }, [settings?.harness, shown]);
    const on = settings?.harness ?? harness;
    if (!on) return null;
    const value: PickerValue = shown ?? {
        harness: on,
        model: settings?.model ?? model ?? '',
        effort: settings?.effort ?? null,
        speed: settings?.speeds.length ? settings.speed : null,
        permissions: settings?.permissionMode ?? 'full-access',
        account: settings?.modelConnection ?? null,
    };
    const choosing = moves.choosing;
    const choice = choosing && {
        harness: choosing.harness,
        accounts: choosing.accounts,
        onPick: (account: string) => {
            setShown({ ...value, harness: choosing.harness.name, model: choosing.move.model ?? choosing.harness.defaultModel, account });
            moves.choose(account);
        },
        onCancel: moves.cancel,
    };
    return (
        <>
            <HarnessModelPicker
                value={value}
                onChange={(next) => {
                    if (next.harness !== value.harness) {
                        const step = moves.start({ harness: next.harness, model: next.model });
                        if (step === 'moving') setShown(next);
                        // The connect popup takes the screen; the move is made once what it connects lands.
                        if (step === 'connect') onOpenChange(false);
                        return;
                    }
                    const patch = patchOf(value, next);
                    if (Object.keys(patch).length) onChange(patch);
                }}
                choice={choice}
                accounts={accounts}
                permissionModes={settings?.permissionModes}
                // The session's settings say what its own model takes; a move not read back yet goes by its harness.
                efforts={shown ? undefined : settings?.efforts}
                defaultEffort={shown ? undefined : settings?.defaultEffort}
                open={open}
                onOpenChange={(o) => {
                    if (!o) moves.cancel();
                    onOpenChange(o);
                }}
                // The footer's account pill under the box names it.
                accountInPill={false}
                fundsOwner={fundsOwner}
            />
            {moves.dialog}
        </>
    );
}
