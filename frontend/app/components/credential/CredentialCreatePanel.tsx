// The form a typed-in credential is connected with, everywhere one is (the connect dialog, the node panel, the public
// provide page, the builder bridge): the values it needs, the optional ones folded under "More options", and one
// full-width button that is never greyed out (pressed early, it says under each empty field what's missing) and names
// who is checking the value while it waits. A provider's refusal reads as the provider's own words, under who refused.
// Persistence is a pluggable onSave (authed credential:create, the token-scoped /provide endpoint, an edit's
// credential:update), so the form can't drift per surface.
import { useId, useRef, useState, type FormEvent } from 'react';
import { ChevronDown, Loader2 } from 'lucide-react';
import { CredentialFieldInput, type CredentialField } from './CredentialFieldInput';
import { FinalStepRow } from './connect/steps';
import { BUTTON_PRIMARY } from '~/components/shell/buttons';
import { FIELD, FIELD_LABEL } from '~/components/shell/fields';
import { missingFieldMessage } from '~/utils/credentialCopy';
import { cn } from '~/lib/utils';

/** The inline forms the agent node's panel draws for itself (an agent's API key, its variables, an MCP server): a
 *  header row with its ×, the fields, then Cancel and the primary action as pills. */
export const CREATE_FORM = {
  root: 'space-y-3',
  header: 'flex items-center justify-between',
  title: 'text-[13.5px] font-medium text-foreground',
  close: 'grid h-6 w-6 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-accent hover:text-foreground',
  note: 'text-[12px] leading-relaxed text-muted-foreground',
  // pre-line: a rejection separates our guidance from the provider's verbatim detail with a blank line.
  error: 'text-xs text-red-600 dark:text-red-400 whitespace-pre-line break-words',
  hint: 'text-[11.5px] leading-relaxed text-foreground/70',
  actions: 'flex gap-2 pt-1',
  cancel: 'inline-flex h-8 flex-1 items-center justify-center rounded-full border border-border px-3 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground',
  save: 'inline-flex h-8 flex-1 items-center justify-center gap-1.5 rounded-full bg-primary px-3 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40',
  // In flight the button keeps its active look plus a spinner: dimmed, it read as
  // an empty pill while the provider checks the credential (which takes seconds).
  saving: 'cursor-wait disabled:cursor-wait disabled:opacity-100',
} as const;

/** A refused save, as the backend's connect seam reports it: the sentence for
 *  the panel, the per-field verdicts for the inputs they name, and what a
 *  provider refusal usually means. A bare string is the legacy one-line form. */
export interface CredentialSaveFailure {
  error: string;
  fieldErrors?: Record<string, string> | null;
  hint?: string | null;
  /** The provider itself refused the value (the reply's `reachable: false`). */
  rejected?: boolean;
}
export type CredentialSaveResult = string | null | CredentialSaveFailure;

export function toSaveFailure(result: CredentialSaveResult): CredentialSaveFailure | null {
  if (!result) return null;
  return typeof result === 'string' ? { error: result } : result;
}

/** The value turned down: a reply that says the provider refused it, says what to change, or names a field. Anything
 *  else (a timeout, a failure of ours) is a plain error line, never put in the provider's mouth. */
function isRejection(result: CredentialSaveResult): boolean {
  if (!result || typeof result !== 'object') return false;
  return !!result.rejected || !!result.hint || Object.keys(result.fieldErrors ?? {}).length > 0;
}

export function CredentialCreatePanel({
  fields,
  onSave,
  onCancel,
  saveLabel = 'Connect',
  app,
  showSources = true,
  instructions,
  name: initialName,
  note,
  initialFailure,
  initialValues,
}: {
  fields: CredentialField[];
  /** Persist (name, data). Resolve a failure to display, null on success. */
  onSave: (name: string, data: Record<string, string>) => Promise<CredentialSaveResult>;
  /** A way out, for a form that opens in place of something (an edit). */
  onCancel?: () => void;
  saveLabel?: string;
  /** The app the values belong to, named while it checks them. */
  app?: string;
  /** Show where each value comes from on its label's row. */
  showSources?: boolean;
  /** The steps to get the values (shown above the form by the connect dialog), so each field's help doesn't repeat
   *  them. */
  instructions?: string | null;
  /** The name to edit, for a form that changes a saved credential. A new one is never asked for a name: an account is
   *  told apart by who it is, and renamed from its own page. */
  name?: string;
  /** One line above the fields ("Enter every value again"). */
  note?: string;
  /** A refusal and values to open on, for the design lab's states. */
  initialFailure?: CredentialSaveResult;
  initialValues?: Record<string, string>;
}) {
  const nameId = useId();
  const [name, setName] = useState(initialName ?? '');
  const [formData, setFormData] = useState<Record<string, string>>(initialValues ?? {});
  const [failure, setFailure] = useState<CredentialSaveFailure | null>(() => toSaveFailure(initialFailure ?? null));
  const [rejected, setRejected] = useState(() => isRejection(initialFailure ?? null));
  const [saving, setSaving] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const required = fields.filter((f) => f.required);
  const optional = fields.filter((f) => !f.required);
  // Optional settings stay folded unless there is nothing else, or one already holds something.
  const [more, setMore] = useState(() => !required.length || optional.some((f) => initialValues?.[f.name] || toSaveFailure(initialFailure ?? null)?.fieldErrors?.[f.name]));

  const updateField = (fieldName: string, value: string) => {
    setFormData((prev) => ({ ...prev, [fieldName]: value }));
    // Editing the field the server named clears that verdict; the rest stand,
    // and the banner never resurrects a sentence whose field was just fixed.
    setFailure((prev) => {
      const cleared = prev?.fieldErrors?.[fieldName];
      if (!prev || !cleared) return prev;
      const rest = { ...prev.fieldErrors };
      delete rest[fieldName];
      const error = prev.error === cleared ? (Object.values(rest)[0] ?? '') : prev.error;
      // With nothing else wrong, the hint went with the field it was about.
      return Object.keys(rest).length || error ? { ...prev, fieldErrors: rest, error } : null;
    });
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    // A dialog portals its content, but React still bubbles a submit to any form around it.
    e.stopPropagation();
    if (saving) return;
    const missing = required.filter((f) => !formData[f.name]?.trim());
    if (missing.length) {
      setFailure({ error: '', fieldErrors: Object.fromEntries(missing.map((f) => [f.name, missingFieldMessage(f)])) });
      formRef.current?.querySelector<HTMLElement>(`[data-field="${missing[0].name}"] input, [data-field="${missing[0].name}"] select`)?.focus();
      return;
    }
    setSaving(true);
    setFailure(null);
    try {
      const result = await onSave(name, formData);
      setFailure(toSaveFailure(result));
      setRejected(isRejection(result));
    } finally {
      setSaving(false);
    }
  };

  const fieldErrors = failure?.fieldErrors ?? {};
  // The banner repeats a field's sentence only when no input can carry it.
  const bannerError = failure?.error && !Object.values(fieldErrors).includes(failure.error) ? failure.error : null;

  const field = (f: CredentialField) => (
    <CredentialFieldInput
      key={f.name}
      app={app}
      showSource={showSources}
      context={instructions}
      field={f}
      value={formData[f.name] || ''}
      onChange={(v) => updateField(f.name, v)}
      error={fieldErrors[f.name]}
    />
  );

  return (
    <form ref={formRef} onSubmit={(e) => void submit(e)} noValidate className="space-y-4" data-testid="credential-form">
      {note && <p className="text-[13px] leading-relaxed text-muted-foreground">{note}</p>}
      {initialName !== undefined && (
        <div>
          <label htmlFor={nameId} className={FIELD_LABEL}>
            Name
          </label>
          <input id={nameId} type="text" value={name} onChange={(e) => setName(e.target.value)} className={FIELD} autoComplete="off" />
        </div>
      )}
      {required.map(field)}
      {optional.length > 0 && required.length > 0 && (
        <button
          type="button"
          aria-expanded={more}
          onClick={() => setMore((v) => !v)}
          className="inline-flex items-center gap-1 rounded-md text-[13px] text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          More options
          <ChevronDown className={cn('h-3.5 w-3.5 transition-transform duration-200', more && 'rotate-180')} />
        </button>
      )}
      {more && optional.map(field)}

      {/* The hint stays when the provider's words sit under a field: it says what to change. */}
      {(bannerError || failure?.hint) && (
        <div role="alert" className="text-[13px] leading-relaxed">
          {bannerError &&
            (rejected ? (
              <>
                <p className="font-medium text-red-600 dark:text-red-400">{app ? `${app} didn’t accept it` : 'Not accepted'}</p>
                <p className="mt-1 whitespace-pre-line break-words font-mono text-[12px] leading-relaxed text-foreground/80">{bannerError}</p>
              </>
            ) : (
              <p className="whitespace-pre-line break-words text-red-600 dark:text-red-400">{bannerError}</p>
            ))}
          {failure?.hint && <p className={cn('text-muted-foreground', bannerError && 'mt-1')}>{failure.hint}</p>}
        </div>
      )}

      <FinalStepRow>
        <div className="flex flex-col gap-2 pt-1">
          <button type="submit" aria-busy={saving || undefined} className={cn(BUTTON_PRIMARY, 'h-10 w-full justify-center', saving && 'cursor-wait')}>
            {saving ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                {app ? `Checking with ${app}…` : 'Checking…'}
              </>
            ) : (
              saveLabel
            )}
          </button>
          {onCancel && (
            <button type="button" onClick={onCancel} className="h-9 self-center rounded-full px-4 text-[13.5px] text-muted-foreground transition-colors hover:text-foreground">
              Cancel
            </button>
          )}
        </div>
      </FinalStepRow>
    </form>
  );
}
