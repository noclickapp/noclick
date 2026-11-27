// NoClick's template gallery: a search, the jobs it files templates under (only those that hold one), and a card for
// each template, NoClick's own first. One gallery for every size of template, from one skill to a team with its app.
// Work draws it in a space's Home (Templates) and the site at noclick.com/templates; each card opens its page.
import { useMemo, useState } from 'react';
import { SearchField } from '@/ui/SearchField';
import { cn } from '@/ui/utils';
import { JOBS, matches, type Listing } from './model';
import { TemplateCard } from './TemplateCard';

const PILL = 'inline-flex h-9 shrink-0 items-center rounded-full px-4 text-[13.5px] font-medium transition-colors';

export function TemplateGallery({
    templates,
    hrefOf,
    onOpen,
    columns = 'grid-cols-1 md:grid-cols-2 xl:grid-cols-3',
}: {
    templates: Listing[];
    /** Each card's page, where cards are links (the site). */
    hrefOf?: (slug: string) => string;
    /** Opening a card's page in place (Work). */
    onOpen?: (slug: string) => void;
    columns?: string;
}) {
    const [query, setQuery] = useState('');
    const [job, setJob] = useState<string | null>(null);
    const jobs = useMemo(() => JOBS.filter((j) => templates.some((t) => t.job === j.id)), [templates]);
    const shown = templates.filter((t) => (!job || t.job === job) && matches(t, query));
    return (
        <div data-testid="template-gallery">
            <SearchField value={query} onChange={setQuery} placeholder="Search by job, app or what it adds" size="lg" className="w-full" aria-label="Search templates" />
            {jobs.length > 1 && (
                <div className="mt-4 flex gap-2 overflow-x-auto [scrollbar-width:none]" role="group" aria-label="Jobs">
                    {[{ id: null, label: 'All' }, ...jobs].map((j) => (
                        <button
                            key={j.id ?? 'all'}
                            type="button"
                            aria-pressed={job === j.id}
                            onClick={() => setJob(j.id)}
                            className={cn(PILL, job === j.id ? 'bg-foreground text-background' : 'bg-foreground/[0.06] text-foreground/80 hover:bg-foreground/[0.1]')}
                        >
                            {j.label}
                        </button>
                    ))}
                </div>
            )}
            {shown.length ? (
                <div className={cn('mt-8 grid gap-5', columns)}>
                    {shown.map((t) => (
                        <TemplateCard key={t.slug} t={t} href={hrefOf?.(t.slug)} onOpen={onOpen} />
                    ))}
                </div>
            ) : (
                <p className="mt-10 text-[14px] text-muted-foreground">{templates.length ? 'No template fits that yet.' : 'No templates are listed yet.'}</p>
            )}
        </div>
    );
}
