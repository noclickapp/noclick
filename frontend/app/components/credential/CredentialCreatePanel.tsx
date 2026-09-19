// The app's "New Credential" creation panel — extracted verbatim from
// NodeCredentials so every surface that creates a credential by form (the
// node config panel, the builder input drawer via NodeCredentials, the public
// credential-provide page, and the builder input bridge) renders the SAME
// panel. Persistence is a pluggable onSave (authed credential:create vs the
// token-scoped /provide endpoint), so the UX cannot drift per surface.
import { useState } from 'react';
import { Check, Loader2, X } from 'lucide-react';
import { CredentialFieldInput, type CredentialField } from './CredentialFieldInput';
import { FieldRequirementBadge } from '~/components/workflow/FieldRequirementBadge';
import { OAuthCredentialForm } from '~/components/workflow/OAuthCredentialForm';

/** A refused save, as the backend's connect seam reports it: the sentence for
 *  the panel, the per-field verdicts for the inputs they name, and what a
 *  provider refusal usually means. A bare string is the legacy one-line form. */
export interface CredentialSaveFailure {
  error: string;
  fieldErrors?: Record<string, string> | null;
  hint?: string | null;
}
export type CredentialSaveResult = string | null | CredentialSaveFailure;

export function toSaveFailure(result: CredentialSaveResult): CredentialSaveFailure | null {
  if (!result) return null;
  return typeof result === 'string' ? { error: result } : result;
}

export function CredentialCreatePanel({
  label,
  schema,
  fields,
  onSave,
  onCancel,
  saveLabel = 'Create',
  hideName = false,
  instructions,
}: {
  /** Requirement label, e.g. "Google Sheets Account" — used in placeholders. */
  label: string;
  /** Credential schema for the custom-client OAuth path (authed surfaces). */
  schema?: Record<string, unknown>;
  fields: CredentialField[];
  /** Persist (name, data). Resolve a failure to display, null on success. */
  onSave: (name: string, data: Record<string, string>) => Promise<CredentialSaveResult>;
  /** Renders the X / Cancel affordances; omit for always-open surfaces. */
  onCancel?: () => void;
  saveLabel?: string;
  /** Anonymous surfaces can't name the owner's credential — hide the field. */
  hideName?: boolean;
  /** Where the values come from, in steps (the schema's x-credential-instructions). */
  instructions?: string | null;
}) {
  const [name, setName] = useState('');
  const [formData, setFormData] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState<CredentialSaveFailure | null>(null);
  const [saving, setSaving] = useState(false);

  const updateField = (fieldName: string, value: string) => {
    setFormData(prev => ({ ...prev, [fieldName]: value }));
    // Editing the field the server named clears that verdict; the rest stand,
    // and the banner never resurrects a sentence whose field was just fixed.
    setFailure(prev => {
      const cleared = prev?.fieldErrors?.[fieldName];
      if (!prev || !cleared) return prev;
      const rest = { ...prev.fieldErrors };
      delete rest[fieldName];
      const error = prev.error === cleared ? Object.values(rest)[0] ?? '' : prev.error;
      return Object.keys(rest).length || error || prev.hint ? { ...prev, fieldErrors: rest, error } : null;
    });
  };

  const save = async () => {
    setSaving(true);
    setFailure(null);
    try {
      setFailure(toSaveFailure(await onSave(name, formData)));
    } finally {
      setSaving(false);
    }
  };

  const fieldErrors = failure?.fieldErrors ?? {};
  // The banner repeats a field's sentence only when no input can carry it.
  const bannerError = failure?.error && !Object.values(fieldErrors).includes(failure.error) ? failure.error : null;

  const missingRequired = fields.filter(f => f.required).some(f => !formData[f.name]);

  return (
    <div className="p-4 rounded-lg bg-muted/50 dark:bg-zinc-900/50 border border-border space-y-3 max-w-md">
      <div className="flex items-center justify-between mb-2">
        <div className="text-[11px] text-muted-foreground uppercase tracking-wider">
          New Credential
        </div>
        {onCancel && (
          <button
            onClick={onCancel}
            className="p-1 hover:bg-accent rounded transition-colors"
          >
            <X className="h-3 w-3 text-muted-foreground dark:text-zinc-500" />
          </button>
        )}
      </div>

      {/* Use custom OAuth form for credentials that support custom client */}
      {schema?.['x-oauth-supports-custom-client'] ? (
        <OAuthCredentialForm
          schema={schema}
          formData={formData}
          onFormDataChange={updateField}
          credentialName={name}
          onCredentialNameChange={setName}
          label={label}
        />
      ) : (
        <>
          {!hideName && (
            <div className="space-y-1.5">
              <label className="flex items-center gap-2 text-xs text-muted-foreground dark:text-zinc-500">
                Name
                <FieldRequirementBadge isRequired={false} />
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={`My ${label}`}
                className="w-full px-3 py-2 text-sm bg-card border border-input rounded-md text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-foreground/20 transition-colors"
              />
            </div>
          )}

          {instructions && (
            <p
              data-testid="credential-instructions"
              className="text-[11.5px] leading-relaxed text-muted-foreground dark:text-zinc-400 border-l-2 border-foreground/15 pl-2.5"
            >
              {instructions}
            </p>
          )}

          {/* Credential Fields - Dynamically rendered from schema */}
          {fields.map((field) => (
            <CredentialFieldInput
              key={field.name}
              field={field}
              value={formData[field.name] || ''}
              onChange={(v) => updateField(field.name, v)}
              error={fieldErrors[field.name]}
            />
          ))}
        </>
      )}

      {/* Refusal: the provider's words (or ours), then what they usually mean. */}
      {failure && (bannerError || failure.hint) && (
        <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 space-y-1" role="alert">
          {bannerError && <div className="text-xs text-red-600 dark:text-red-400 break-words">{bannerError}</div>}
          {failure.hint && <div className="text-[11.5px] leading-relaxed text-foreground/70">{failure.hint}</div>}
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-2 pt-1">
        {onCancel && (
          <button
            onClick={onCancel}
            className="flex-1 px-3 py-2 text-xs text-muted-foreground hover:text-foreground/80 bg-card hover:bg-accent border border-border rounded-lg transition-all"
          >
            Cancel
          </button>
        )}
        <button
          onClick={() => void save()}
          disabled={saving || missingRequired}
          className={
            saving
              // In-flight keeps the ACTIVE palette + a spinner — the disabled
              // palette's dim text read as an empty gray pill while the
              // backend validates the credential with the provider (which can
              // take seconds).
              ? 'flex-1 px-3 py-2 text-xs text-primary-foreground dark:text-foreground bg-primary dark:bg-zinc-700 cursor-wait border border-transparent dark:border-zinc-700 rounded-lg transition-all flex items-center justify-center gap-1.5'
              : 'flex-1 px-3 py-2 text-xs text-primary-foreground dark:text-foreground bg-primary dark:bg-zinc-700 hover:bg-primary/90 dark:hover:bg-zinc-600 disabled:bg-muted disabled:text-muted-foreground/70 dark:disabled:text-zinc-600 disabled:cursor-not-allowed border border-transparent dark:border-zinc-700 disabled:border-border rounded-lg transition-all flex items-center justify-center gap-1.5'
          }
        >
          {saving ? (
            <>
              <Loader2 className="h-3 w-3 animate-spin" />
              Validating…
            </>
          ) : (
            <>
              <Check className="h-3 w-3" />
              {saveLabel}
            </>
          )}
        </button>
      </div>
    </div>
  );
}
