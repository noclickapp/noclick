// What stands in the console's slots when no host fills them (slots.ts).
import type { CardProgram } from 'noclick';
import { consoleButtonClass } from './ui/Button';

/** Where the company finishes its application for card issuing: the issuer's form isn't part of this app. */
export function IssuerLink({ program }: { program: CardProgram }) {
    return (
        <div className="flex flex-col items-start gap-3">
            <p className="m-0 max-w-xl text-[13px] text-muted-foreground">The card issuer takes these details in its own form, which a person signed in to NoClick fills in on NoClick&apos;s console.</p>
            {program.onboardingUrl && (
                <a href={program.onboardingUrl} target="_blank" rel="noreferrer" className={consoleButtonClass('primary')}>
                    Continue the application
                </a>
            )}
        </div>
    );
}
