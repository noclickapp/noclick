// What a hand-off's receipt in the thread is built from: how long its work took, said one way ("3 min"), and the quiet
// pill that leads to the change.
import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { ArrowUpRight } from 'lucide-react';
import { PILL_QUIET, PILL_SECONDARY } from '@/ui/chat/primitives';
import { cn } from '@/ui/utils';
import { Ink } from './ink';

const SM = 'h-7 px-3 text-[12.5px]';

/** "3 min", "40s", "1 h 12 min": how long, the one way the thread says it. */
export function durationWords(seconds: number): string {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return h ? (m ? `${h} h ${m} min` : `${h} h`) : m ? `${m} min` : `${Math.max(0, Math.floor(seconds))}s`;
}

/** A link to somewhere: within the app, in place; anywhere else, in a new tab. */
function Way({ href, className, children }: { href: string; className: string; children: ReactNode }) {
    return href.startsWith('/') ? (
        <Link to={href} data-ink className={className}>
            {children}
        </Link>
    ) : (
        <a href={href} target="_blank" rel="noopener noreferrer" data-ink className={className}>
            {children}
        </a>
    );
}

/** A way in (the change it made) as the thread's grey pill, or a quiet one. */
export function QuietPill({ children, href, external, way = true }: { children: ReactNode; href: string; external?: boolean; way?: boolean }) {
    return (
        <Way href={href} className={cn(way ? PILL_SECONDARY : PILL_QUIET, SM, 'relative z-10')}>
            <Ink>{children}</Ink>
            {external && <ArrowUpRight className="h-3.5 w-3.5 opacity-60" />}
        </Way>
    );
}
