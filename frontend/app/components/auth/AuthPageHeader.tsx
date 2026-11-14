// The top of a single-purpose auth page (reset, update, SSO, errors): the way back, then a serif title and one line
// on what the page does. Shipped, so both editions' pages share it.
import { ChevronLeft } from 'lucide-react';
import { Link } from 'react-router';
import { AUTH_QUIET_LINK_CLASS, AUTH_TITLE_CLASS } from '~/components/auth/authStyle';
import { cn } from '~/lib/utils';

export function AuthPageHeader({ back, title, description }: { back: { to: string; label: string }; title: string; description: string }) {
    return (
        <div className="mb-9">
            <Link to={back.to} className={cn('mb-10 inline-flex items-center gap-1 text-[14px]', AUTH_QUIET_LINK_CLASS)}>
                <ChevronLeft className="h-4 w-4" />
                {back.label}
            </Link>
            <h1 className={`${AUTH_TITLE_CLASS} text-[48px] sm:text-[56px]`}>{title}</h1>
            <p className="mt-4 max-w-sm text-[15px] leading-6 text-foreground/60">{description}</p>
        </div>
    );
}
