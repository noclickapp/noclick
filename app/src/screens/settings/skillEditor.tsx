// A builder skill's words, edited in place of Settings → Skills' list: its name, when the builder should use it, and
// what it tells the builder, read with GET /v1/builder_skills/{id} and saved with PATCH. The standard of the skill
// editor slot; a host with a workflow canvas fills it with an editor that also draws the skill's workflow. One shared
// with the account reads only.
import { useEffect, useState } from 'react';
import { ArrowLeft } from 'lucide-react';
import { BuilderSkill } from 'noclick';
import { useClient } from '@/sdk/client';
import { BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { FIELD, FIELD_LABEL } from '@/ui/fields';
import { cn } from '@/ui/utils';
import { SettingsHeader } from './parts';
import type { SkillEditorProps } from './skills';

export function SkillWordsEditor({ skillId, scope, onClose, onChanged }: SkillEditorProps) {
    const client = useClient();
    const [skill, setSkill] = useState<BuilderSkill | null>(null);
    const [draft, setDraft] = useState({ name: '', description: '', bodyText: '' });
    const [state, setState] = useState<'idle' | 'saving' | 'saved'>('idle');
    const [error, setError] = useState<string | null>(null);
    const readOnly = scope === 'shared';

    useEffect(() => {
        let live = true;
        BuilderSkill.get(skillId, { client }).then(
            (read) => {
                if (!live) return;
                setSkill(read);
                setDraft({ name: read.name, description: read.description, bodyText: read.bodyText ?? '' });
            },
            (failure: unknown) => live && setError(failure instanceof Error ? failure.message : String(failure))
        );
        return () => {
            live = false;
        };
    }, [client, skillId]);

    const save = async () => {
        if (!skill) return;
        setState('saving');
        try {
            setSkill(await skill.update({ name: draft.name.trim(), description: draft.description, bodyText: draft.bodyText }, { client }));
            setState('saved');
            onChanged();
        } catch (failure) {
            setError(failure instanceof Error ? failure.message : String(failure));
            setState('idle');
        }
    };

    const changed = !!skill && (draft.name !== skill.name || draft.description !== skill.description || draft.bodyText !== (skill.bodyText ?? ''));
    return (
        <div>
            <button type="button" onClick={onClose} className="mb-4 inline-flex items-center gap-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground">
                <ArrowLeft className="h-3.5 w-3.5" />
                Skills
            </button>
            <SettingsHeader title={skill?.name || 'Skill'} description={readOnly ? 'Shared with you to read.' : 'What the builder reads to decide whether to use it, and what it tells it.'} />
            {error && <p role="alert" className="mb-4 text-[13px] text-red-600 dark:text-red-400">{error}</p>}
            <div className={cn('space-y-5', !skill && 'opacity-60')}>
                <div>
                    <label htmlFor="skill-name" className={FIELD_LABEL}>
                        Name
                    </label>
                    <input id="skill-name" value={draft.name} disabled={!skill || readOnly} onChange={(e) => setDraft({ ...draft, name: e.target.value })} className={FIELD} />
                </div>
                <div>
                    <label htmlFor="skill-description" className={FIELD_LABEL}>
                        When to use it
                    </label>
                    <input
                        id="skill-description"
                        value={draft.description}
                        disabled={!skill || readOnly}
                        onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                        className={FIELD}
                    />
                </div>
                <div>
                    <label htmlFor="skill-text" className={FIELD_LABEL}>
                        What it says
                    </label>
                    <textarea
                        id="skill-text"
                        rows={12}
                        value={draft.bodyText}
                        disabled={!skill || readOnly}
                        onChange={(e) => setDraft({ ...draft, bodyText: e.target.value })}
                        className={cn(FIELD, 'h-auto py-2.5 font-mono text-[13px]')}
                    />
                </div>
                {skill?.hasWorkflow && <p className="text-[13px] text-muted-foreground">It also carries a workflow, which this editor leaves as it is.</p>}
            </div>
            {!readOnly && (
                <div className="mt-6 flex items-center gap-2">
                    <button type="button" onClick={() => void save()} disabled={!changed || !draft.name.trim() || state === 'saving'} className={BUTTON_PRIMARY}>
                        {state === 'saving' ? 'Saving…' : 'Save'}
                    </button>
                    <button type="button" onClick={onClose} className={BUTTON_SECONDARY}>
                        Done
                    </button>
                    {state === 'saved' && !changed && <span className="text-[13px] text-muted-foreground">Saved</span>}
                </div>
            )}
        </div>
    );
}
