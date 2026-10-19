// What a number's country asks before it's sold, as one form: who holds it (their name and address, and a phone to
// reach them on where it asks), then each answer it takes in text (a choice where the carrier lists the answers, its
// example as the hint) and each document, uploaded once and offered again for the account's next number. One section
// per thing asked, the carrier's own description behind "What's this", sections divided by hairlines.
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { ChevronRight, FileText, Loader2, Trash2, Upload } from 'lucide-react';
import { BUTTON_SECONDARY } from '~/components/shell/buttons';
import { FIELD } from '~/components/shell/fields';
import type { NumberDocument, NumberFiling, NumberHolder, NumberRequirement, NumberType, PhoneNumberPurchase, RequirementAnswers } from '~/hooks/usePhoneNumberPurchase';
import { cn } from '~/lib/utils';
import { HolderFields, holderMissing, holderToSend, useHolder } from './HolderFields';

/** The files a document requirement takes (what the carrier accepts for one), up to its 20 MB. */
export const DOCUMENT_ACCEPT = 'application/pdf,image/png,image/jpeg';
// An example longer than this reads as a hint under the field, not a placeholder in it.
const PLACEHOLDER_MAX = 40;

const asksHolder = (items: NumberRequirement[]) => items.some((r) => r.kind === 'address' || r.kind === 'contact');
const asksPhone = (items: NumberRequirement[]) => items.some((r) => r.kind === 'contact');
const answered = (items: NumberRequirement[]) => items.filter((r) => r.kind === 'textual' || r.kind === 'document');

/** The holder and the answers a form for ``country``'s number edits, the holder's phone prefilled with the account's. */
export function useFiling(country: string, contactPhone: string | null) {
    const [holder, setHolder] = useHolder(country, contactPhone);
    const [answers, setAnswers] = useState<RequirementAnswers>({});
    const setAnswer = (id: string, value: string) => setAnswers((current) => ({ ...current, [id]: value }));
    return { holder, setHolder, answers, setAnswer };
}

export type Filing = ReturnType<typeof useFiling>;

/** What's missing before it can be sent, in words; empty when every requirement is answered. */
export function filingMissing(items: NumberRequirement[], filing: Pick<Filing, 'holder' | 'answers'>): string[] {
    const missing = asksHolder(items) ? holderMissing(filing.holder, asksPhone(items)) : [];
    for (const r of answered(items)) if (!filing.answers[r.id]?.trim()) missing.push(r.kind === 'document' ? `a file for ${r.name}` : r.name);
    return missing;
}

/** The holder and the answers, each where it's asked, as a purchase sends them. */
export function filingToSend(items: NumberRequirement[], filing: { holder: NumberHolder; answers: RequirementAnswers }): NumberFiling {
    const asked = answered(items);
    return {
        ...(asksHolder(items) ? { holder: holderToSend(filing.holder, asksPhone(items)) } : {}),
        ...(asked.length ? { answers: Object.fromEntries(asked.map((r) => [r.id, (filing.answers[r.id] ?? '').trim()])) } : {}),
    };
}

function WhatsThis({ text }: { text: string }) {
    if (!text) return null;
    return (
        <details className="group">
            <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-[12.5px] text-muted-foreground transition-colors hover:text-foreground [&::-webkit-details-marker]:hidden">
                <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90" />
                What’s this
            </summary>
            <p className="mt-1.5 max-w-xl pl-[18px] text-[12.5px] leading-relaxed text-muted-foreground">{text}</p>
        </details>
    );
}

function Asked({ title, help, children, testId }: { title: string; help?: string; children: ReactNode; testId?: string }) {
    return (
        <section className="space-y-2.5 py-5 first:pt-0 last:pb-0" data-testid={testId}>
            <div className="space-y-1">
                <h3 className="text-[14px] font-medium text-foreground">{title}</h3>
                {help !== undefined && <WhatsThis text={help} />}
            </div>
            {children}
        </section>
    );
}

function TextAnswer({ requirement, value, onChange, disabled }: { requirement: NumberRequirement; value: string; onChange: (value: string) => void; disabled?: boolean }) {
    const id = useId();
    const example = requirement.example.trim();
    const hint = example.length > PLACEHOLDER_MAX;
    return (
        <div>
            <label htmlFor={id} className="sr-only">
                {requirement.name}
            </label>
            {requirement.values.length ? (
                <select id={id} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} className={cn(FIELD, 'max-w-sm', !value && 'text-muted-foreground')}>
                    <option value="">Choose one</option>
                    {requirement.values.map((v) => (
                        <option key={v} value={v}>
                            {v}
                        </option>
                    ))}
                </select>
            ) : (
                <input
                    id={id}
                    value={value}
                    onChange={(e) => onChange(e.target.value.slice(0, 1000))}
                    placeholder={example && !hint ? `e.g. ${example}` : undefined}
                    disabled={disabled}
                    className={FIELD}
                />
            )}
            {hint && <p className="mt-1.5 text-[12.5px] leading-snug text-muted-foreground">For example: {example}</p>}
        </div>
    );
}

function uploadedOn(document: NumberDocument): string {
    return new Date(document.uploaded_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function DocumentAnswer({
    subject,
    requirement,
    value,
    onChange,
    purchase,
    disabled,
}: {
    subject: { country: string; number_type: NumberType };
    requirement: NumberRequirement;
    value: string;
    onChange: (value: string) => void;
    purchase: PhoneNumberPurchase;
    disabled?: boolean;
}) {
    const input = useRef<HTMLInputElement>(null);
    const [kept, setKept] = useState<string | null>(null);
    const mine = (purchase.documents ?? []).filter((d) => d.requirement_id === requirement.id);
    const uploading = purchase.uploading === requirement.id;
    // One uploaded for this before is offered again; the newest is chosen until the person picks another.
    useEffect(() => {
        if (!value && mine[0]) onChange(mine[0].id);
        if (value && purchase.documents && !mine.some((d) => d.id === value)) onChange(mine[0]?.id ?? '');
    }, [purchase.documents]); // eslint-disable-line react-hooks/exhaustive-deps

    const upload = async (file: File | undefined) => {
        if (!file) return;
        const uploaded = await purchase.uploadDocument(subject, requirement, file);
        if (uploaded) onChange(uploaded.id);
        if (input.current) input.current.value = '';
    };
    const remove = async (document: NumberDocument) => {
        const removed = await purchase.removeDocument(document);
        if (removed) setKept(removed.keptByCarrier ? document.filename : null);
    };
    return (
        <div className="space-y-2">
            {mine.length > 0 && (
                <div role="radiogroup" aria-label={requirement.name} className="divide-y divide-border dark:divide-foreground/[0.06]">
                    {mine.map((d) => (
                        <label key={d.id} className="flex cursor-pointer items-center gap-3 py-2 text-[13.5px]">
                            <input type="radio" name={requirement.id} checked={value === d.id} onChange={() => onChange(d.id)} disabled={disabled} className="h-4 w-4 accent-foreground" />
                            <FileText className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.75} />
                            <span className="min-w-0 flex-1 truncate text-foreground">{d.filename}</span>
                            <span className="shrink-0 text-[12.5px] text-muted-foreground">{uploadedOn(d)}</span>
                            <button
                                type="button"
                                onClick={(e) => {
                                    e.preventDefault();
                                    void remove(d);
                                }}
                                disabled={disabled}
                                aria-label={`Remove ${d.filename}`}
                                className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                            >
                                <Trash2 className="h-3.5 w-3.5" />
                            </button>
                        </label>
                    ))}
                </div>
            )}
            <input ref={input} type="file" accept={DOCUMENT_ACCEPT} className="hidden" onChange={(e) => void upload(e.target.files?.[0])} aria-label={`Upload ${requirement.name}`} />
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                <button type="button" onClick={() => input.current?.click()} disabled={disabled || uploading} className={cn(BUTTON_SECONDARY, 'h-8 px-3.5 text-[13px]')}>
                    {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
                    {mine.length ? 'Upload another' : 'Upload a file'}
                </button>
                <span className="text-[12.5px] text-muted-foreground">PDF, PNG or JPEG, up to 20 MB</span>
            </div>
            {kept && <p className="text-[12.5px] text-muted-foreground">Removed {kept}. The carrier keeps its copy on file for the number it was filed for.</p>}
        </div>
    );
}

/** Each thing ``requirements`` asks, for ``subject`` (the number, or its order), as one form. */
export function RequirementFields({
    subject,
    requirements,
    filing,
    purchase,
    disabled,
}: {
    subject: { country: string; number_type: NumberType };
    requirements: NumberRequirement[];
    filing: Filing;
    purchase: PhoneNumberPurchase;
    disabled?: boolean;
}) {
    const documents = requirements.some((r) => r.kind === 'document');
    const { loadDocuments } = purchase;
    useEffect(() => {
        if (documents) void loadDocuments();
    }, [documents, loadDocuments]);
    const holderAsked = requirements.filter((r) => r.kind === 'address' || r.kind === 'contact');
    return (
        <div className="divide-y divide-border dark:divide-foreground/[0.06]" data-testid="requirement-fields">
            {holderAsked.length > 0 && (
                <Asked title="Who holds the number" help={holderAsked.map((r) => r.description).filter(Boolean).join(' ')} testId="requirement-holder">
                    <HolderFields holder={filing.holder} onChange={filing.setHolder} askPhone={asksPhone(requirements)} disabled={disabled} />
                </Asked>
            )}
            {answered(requirements).map((r) => (
                <Asked key={r.id} title={r.name} help={r.description} testId={`requirement-${r.kind}`}>
                    {r.kind === 'textual' ? (
                        <TextAnswer requirement={r} value={filing.answers[r.id] ?? ''} onChange={(v) => filing.setAnswer(r.id, v)} disabled={disabled} />
                    ) : (
                        <DocumentAnswer
                            subject={subject}
                            requirement={r}
                            value={filing.answers[r.id] ?? ''}
                            onChange={(v) => filing.setAnswer(r.id, v)}
                            purchase={purchase}
                            disabled={disabled}
                        />
                    )}
                </Asked>
            ))}
            {documents && (
                <p className="pt-4 text-[12.5px] leading-snug text-muted-foreground">
                    Each file goes to the carrier, which keeps it on file for the number. NoClick keeps its name, not the file, and offers it again for your next
                    number.
                </p>
            )}
        </div>
    );
}
