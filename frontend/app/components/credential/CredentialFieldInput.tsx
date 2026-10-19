// One credential field, as every surface that asks for one draws it (the connect dialog, the node panel, the public
// provide page): the shell's field (`shell/fields.ts`) under a sentence-case label, with no badge (only an optional
// field says so), where the value comes from as a quiet link on the label's row, the server's verdict under the input,
// and help read from the schema without what restates the label, the placeholder or the steps above it.

import { useId } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { SecretInput } from '~/components/workflow/SecretInput';
import { FIELD, FIELD_LABEL, QUIET_LINK } from '~/components/shell/fields';
import { fieldHelp, fieldLabel, sourceLink } from '~/utils/credentialCopy';
import { cn } from '~/lib/utils';

export interface CredentialField {
    name: string;
    label: string;
    type: string;
    placeholder?: string;
    required: boolean;
    description?: string;
    /** Where this one value comes from, when the schema names it. */
    helpUrl?: string | null;
    default?: string;
    options?: Array<{ value: string; label: string }>;
}

interface CredentialFieldInputProps {
    field: CredentialField;
    value: string;
    onChange: (value: string) => void;
    /** The server's per-field verdict on the last save ("looks like a web address"), shown under the input it names. */
    error?: string | null;
    /** The app the value comes from, so its help can drop what only names the app. */
    app?: string;
    /** Show where this value comes from on the label's row. */
    showSource?: boolean;
    /** What the form already says above the field (its steps), so the field's help doesn't say it again. */
    context?: string | null;
}

// The secret's own value is code-like, so it sets in mono; what you type to find it (a placeholder) stays in the sans.
const SECRET = 'font-mono placeholder:font-sans';

export function CredentialFieldInput({ field, value, onChange, error, app = '', showSource = true, context }: CredentialFieldInputProps) {
    const id = useId();
    const help = fieldHelp(field, app, context);
    // The server names the field by its schema title ("App Password looks like…"); under its own label it is "This".
    const verdict = error?.replace(new RegExp(`^${field.label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i'), 'This');
    const source = showSource && field.helpUrl ? sourceLink({ kind: 'api_key', label: field.label, credentialUrl: field.helpUrl }) : null;
    const described = [error && `${id}-error`, help && `${id}-help`].filter(Boolean).join(' ') || undefined;
    const control = {
        id,
        'aria-invalid': error ? true : undefined,
        'aria-describedby': described,
        className: cn(FIELD, error && 'border-red-500/60 focus:border-red-500 dark:border-red-400/50 dark:focus:border-red-400'),
    };
    return (
        <div data-field={field.name}>
            <div className="flex items-baseline justify-between gap-3">
                <label htmlFor={id} className={FIELD_LABEL}>
                    {fieldLabel(field)}
                    {!field.required && <span className="font-normal text-muted-foreground"> (optional)</span>}
                </label>
                {source && (
                    <a href={source.href} target="_blank" rel="noopener noreferrer" className={cn(QUIET_LINK, 'mb-1.5 shrink-0 text-[12.5px]')}>
                        {source.host}
                        <ArrowUpRight className="h-3 w-3" />
                    </a>
                )}
            </div>
            {field.options ? (
                <select {...control} value={value || field.default || ''} onChange={(e) => onChange(e.target.value)}>
                    {field.options.map((o) => (
                        <option key={o.value} value={o.value}>
                            {o.label}
                        </option>
                    ))}
                </select>
            ) : field.type === 'password' ? (
                <SecretInput
                    {...control}
                    className={undefined}
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    placeholder={field.placeholder}
                    autoComplete="off"
                    spellCheck={false}
                    inputClassName={cn(control.className, SECRET)}
                />
            ) : (
                <input {...control} type="text" value={value} onChange={(e) => onChange(e.target.value)} placeholder={field.placeholder} autoComplete="off" spellCheck={false} />
            )}
            {error && (
                <p id={`${id}-error`} className="mt-1.5 text-[12.5px] leading-snug text-red-600 dark:text-red-400" role="alert">
                    {verdict}
                </p>
            )}
            {help && (
                <p id={`${id}-help`} className="mt-1.5 text-[12.5px] leading-snug text-muted-foreground">
                    {help}
                </p>
            )}
        </div>
    );
}
