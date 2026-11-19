// A harness as Work draws it: its maker's mark and its name, on the SDK's harness names (sdk is NoClick's own agent).
// Shared by the agents list, an agent's profile, the New agent draft, the model picker and the conversation.
import { SiClaude, SiOpenai } from 'react-icons/si';
import type { HarnessName } from 'noclick';
import { LogoMark } from '@/ui/LogoMark';
import { useSlot } from '@/slots';
import { HARNESS_MARK } from '../slots';
import { cn } from '@/ui/utils';

/** Every harness, in the order Work lists them, with what it is in a line. */
export const HARNESSES: { id: HarnessName; note: string }[] = [
    { id: 'claude_code', note: 'Anthropic’s coding agent' },
    { id: 'codex', note: 'OpenAI’s coding agent' },
    { id: 'opencode', note: 'Open source, any model' },
    { id: 'hermes', note: 'Nous Research’s agent, with skills it writes itself' },
    { id: 'openclaw', note: 'The open personal assistant' },
    { id: 'sdk', note: 'NoClick’s own agent, quickest to answer' },
];

const LABEL: Record<HarnessName, string> = { sdk: 'NoClick agent', claude_code: 'Claude Code', codex: 'Codex', opencode: 'OpenCode', hermes: 'Hermes', openclaw: 'OpenClaw' };

/** "Claude Code", "NoClick agent". */
export const harnessLabel = (harness: HarnessName) => LABEL[harness] ?? harness;
/** As a sentence names it: "NoClick’s own agent" for sdk. */
export const harnessName = (harness: HarnessName) => (harness === 'sdk' ? 'NoClick’s own agent' : harnessLabel(harness));

/** A harness's mark: its maker's logo, as the app draws it everywhere else; one the app has no drawing of is
 *  whoever shows Work's (`HARNESS_MARK`), else a plain dot. */
export function HarnessMark({ harness, className = 'h-4 w-4' }: { harness: HarnessName; className?: string }) {
    const brand = useSlot(HARNESS_MARK)[harness];
    if (harness === 'claude_code') return <SiClaude className={cn('shrink-0 text-[#D97757]', className)} aria-hidden />;
    if (harness === 'codex') return <SiOpenai className={cn('shrink-0 text-foreground', className)} aria-hidden />;
    // NoClick's mark fills its box edge to edge, so it reads larger than the others' at the same size.
    if (harness === 'sdk') return <LogoMark className={cn('shrink-0 scale-[0.78] text-foreground', className)} />;
    if (!brand) return <span aria-hidden className={cn('shrink-0 rounded-full bg-foreground/[0.1]', className)} />;
    return (
        <img
            src={brand.src}
            alt=""
            aria-hidden
            draggable={false}
            className={cn('shrink-0 object-contain', brand.monochrome && 'invert dark:invert-0', className)}
            style={brand.inset ? { transform: `scale(${brand.inset})` } : undefined}
        />
    );
}
