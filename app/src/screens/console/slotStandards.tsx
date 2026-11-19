// What stands in the console's slots when no host fills them (slots.ts).
import type { CardProgram } from 'noclick';
import { getNodeIconMeta } from '@/lib/nodeIconRegistry';
import { NodeMark, nodeLabel, type MarkSize } from '@/ui/primitives';
import { consoleButtonClass } from './ui/Button';

/** The mark the icon registry holds for the service's node type: a plain cube when it holds none. */
export function StandardCredentialMark({ nodeType, size = 'sm', className }: { credentialType: string; nodeType?: string | null; size?: MarkSize; className?: string }) {
    return <NodeMark type={nodeType ?? ''} size={size} className={className} />;
}

/** The service's name as the icon registry has it, else read off its type: `automation-google-sheets` is
 *  "Google sheets". */
export function standardCredentialLabel(credentialType: string, nodeType?: string | null): string {
    if (nodeType && getNodeIconMeta(nodeType)) return nodeLabel(nodeType);
    const words = (nodeType || credentialType).replace(/^automation-/, '').replace(/[-_]+/g, ' ').trim();
    return words ? words.charAt(0).toUpperCase() + words.slice(1) : '';
}

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
