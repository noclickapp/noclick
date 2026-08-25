// Reusable OAuth credential form component with custom client credentials toggle.
// Detects "x-oauth-supports-custom-client" flag and shows optional custom fields when enabled.
// Can be used for any OAuth provider (Twitter, Reddit, GitHub, etc.) that supports custom OAuth apps.

import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { SecretInput } from './SecretInput';
import { FieldRequirementBadge, isFieldFilled } from './FieldRequirementBadge';

interface OAuthCredentialFormProps {
    schema: any;
    formData: Record<string, string>;
    onFormDataChange: (field: string, value: string) => void;
    credentialName: string;
    onCredentialNameChange: (name: string) => void;
    label: string;
}

export const OAuthCredentialForm = ({
    schema,
    formData,
    onFormDataChange,
    credentialName,
    onCredentialNameChange,
    label,
}: OAuthCredentialFormProps) => {
    const [showCustomFields, setShowCustomFields] = useState(false);

    // Check if this OAuth credential supports custom client credentials
    const supportsCustomClient = schema?.['x-oauth-supports-custom-client'] === true;
    const customClientHelp = schema?.['x-oauth-custom-client-help'];

    // Get all fields from schema
    const required = schema?.required || [];
    const properties = schema?.properties || {};

    // Separate standard OAuth fields from custom client credential fields
    const standardFields: any[] = [];
    const customClientFields: any[] = [];

    Object.entries(properties).forEach(([name, prop]: [string, any]) => {
        if (prop['ui:hidden']) return;
        const fieldInfo = {
            name,
            label: prop.title || name,
            type: prop['ui:widget'] === 'password' ? 'password' : 'text',
            placeholder: prop.placeholder,
            description: prop.description,
            required: required.includes(name),
            isOptionalCustom: prop['x-optional-custom'] === true,
        };

        if (fieldInfo.isOptionalCustom) {
            customClientFields.push(fieldInfo);
        } else {
            standardFields.push(fieldInfo);
        }
    });

    const renderField = (field: any) => (
        <div key={field.name} className="space-y-1.5">
            <label className="flex items-center gap-2 text-xs text-muted-foreground dark:text-zinc-500">
                {field.label}
                <FieldRequirementBadge
                    isRequired={field.required && (!field.isOptionalCustom || showCustomFields)}
                    isFilled={isFieldFilled(formData[field.name])}
                />
            </label>
            {field.description && (
                <p className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 -mt-1 mb-1">{field.description}</p>
            )}
            {field.type === 'password' ? (
                <SecretInput
                    value={formData[field.name] || ''}
                    onChange={(e) => onFormDataChange(field.name, e.target.value)}
                    placeholder={field.placeholder}
                    required={field.required && (!field.isOptionalCustom || showCustomFields)}
                    inputClassName="w-full px-3 py-2 text-sm bg-card border border-input rounded-md text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-ring/30 transition-colors font-mono"
                />
            ) : (
                <input
                    type={field.type}
                    value={formData[field.name] || ''}
                    onChange={(e) => onFormDataChange(field.name, e.target.value)}
                    placeholder={field.placeholder}
                    required={field.required && (!field.isOptionalCustom || showCustomFields)}
                    className="w-full px-3 py-2 text-sm bg-card border border-input rounded-md text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-ring/30 transition-colors font-mono"
                />
            )}
        </div>
    );

    return (
        <div className="space-y-3">
            {/* Credential Name */}
            <div className="space-y-1.5">
                <label className="flex items-center gap-2 text-xs text-muted-foreground dark:text-zinc-500">
                    Name
                    <FieldRequirementBadge isRequired={false} />
                </label>
                <input
                    type="text"
                    value={credentialName}
                    onChange={(e) => onCredentialNameChange(e.target.value)}
                    placeholder={`My ${label}`}
                    className="w-full px-3 py-2 text-sm bg-card border border-input rounded-md text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-ring/30 transition-colors"
                />
            </div>

            {/* Standard OAuth Fields (access_token, refresh_token, etc.) */}
            {standardFields.map(renderField)}

            {/* Custom Client Credentials Toggle */}
            {supportsCustomClient && customClientFields.length > 0 && (
                <div className="pt-2 border-t border-border">
                    <button
                        type="button"
                        onClick={() => setShowCustomFields(!showCustomFields)}
                        className="w-full flex items-center justify-between px-3 py-2 text-xs text-muted-foreground hover:text-foreground/80 bg-muted/50 dark:bg-zinc-900/50 hover:bg-accent dark:hover:bg-zinc-900 border border-border hover:border-muted-foreground/40 dark:hover:border-zinc-700 rounded-lg transition-all"
                    >
                        <span className="flex items-center gap-2">
                            {showCustomFields ? (
                                <ChevronDown className="h-3.5 w-3.5" />
                            ) : (
                                <ChevronRight className="h-3.5 w-3.5" />
                            )}
                            Use my own OAuth app credentials
                        </span>
                        <span className="text-[10px] text-muted-foreground/70 dark:text-zinc-600">
                            {showCustomFields ? 'Hide' : 'Show'} custom credentials
                        </span>
                    </button>

                    {/* Custom Client Credential Fields (shown when toggle is on) */}
                    {showCustomFields && (
                        <div className="mt-3 space-y-3 p-3 bg-muted/50 dark:bg-zinc-900/30 rounded-lg border border-border/50 dark:border-zinc-800/50">
                            <div className="text-[10px] text-muted-foreground dark:text-zinc-500 leading-relaxed space-y-2">
                                <p>
                                    By default, NoClick's OAuth app is used for authentication. If you have your own OAuth app with premium features or custom rate limits, enter your credentials below.
                                </p>
                                {customClientHelp && (
                                    <p className="text-amber-600 dark:text-amber-400/80 bg-amber-500/10 border border-amber-500/20 rounded px-2 py-1.5">
                                        ⚠️ {customClientHelp}
                                    </p>
                                )}
                            </div>
                            {customClientFields.map(renderField)}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};
