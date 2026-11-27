// Home's Templates, a row under Threads: NoClick's template gallery in the conversation's place, as
// Threads opens, and a template's page over it (`listing` in the URL). Its button adds the template to the space you
// came from (a space of yours), else to a new space, on Work's page of asks. The gallery is read with no key, as the
// site reads it.
import { ChevronRight } from 'lucide-react';
import { TemplateListing } from 'noclick';
import { PhoneBarBack } from '@/ui/phoneBar';
import { BUTTON_PRIMARY } from '@/ui/buttons';
import { PAGE_TITLE } from '@/ui/titles';
import { cn } from '@/ui/utils';
import { errorText } from '@/screens/console/pages/resources/shared';
import { jobLabel } from '@/screens/templates/model';
import { TemplateGallery } from '@/screens/templates/TemplateGallery';
import { TemplatePageView } from '@/screens/templates/TemplatePage';
import { useWorkV1 } from '../agents/reads';

export const TEMPLATES_KEY = 'work:templates';

export function TemplatesPane({
    listing,
    spaceName,
    into,
    phone,
    onBack,
    onOpen,
    onAdd,
}: {
    /** The template whose page is open; null for the gallery. */
    listing: string | null;
    spaceName: string;
    /** The space an add goes into (a workspace of yours); null, a new space. */
    into: string | null;
    phone: boolean;
    onBack: () => void;
    onOpen: (slug: string | null) => void;
    /** Add it: Work's page of asks for its address. */
    onAdd: (address: string) => void;
}) {
    const list = useWorkV1(TEMPLATES_KEY, (client) => TemplateListing.list({ client }));
    const page = useWorkV1(listing ? `${TEMPLATES_KEY}:${listing}` : null, (client) => TemplateListing.get(listing ?? '', { client }));
    const open = listing ? page.data : null;
    const error = (listing ? page.error : list.error) ?? null;
    const name = open?.name ?? list.data?.find((t) => t.slug === listing)?.name ?? '';
    return (
        <section className="flex min-h-0 min-w-0 flex-1 flex-col" data-testid="templates-pane">
            {phone &&
                (listing ? (
                    <PhoneBarBack label="Templates" title={<span className="truncate">{name}</span>} onBack={() => onOpen(null)} />
                ) : (
                    <PhoneBarBack label="Home" title={<span className="truncate">Templates</span>} onBack={onBack} />
                ))}
            <div className="min-h-0 flex-1 overflow-y-auto scrollbar-subtle">
                <div className="mx-auto max-w-[1080px] px-4 pb-16 pt-4 sm:px-8 md:pt-10">
                    {error ? (
                        <p role="alert" className="text-sm text-muted-foreground">
                            {errorText(error)}
                        </p>
                    ) : listing ? (
                        open ? (
                            <TemplatePageView
                                t={open}
                                crumb={
                                    <p className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
                                        <button type="button" onClick={() => onOpen(null)} className="hover:text-foreground">
                                            Templates
                                        </button>
                                        {jobLabel(open.job) && (
                                            <>
                                                <ChevronRight className="h-3.5 w-3.5" />
                                                {jobLabel(open.job)}
                                            </>
                                        )}
                                    </p>
                                }
                                from={open.repository?.name}
                                action={
                                    <button type="button" className={BUTTON_PRIMARY} onClick={() => onAdd(open.address)} data-testid="template-add">
                                        {into ? `Add to ${spaceName}` : 'Use this template'}
                                    </button>
                                }
                            />
                        ) : (
                            <div className="h-64 animate-pulse rounded-2xl bg-foreground/[0.04]" />
                        )
                    ) : (
                        <>
                            {!phone && <h2 className={cn(PAGE_TITLE, 'm-0')}>Templates</h2>}
                            <p className="mb-7 mt-1.5 text-[14px] text-muted-foreground">Teams, agents and apps to add to {into ? spaceName : 'a new space'}.</p>
                            {list.data ? (
                                <TemplateGallery templates={list.data} onOpen={(slug) => onOpen(slug)} columns="grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3" />
                            ) : (
                                <div className="grid gap-5 lg:grid-cols-2">
                                    {[0, 1, 2, 3].map((i) => (
                                        <div key={i} className="h-[380px] animate-pulse rounded-3xl bg-foreground/[0.04]" />
                                    ))}
                                </div>
                            )}
                        </>
                    )}
                </div>
            </div>
        </section>
    );
}
