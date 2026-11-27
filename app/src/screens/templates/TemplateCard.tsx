// A template's card in the gallery: its picture, its name in the serif, what it does in
// two lines, what it adds counted, and at its foot the apps it asks you to connect and what it costs a month.
import { CredentialMark } from '@/ui/connectionMark';
import { DISPLAY } from '@/ui/titles';
import { cn } from '@/ui/utils';
import { contentsLine, priceLine, type Listing } from './model';
import { TemplatePicture } from './Pictures';

/** The card's surface: the site's wash, a raised white card in light. */
export const CARD = 'bg-card ring-1 ring-inset ring-foreground/[0.07] dark:bg-foreground/[0.045] dark:ring-0';

/** The apps it asks you to connect, by their marks; a word where it asks for none. */
export function AskMarks({ t, size = 'md' }: { t: Listing; size?: 'sm' | 'md' }) {
    if (!t.connections.length) return <span className="text-[12.5px] text-muted-foreground/70">Asks for nothing</span>;
    return (
        <span className="flex items-center gap-2" aria-label={`Asks for ${t.connections.map((c) => c.label).join(', ')}`}>
            {t.connections.slice(0, 5).map((c) => (
                <CredentialMark key={c.integration} credentialType="" nodeType={c.nodeType} size={size} />
            ))}
        </span>
    );
}

export function TemplateCard({ t, href, onOpen }: { t: Listing; href?: string; onOpen?: (slug: string) => void }) {
    const body = (
        <>
            <TemplatePicture t={t} className="mx-2.5 mt-2.5 h-[208px]" />
            <div className="flex flex-1 flex-col px-5 pb-[18px] pt-[18px]">
                <h3 className={cn(DISPLAY, 'm-0 mt-0.5 text-[26px] leading-[1.05] text-foreground')}>{t.name}</h3>
                {t.description && <p className="mt-2 line-clamp-2 text-[14px] leading-[1.43] text-foreground/60">{t.description}</p>}
                <p className="mt-2 text-[12.5px] text-muted-foreground">{contentsLine(t)}</p>
                <div className="mt-auto flex min-h-[22px] items-center gap-2.5 pt-[18px]">
                    <AskMarks t={t} />
                    <span className="ml-auto whitespace-nowrap text-[12.5px] tabular-nums text-muted-foreground">{priceLine(t)}</span>
                </div>
            </div>
        </>
    );
    const className = cn(CARD, 'flex w-full flex-col overflow-hidden rounded-3xl text-left text-foreground no-underline transition-[background-color,box-shadow] hover:ring-foreground/[0.16] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:hover:bg-foreground/[0.07]');
    return href ? (
        <a href={href} className={className} data-template={t.slug}>
            {body}
        </a>
    ) : (
        <button type="button" onClick={() => onOpen?.(t.slug)} className={className} data-template={t.slug}>
            {body}
        </button>
    );
}
