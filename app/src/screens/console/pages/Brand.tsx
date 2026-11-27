// Brand: how approval pages and emails look to the people your platform key
// reaches. The form edits the account's one brand (PUT /v1/brand; Reset is
// DELETE, back to NoClick's defaults); the preview renders the real /h/{id}
// page component, contained, and an approximation of the email. Your own OAuth
// app per provider changes one provider at a time (PATCH), and a save keeps
// them. In the lab (designed): the domain those pages and emails come from.
import { useState, type ReactNode } from 'react';
import { Palette } from 'lucide-react';
import { toast } from 'sonner';
import { HAIRLINE } from '@/ui/primitives';
import { FieldSelect } from '@/ui/FieldSelect';
import { cn } from '@/ui/utils';
import { Brand, NoClickError, Secret } from 'noclick';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { useV1 } from '@/sdk/useV1';
import { brandPresentation, EYEBROW, HumanRequestView, Details, type Brand as PageBrand, type HumanRequestContent } from '@/screens/humans/HumanRequestView';
import { ConsoleButton } from '../ui/Button';
import { ConsoleDialog } from '../ui/ConsoleDialog';
import { CopyButton } from '../ui/CopyButton';
import { ErrorPanel } from '../ui/ErrorPanel';
import { PageHeader } from '../ui/PageHeader';
import { Segmented } from '../ui/Segmented';

export type BrandField = 'name' | 'logo_url' | 'color' | 'support_url' | 'email_from_name';
export type BrandDraft = Record<BrandField, string>;

/** Control characters and what would break out of a From display name (`brand/service._UNSAFE_NAME`). */
const unsafeName = (value: string) => [...value].some((c) => c.charCodeAt(0) < 0x20 || c.charCodeAt(0) === 0x7f || '<>"\\'.includes(c));
const HEX = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;

/** The account's example approval: the preview's canned request. */
export const PREVIEW_REQUEST: HumanRequestContent = {
    kind: 'approve',
    message: 'Support Bot wants to send the weekly summary to your team. Approve it?',
    options: [],
    details: { To: 'team@example.com', Subject: 'Weekly summary' },
    status: 'pending',
    answer: null,
};

function httpsOk(value: string): boolean {
    try {
        const url = new URL(value);
        return url.protocol === 'https:' && !!url.hostname && !url.username && !url.password && !/\s/.test(value);
    } catch {
        return false;
    }
}

/** The same refusals as `brand/service.validate`, per field. */
export function validateBrand(draft: BrandDraft): Partial<Record<BrandField, string>> {
    const errors: Partial<Record<BrandField, string>> = {};
    const name = draft.name.trim();
    if (!name) errors.name = 'Name is required.';
    else if (name.length > 80) errors.name = 'Name is at most 80 characters.';
    else if (unsafeName(name)) errors.name = 'Name can\'t contain line breaks, control characters, <, >, " or \\.';
    for (const field of ['logo_url', 'support_url'] as const) {
        const value = draft[field].trim();
        if (value && !httpsOk(value)) errors[field] = 'Use a full https:// URL.';
    }
    const color = draft.color.trim();
    if (color && !HEX.test(color)) errors.color = 'Use a hex color like #1a73e8.';
    const from = draft.email_from_name.trim();
    if (from.length > 80) errors.email_from_name = 'At most 80 characters.';
    else if (unsafeName(from)) errors.email_from_name = 'Can\'t contain line breaks, control characters, <, >, " or \\.';
    return errors;
}

function draftOf(brand: Brand): BrandDraft {
    return {
        name: brand.name ?? '',
        logo_url: brand.logoUrl ?? '',
        color: brand.color ?? '',
        support_url: brand.supportUrl ?? '',
        email_from_name: brand.emailFromName ?? '',
    };
}

const orNull = (v: string) => v.trim() || null;

/** `#abc` → `#aabbcc`; what `<input type="color">` accepts. */
function sixDigit(color: string): string | null {
    const c = color.trim();
    if (!HEX.test(c)) return null;
    return c.length === 4 ? `#${[...c.slice(1)].map((ch) => ch + ch).join('')}`.toLowerCase() : c.toLowerCase();
}

export function pageBrand(draft: BrandDraft): PageBrand {
    return { name: draft.name.trim() || 'NoClick', logo_url: orNull(draft.logo_url), color: sixDigit(draft.color), support_url: orNull(draft.support_url) };
}

function FieldRow({ label, htmlFor, hint, error, children }: { label: string; htmlFor: string; hint?: string; error?: string; children: ReactNode }) {
    return (
        <div className="flex flex-col gap-1.5">
            <label htmlFor={htmlFor} className="text-[12px] font-medium text-muted-foreground">
                {label}
            </label>
            {children}
            {error ? (
                <p id={`${htmlFor}-error`} className="m-0 text-[12px] text-red-600 dark:text-red-400">
                    {error}
                </p>
            ) : hint ? (
                <p className="m-0 text-[12px] text-muted-foreground">{hint}</p>
            ) : null}
        </div>
    );
}

/** A host the account holds, like `connect.acme.com`. */
const HOST = /^[a-z0-9-]+(\.[a-z0-9-]+)+$/i;

/** The providers an app can be brought for (`brand/service.OAUTH_APP_PROVIDERS`), as people write them. */
const PROVIDER_NAMES: Record<string, string> = {
    asana: 'Asana', box: 'Box', clickup: 'ClickUp', gitlab: 'GitLab', google: 'Google', intercom: 'Intercom', klaviyo: 'Klaviyo',
    monday: 'monday.com', pagerduty: 'PagerDuty', pipedrive: 'Pipedrive', slack: 'Slack', webflow: 'Webflow', zoom: 'Zoom',
};
const providerName = (provider: string) => PROVIDER_NAMES[provider] ?? provider;

function RedirectUri({ url }: { url: string }) {
    return (
        <span className="flex min-w-0 items-center gap-1 text-[12px] text-muted-foreground">
            Redirect URI: <span className="truncate font-mono text-foreground/85">{url}</span>
            <CopyButton value={url} label="Copy the redirect URI" />
        </span>
    );
}


/** Your own OAuth app per provider: an account secret holding CLIENT_ID and CLIENT_SECRET, one provider at a time. */
function OAuthApps({ brand, apps, onApps }: { brand: Brand; apps: Record<string, string>; onApps: (apps: Record<string, string>) => void }) {
    const { client } = useConsole();
    const secrets = useV1('brand/oauth_app_secrets', () => Secret.list({ client }));
    const accountSecrets = (secrets.data ?? []).filter((secret) => secret.userId === null);
    const named = Object.entries(apps);
    const open = Object.keys(brand.oauthRedirectUrls).filter((provider) => !(provider in apps));
    const [provider, setProvider] = useState('');
    const [secretId, setSecretId] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const change = async (target: string, secret: string | null) => {
        setBusy(true);
        setError(null);
        try {
            onApps((await Brand.update({ oauthApps: { [target]: secret } }, { client })).oauthApps);
            if (secret) {
                setProvider('');
                setSecretId('');
            }
            toast(secret ? `${providerName(target)} connects with your app` : `${providerName(target)} connects with NoClick's app`);
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        } finally {
            setBusy(false);
        }
    };
    return (
        <div className="flex flex-col gap-1.5">
            <span className="text-[12px] font-medium text-muted-foreground">OAuth apps</span>
            {named.length ? (
                <ul aria-label="OAuth apps" className={'m-0 -mx-3 list-none p-0'}>
                    {named.map(([name, id]) => (
                        <li key={name} className={cn('flex flex-col gap-1 px-3 py-2')}>
                            <div className="flex items-center justify-between gap-2 text-[13px]">
                                <span className="font-medium">{providerName(name)}</span>
                                <span className="flex min-w-0 items-center gap-1">
                                    <span className="truncate font-mono text-[12px] text-muted-foreground">{secrets.data?.find((s) => s.id === id)?.name ?? id}</span>
                                    <ConsoleButton variant="ghost" size="sm" disabled={busy} onClick={() => void change(name, null)} aria-label={`Remove ${providerName(name)}'s app`}>
                                        Remove
                                    </ConsoleButton>
                                </span>
                            </div>
                            {brand.oauthRedirectUrls[name] && <RedirectUri url={brand.oauthRedirectUrls[name]} />}
                        </li>
                    ))}
                </ul>
            ) : (
                <p className="m-0 text-[12px] text-muted-foreground">None: consent screens name NoClick.</p>
            )}
            {brand.isDefault ? (
                <p className="m-0 text-[12px] text-muted-foreground">Save your brand first, then name your apps.</p>
            ) : (
                open.length > 0 && (
                    <div className="flex flex-col gap-1.5">
                        <div className="flex items-center gap-2">
                            <FieldSelect aria-label="Provider" className="h-8 flex-1" placeholder="Provider" value={provider} onValueChange={setProvider} options={open.map((name) => ({ value: name, label: providerName(name) }))} />
                            <FieldSelect
                                aria-label="App secret"
                                className="h-8 flex-1"
                                placeholder="Secret"
                                value={secretId}
                                onValueChange={setSecretId}
                                options={accountSecrets.map((secret) => ({ value: secret.id, label: secret.name }))}
                            />
                            <ConsoleButton size="sm" disabled={busy || !provider || !secretId} onClick={() => void change(provider, secretId)}>
                                Add
                            </ConsoleButton>
                        </div>
                        {provider && brand.oauthRedirectUrls[provider] && <RedirectUri url={brand.oauthRedirectUrls[provider]} />}
                    </div>
                )
            )}
            {error && (
                <p role="alert" className="m-0 text-[12px] text-red-600 dark:text-red-400">
                    {error}
                </p>
            )}
            <p className="m-0 text-[12px] text-muted-foreground">
                Your app puts your name on the provider&apos;s consent screen. Register its redirect URI there, and keep its client id and secret in an account secret as CLIENT_ID and CLIENT_SECRET. Connect links made
                after sign in with it; connections made before keep NoClick&apos;s until reconnected.
            </p>
        </div>
    );
}

const INPUT = 'h-9 w-full rounded-md border border-input bg-background px-3 text-[13px] text-foreground outline-none placeholder:text-[hsl(var(--placeholder))] focus-visible:ring-2 focus-visible:ring-ring';

/** The branded email, approximately: the shell's eyebrow, heading, body and footer. */
export function EmailPreview({ draft, isDefault }: { draft: BrandDraft; isDefault: boolean }) {
    const { name, logoUrl, supportUrl } = brandPresentation(pageBrand(draft));
    const from = draft.email_from_name.trim() || name;
    return (
        <div className="flex flex-col gap-3 px-4 py-6">
            <dl className="m-0 grid grid-cols-[4rem_1fr] gap-y-1 text-[12px]">
                <dt className="text-muted-foreground">From</dt>
                <dd className="m-0 truncate text-foreground">{from}</dd>
                <dt className="text-muted-foreground">Subject</dt>
                <dd className="m-0 truncate text-foreground">Approval needed: {PREVIEW_REQUEST.message}</dd>
            </dl>
            <div className="mx-auto w-full max-w-md rounded-xl border border-border bg-card px-6 py-7">
                {logoUrl && <img src={logoUrl} alt="" referrerPolicy="no-referrer" className="mb-4 h-10 w-10 rounded-lg object-contain" />}
                <p className="m-0 text-xs font-semibold uppercase tracking-wider text-muted-foreground">{EYEBROW.approve}</p>
                <h3 className="m-0 mt-2 text-lg font-semibold tracking-tight text-foreground">{name} needs your approval</h3>
                <p className="m-0 mt-3 text-sm leading-relaxed text-foreground">{PREVIEW_REQUEST.message}</p>
                <Details details={PREVIEW_REQUEST.details} />
                <span className="mt-5 inline-block rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground">Review and respond</span>
                <div className="mt-6 flex flex-col gap-1 border-t border-border pt-4 text-[12px] text-muted-foreground">
                    <p className="m-0">{`Sent through NoClick ${isDefault ? "on someone's behalf" : `by ${name}`}. If you didn't expect it, you can ignore this email.`}</p>
                    {supportUrl && <p className="m-0">Questions? Contact {name}</p>}
                </div>
            </div>
            <p className="m-0 text-center text-[12px] text-muted-foreground">{"An approximation: the email's exact layout may differ."}</p>
        </div>
    );
}

function BrandEditor({ saved, onChanged }: { saved: Brand; onChanged: () => Promise<void> }) {
    const { client, lab } = useConsole();
    const [draft, setDraft] = useState<BrandDraft>(() => draftOf(saved));
    // Designed, lab only: the host the pages are served from.
    const [domain, setDomain] = useState(saved.domain ?? '');
    const [domainError, setDomainError] = useState<string | null>(null);
    // Saved as they change (PATCH); a save of the form sends them back as they are.
    const [apps, setApps] = useState(saved.oauthApps);
    const [errors, setErrors] = useState<Partial<Record<BrandField, string>>>({});
    const [failure, setFailure] = useState<unknown>(undefined);
    const [saving, setSaving] = useState(false);
    const [resetting, setResetting] = useState(false);
    const [confirmReset, setConfirmReset] = useState(false);
    const [view, setView] = useState<'page' | 'email'>('page');
    const dirty = (Object.keys(draft) as BrandField[]).some((k) => draft[k] !== draftOf(saved)[k]) || (lab && domain.trim() !== (saved.domain ?? ''));
    const set = (field: BrandField) => (value: string) => {
        setDraft((d) => ({ ...d, [field]: value }));
        setErrors((e) => ({ ...e, [field]: undefined }));
    };

    const save = async () => {
        const found = validateBrand(draft);
        setErrors(found);
        setFailure(undefined);
        const badDomain = lab && domain.trim() !== '' && !HOST.test(domain.trim());
        setDomainError(badDomain ? 'Use a host name like connect.acme.com.' : null);
        if (Object.values(found).some(Boolean) || badDomain) return;
        setSaving(true);
        try {
            // A save replaces the brand whole, so the OAuth apps (and, in the lab, the designed domain) go back as they are.
            const kept = { oauthApps: Object.keys(apps).length ? apps : undefined, ...(lab ? { domain: orNull(domain) } : {}) };
            await Brand.set(
                {
                    name: draft.name.trim(),
                    logoUrl: orNull(draft.logo_url),
                    color: orNull(draft.color),
                    supportUrl: orNull(draft.support_url),
                    emailFromName: orNull(draft.email_from_name),
                    ...kept,
                },
                { client }
            );
            toast('Brand saved');
            await onChanged();
        } catch (e) {
            const field = e instanceof NoClickError ? (e.details.field as BrandField | undefined) : undefined;
            if (field && field in draft) setErrors({ [field]: e instanceof Error ? e.message : String(e) });
            else setFailure(e);
        } finally {
            setSaving(false);
        }
    };

    const reset = async () => {
        setResetting(true);
        try {
            await Brand.reset({ client });
            setConfirmReset(false);
            toast('Brand reset to NoClick');
            await onChanged();
        } catch (e) {
            setFailure(e);
            setConfirmReset(false);
        } finally {
            setResetting(false);
        }
    };

    const described = (field: BrandField) => (errors[field] ? { 'aria-invalid': true, 'aria-describedby': `brand-${field}-error` } : {});
    const swatch = sixDigit(draft.color);
    return (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
            <form
                className="flex flex-col gap-4 self-start"
                onSubmit={(e) => {
                    e.preventDefault();
                    void save();
                }}
            >
                <div className="flex items-center justify-between">
                    <h2 className="m-0 text-[13px] font-semibold text-foreground">Your brand</h2>
                    {saved.isDefault && <span className="rounded-md bg-foreground/[0.06] px-1.5 py-[1px] text-[12px] font-medium text-muted-foreground">Default</span>}
                </div>
                <FieldRow label="Name" htmlFor="brand-name" error={errors.name}>
                    <input id="brand-name" className={INPUT} value={draft.name} maxLength={80} onChange={(e) => set('name')(e.target.value)} {...described('name')} />
                </FieldRow>
                <FieldRow label="Logo URL" htmlFor="brand-logo_url" hint="An https image; square works best." error={errors.logo_url}>
                    <input id="brand-logo_url" className={INPUT} value={draft.logo_url} placeholder="https://" onChange={(e) => set('logo_url')(e.target.value)} {...described('logo_url')} />
                </FieldRow>
                <FieldRow label="Accent color" htmlFor="brand-color" hint="One bar across the top of the page." error={errors.color}>
                    <div className="flex items-center gap-2">
                        {/* The swatch is the app's; the colour it opens is the system's own picker, which no field of ours replaces. */}
                        <label
                            className="relative grid h-9 w-9 shrink-0 cursor-pointer place-items-center overflow-hidden rounded-full border border-input focus-within:ring-2 focus-within:ring-ring"
                            style={swatch ? { background: swatch } : undefined}
                        >
                            {!swatch && <Palette aria-hidden className="h-4 w-4 text-muted-foreground" />}
                            <input
                                key={swatch ? 'set' : 'unset'}
                                type="color"
                                aria-label="Pick accent color"
                                {...(swatch ? { value: swatch } : {})}
                                onChange={(e) => set('color')(e.target.value)}
                                className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                            />
                        </label>
                        <input id="brand-color" className={cn(INPUT, 'font-mono')} value={draft.color} placeholder="None" onChange={(e) => set('color')(e.target.value)} {...described('color')} />
                    </div>
                </FieldRow>
                <FieldRow label="Support URL" htmlFor="brand-support_url" hint={'Shown as "Questions? Contact …".'} error={errors.support_url}>
                    <input id="brand-support_url" className={INPUT} value={draft.support_url} placeholder="https://" onChange={(e) => set('support_url')(e.target.value)} {...described('support_url')} />
                </FieldRow>
                <FieldRow label="Email from name" htmlFor="brand-email_from_name" hint="The sender name on emails; defaults to the name." error={errors.email_from_name}>
                    <input id="brand-email_from_name" className={INPUT} value={draft.email_from_name} placeholder={draft.name || 'NoClick'} onChange={(e) => set('email_from_name')(e.target.value)} {...described('email_from_name')} />
                </FieldRow>
                {lab && (
                    <FieldRow
                        label="Domain"
                        htmlFor="brand-domain"
                        hint="Serves the connect, approval and hand-off pages, and sends their emails, from your host: one CNAME record on a domain your account holds."
                        error={domainError ?? undefined}
                    >
                        <input
                            id="brand-domain"
                            className={cn(INPUT, 'font-mono')}
                            value={domain}
                            placeholder="connect.acme.com"
                            onChange={(e) => {
                                setDomain(e.target.value);
                                setDomainError(null);
                            }}
                        />
                    </FieldRow>
                )}
                <OAuthApps brand={saved} apps={apps} onApps={setApps} />
                {failure !== undefined && <ErrorPanel error={failure} />}
                <div className="flex items-center gap-2">
                    <ConsoleButton type="submit" variant="primary" disabled={saving || !dirty}>
                        {saving ? 'Saving…' : 'Save'}
                    </ConsoleButton>
                    {!saved.isDefault && (
                        <ConsoleButton variant="ghost" onClick={() => setConfirmReset(true)}>
                            Reset
                        </ConsoleButton>
                    )}
                </div>
            </form>
            <section className="flex min-w-0 flex-col gap-2">
                <div className="flex items-center justify-between gap-2">
                    <h2 className="m-0 text-[13px] font-semibold text-foreground">Preview</h2>
                    <Segmented
                        label="Preview"
                        value={view}
                        onChange={setView}
                        options={[
                            { value: 'page', label: 'Approval page' },
                            { value: 'email', label: 'Email' },
                        ]}
                    />
                </div>
                <div data-testid="brand-preview" className={cn('min-w-0 overflow-hidden rounded-xl border bg-background', HAIRLINE)}>
                    {view === 'page' ? (
                        <HumanRequestView request={PREVIEW_REQUEST} brand={pageBrand(draft)} preview />
                    ) : (
                        <EmailPreview draft={draft} isDefault={saved.isDefault && !dirty} />
                    )}
                </div>
            </section>
            <ConsoleDialog
                open={confirmReset}
                onOpenChange={setConfirmReset}
                size="sm"
                title="Reset your brand?"
                description="Approval pages and emails go back to NoClick's name and look."
                footer={
                    <>
                        <ConsoleButton variant="ghost" onClick={() => setConfirmReset(false)}>
                            Cancel
                        </ConsoleButton>
                        <ConsoleButton variant="danger" disabled={resetting} onClick={() => void reset()}>
                            {resetting ? 'Resetting…' : 'Reset brand'}
                        </ConsoleButton>
                    </>
                }
            />
        </div>
    );
}

export default function BrandPage() {
    const { client } = useConsole();
    const href = useConsoleHref();
    const brand = useV1('brand', () => Brand.get({ client }));
    return (
        <>
            <PageHeader crumbs={[{ label: 'Settings', href: href('settings') }]} title="Brand" purpose="What your users see on the pages and emails that ask them to connect an account or answer a request." />
            {brand.error !== undefined && !brand.data ? (
                <ErrorPanel error={brand.error} onRetry={() => void brand.refresh()} />
            ) : !brand.data ? (
                <div aria-busy className="h-96 animate-pulse rounded-xl bg-foreground/[0.04]" />
            ) : (
                <BrandEditor key={String(brand.data.raw.updated_at)} saved={brand.data} onChanged={brand.refresh} />
            )}
        </>
    );
}
