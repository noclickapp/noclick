// The one layout for "this instance needs something from its operator" asks —
// an OAuth app, a service key — so the credential panel, the builder, the
// <ask> drawer and Settings → Self-hosted all set them up the same way: what to
// do, in two or three steps, then the form. No box: it sits in whatever panel
// asked, in the shell's field and button language.
import type { ReactNode } from 'react';
import { BUTTON_PRIMARY, BUTTON_SECONDARY } from '~/components/shell/buttons';
import { FIELD, FIELD_LABEL } from '~/components/shell/fields';

export const INSTANCE_FORM = {
    card: 'space-y-4',
    title: 'text-[14.5px] font-medium text-foreground',
    steps: 'mt-1.5 list-decimal space-y-0.5 pl-4 text-[13px] leading-relaxed text-muted-foreground',
    // The way in (the provider's console, where the key or app gets made).
    chip: BUTTON_SECONDARY,
    label: FIELD_LABEL,
    // Keys, IDs and hosts read in mono; the hint in their placeholder doesn't.
    input: `${FIELD} font-mono placeholder:font-sans`,
    primaryButton: BUTTON_PRIMARY,
    cancelButton: 'inline-flex h-9 items-center rounded-full px-3 text-[13.5px] text-muted-foreground transition-colors hover:text-foreground',
    note: 'ml-auto text-xs text-muted-foreground',
} as const;

export function InstanceSetupCard({
    title,
    steps,
    children,
}: {
    title: string;
    steps: string[];
    children: ReactNode;
}) {
    return (
        <div className={INSTANCE_FORM.card}>
            <div>
                <div className={INSTANCE_FORM.title}>{title}</div>
                <ol className={INSTANCE_FORM.steps}>
                    {steps.map((step) => (
                        <li key={step}>{step}</li>
                    ))}
                </ol>
            </div>
            {children}
        </div>
    );
}
