// Shared renderer for a single credential input field — a select for enum fields,
// a masked SecretInput for passwords, a plain input otherwise, with the label and
// required/optional marker. Used by BOTH the in-app credential UI (NodeCredentials)
// and the public credential-provide page so the field rendering can't diverge
// between them. Styling is a prop (inputClassName) so each surface keeps its look
// while sharing the logic.

import { SecretInput } from '~/components/workflow/SecretInput';
import { FieldRequirementBadge, isFieldFilled } from '~/components/workflow/FieldRequirementBadge';

export interface CredentialField {
    name: string;
    label: string;
    type: string;
    placeholder?: string;
    required: boolean;
    description?: string;
    default?: string;
    options?: Array<{ value: string; label: string }>;
}

export const CRED_INPUT_CLASS =
    'w-full px-3 py-2 text-sm bg-card border border-input rounded-md text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-foreground/20 transition-colors';

interface CredentialFieldInputProps {
    field: CredentialField;
    value: string;
    onChange: (value: string) => void;
    /** Input styling; defaults to the compact in-app style. */
    inputClassName?: string;
}

export function CredentialFieldInput({
    field,
    value,
    onChange,
    inputClassName = CRED_INPUT_CLASS,
}: CredentialFieldInputProps) {
    // Selects fall back to field.default when untouched, so judge filledness on
    // what the control actually shows.
    const effectiveValue = field.options ? value || field.default || '' : value;
    return (
        <div className="space-y-1.5">
            <label className="flex items-center gap-2 text-xs text-muted-foreground/70 dark:text-zinc-500">
                {field.label}
                <FieldRequirementBadge isRequired={field.required} isFilled={isFieldFilled(effectiveValue)} />
            </label>
            {field.options ? (
                <select
                    value={value || field.default || ''}
                    onChange={(e) => onChange(e.target.value)}
                    className={inputClassName}
                >
                    {field.options.map((o) => (
                        <option key={o.value} value={o.value}>
                            {o.label}
                        </option>
                    ))}
                </select>
            ) : field.type === 'password' ? (
                <SecretInput
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    placeholder={field.placeholder}
                    required={field.required}
                    inputClassName={`${inputClassName} font-mono`}
                />
            ) : (
                <input
                    type={field.type}
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    placeholder={field.placeholder}
                    required={field.required}
                    className={`${inputClassName} font-mono`}
                />
            )}
            {field.description && (
                <p className="text-[11px] leading-relaxed text-muted-foreground/70 dark:text-zinc-500">
                    {field.description}
                </p>
            )}
        </div>
    );
}
