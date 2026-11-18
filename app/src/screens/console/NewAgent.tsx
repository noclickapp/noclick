// "New agent": an agent is made in code, so this shows the code that makes one,
// the prompt that has a coding agent write it, and the guide. Nothing here
// creates an agent; it appears on Home once the code runs.
import { useState } from 'react';
import { ArrowUpRight, Bot } from 'lucide-react';
import { cn } from '@/ui/utils';
import { HAIRLINE } from '@/ui/primitives';
import { useSlot } from '@/slots';
import { NEW_AGENT, snippetTabs } from '@/screens/console/lib/snippets';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { docsUrl } from '@/screens/console/lib/site';
import { CopyPromptAction, WorksWith, useCopyPrompt } from './Quickstart';
import { ConsoleButton } from './ui/Button';
import { CodeSnippet } from './ui/CodeSnippet';
import { ConsoleDialog } from './ui/ConsoleDialog';
import { useOwnerOnly } from './ownerOnly';
import { TERMS } from './slots';

const LABEL = 'm-0 mb-2.5 text-[13px] font-medium text-foreground/70 dark:text-muted-foreground';


export function NewAgentDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
    const copier = useCopyPrompt();
    const { site } = useConsole();
    const Terms = useSlot(TERMS);
    const ownerCan = useOwnerOnly();
    const [lang, setLang] = useState('python');
    return (
        <ConsoleDialog
            open={open}
            onOpenChange={onOpenChange}
            size="lg"
            mark={<Bot aria-hidden className="h-5 w-5" />}
            title="New agent"
            description="Agents are made in your code. Run this once and the agent shows up here; running it again finds the same one."
            footer={
                <>
                    <a href={docsUrl(site, 'guide/agents')} target="_blank" rel="noreferrer" className="mr-auto inline-flex items-center gap-1 text-[13px] text-muted-foreground transition-colors hover:text-foreground">
                        The agents guide <ArrowUpRight aria-hidden className="h-3.5 w-3.5" />
                    </a>
                    <ConsoleButton onClick={() => onOpenChange(false)}>Done</ConsoleButton>
                </>
            }
        >
            <div className="flex flex-col gap-6">
                <section aria-label="Create it from your code">
                    <h3 className={LABEL}>Create it from your code</h3>
                    <CodeSnippet tabs={snippetTabs(NEW_AGENT)} tab={lang} onTabChange={setLang} />
                </section>
                {ownerCan('setupCode') && (
                <section aria-label="Or let your coding agent write it" className={cn('flex flex-col gap-3 border-t pt-6', HAIRLINE)}>
                    <div>
                        <h3 className={cn(LABEL, 'mb-1')}>Or let your coding agent write it</h3>
                        <p className="m-0 text-[13px] leading-relaxed text-muted-foreground">
                            One prompt: your coding agent installs NoClick, saves a key to your project without ever seeing it, and writes the agent with you.
                        </p>
                    </div>
                    <WorksWith />
                    <CopyPromptAction copier={copier} />
                    <Terms action="copying the prompt" />
                </section>
                )}
            </div>
        </ConsoleDialog>
    );
}
