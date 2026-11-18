// What a console acting as a key shows where something only the owner can do would be: why it isn't here, and a link
// to where its owner does it (the page of NoClick's own console), in a new tab.
import { ArrowUpRight } from 'lucide-react';
import { cn } from '@/ui/utils';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { noclickConsoleUrl } from '@/screens/console/lib/site';
import { OWNER_ONLY, ownerOnlyWhy, type OwnerOnly, type OwnerOnlyRow } from '../ownerOnly';

/** `search` is the page's own query, carried to NoClick's page where the two take the same one (a sign-in's code). */
export function OwnerOnlyNote({ what, search = '', className }: { what: OwnerOnly; search?: string; className?: string }) {
    const { site } = useConsole();
    const { at }: OwnerOnlyRow = OWNER_ONLY[what];
    return (
        <p className={cn('m-0 text-[13px] leading-relaxed text-muted-foreground', className)}>
            {ownerOnlyWhy(what)}
            {at && (
                <>
                    {' '}
                    <a href={noclickConsoleUrl(site, at.page, search)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 whitespace-nowrap font-medium text-foreground hover:underline">
                        {at.link} <ArrowUpRight className="h-3.5 w-3.5 text-muted-foreground" />
                    </a>
                </>
            )}
        </p>
    );
}
