// A template's picture in the gallery: its own screenshots, each in NoClick's laptop or phone frame (never the
// listing's own chrome, stars or badges), else NoClick's picture of what it makes: its agents' faces, its app in a
// browser frame, its skill as a page, its memory as notes, its automation's steps.
import type { ReactNode } from 'react';
import { ArrowRight, BookOpen, Brain } from 'lucide-react';
import { MemberAvatar, type AvatarSize } from '@/screens/channels/avatars';
import { hueFor } from '@/screens/channels/model';
import type { ChannelMember } from '@/screens/channels/types';
import { NodeMark } from '@/ui/primitives';
import { DISPLAY } from '@/ui/titles';
import { cn } from '@/ui/utils';
import { pictureKind, type Listing } from './model';

/** The ground a picture sits on: darker than the card in dark, a soft grey in light. */
export const PICTURE_GROUND = 'bg-[hsl(240_6%_95.5%)] dark:bg-black/55';
/** On a page, which has no card under it: a faint lift of the page in dark. */
export const PAGE_GROUND = 'bg-[hsl(240_6%_95.5%)] dark:bg-foreground/[0.04]';

/** One of a template's agents as Work draws an agent: its face, by its name and job. */
export function agentMember(t: Pick<Listing, 'slug'>, agent: { name: string; role: string | null }): ChannelMember {
    return { id: `template:${t.slug}:${agent.name}`, kind: 'agent', name: agent.name, hue: hueFor(`${t.slug}:${agent.name}`), role: agent.role ?? undefined };
}

function Faces({ t, size }: { t: Listing; size: AvatarSize }) {
    const shown = t.agents.slice(0, 4);
    return (
        <div className="flex items-start justify-center gap-4">
            {shown.map((a) => (
                <figure key={a.name} className="m-0 flex flex-col items-center gap-2">
                    <MemberAvatar member={agentMember(t, a)} size={size} />
                    <figcaption className="max-w-[88px] truncate text-[12px] text-muted-foreground">{a.name}</figcaption>
                </figure>
            ))}
        </div>
    );
}

/** NoClick's browser frame: three dots, no address, the page beneath. */
export function LaptopFrame({ children, className }: { children: ReactNode; className?: string }) {
    return (
        <div className={cn('overflow-hidden rounded-xl bg-card shadow-[0_0_0_1px_hsl(var(--border)),0_10px_30px_rgb(0_0_0/0.25)]', className)}>
            <div className="flex h-[18px] items-center gap-1 bg-foreground/[0.05] px-2" aria-hidden>
                {[0, 1, 2].map((i) => (
                    <i key={i} className="h-[5px] w-[5px] rounded-full bg-foreground/20" />
                ))}
            </div>
            {children}
        </div>
    );
}

/** NoClick's phone frame: a dark rim round the page. */
export function PhoneFrame({ children, className }: { children: ReactNode; className?: string }) {
    return <div className={cn('overflow-hidden rounded-[18px] border-[4px] border-zinc-900 bg-card shadow-[0_10px_30px_rgb(0_0_0/0.3)] dark:border-zinc-700', className)}>{children}</div>;
}

/** Its own screenshots: the first laptop one, with the first phone one in front of it where it has one. */
function Screenshots({ t }: { t: Listing }) {
    const laptop = t.pictures.find((p) => p.frame === 'laptop');
    const phone = t.pictures.find((p) => p.frame === 'phone');
    return (
        <div className="relative h-full w-full">
            {laptop && (
                <LaptopFrame className={cn('absolute top-[12%] w-[74%]', phone ? 'left-[8%]' : 'left-[13%]')}>
                    <img src={laptop.url} alt={laptop.caption ?? `${t.name} on a laptop`} className="block aspect-[16/10] w-full object-cover object-top" loading="lazy" />
                </LaptopFrame>
            )}
            {phone && (
                <PhoneFrame className={cn('absolute bottom-[8%] w-[24%]', laptop ? 'right-[8%]' : 'left-[38%]')}>
                    <img src={phone.url} alt={phone.caption ?? `${t.name} on a phone`} className="block aspect-[9/19] w-full object-cover object-top" loading="lazy" />
                </PhoneFrame>
            )}
        </div>
    );
}

/** An app with no screenshots of its own: its frame, named. */
function AppFrame({ t }: { t: Listing }) {
    return (
        <LaptopFrame className="w-[68%]">
            <div className="px-4 pb-5 pt-4">
                <p className={cn(DISPLAY, 'text-[20px] leading-tight text-foreground')}>{t.name}</p>
                <div className="mt-3 space-y-1.5" aria-hidden>
                    <i className="block h-1.5 w-4/5 rounded-full bg-foreground/10" />
                    <i className="block h-1.5 w-3/5 rounded-full bg-foreground/10" />
                </div>
                <i className="mt-3 block h-5 w-20 rounded-full bg-foreground/80" aria-hidden />
            </div>
        </LaptopFrame>
    );
}

/** A skill, as the page its agents read: its name, what it's for, and its first lines. */
function SkillPage({ t, large = false }: { t: Listing; large?: boolean }) {
    const skill = t.skills[0];
    return (
        <div className={cn('rounded-xl bg-card p-4 shadow-[0_0_0_1px_hsl(var(--border)),0_10px_30px_rgb(0_0_0/0.2)]', large ? 'w-[86%] max-w-[560px] p-6' : 'w-[72%]')}>
            <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <BookOpen className="h-3.5 w-3.5" strokeWidth={1.75} />
                SKILL.md
            </p>
            <p className="mt-2 text-[14px] font-semibold text-foreground">{skill.name}</p>
            <p className="mt-1 line-clamp-3 text-[12px] leading-snug text-muted-foreground">{skill.description}</p>
            {large && skill.lines.length > 0 && (
                <div className="mt-3 space-y-1 border-t border-foreground/[0.08] pt-3 text-[12.5px] leading-snug text-foreground/80">
                    {skill.lines.map((line, i) => (
                        <p key={i} className={cn('m-0', /^#/.test(line) && 'font-semibold text-foreground')}>
                            {line.replace(/^#+\s*|^[-*]\s+/g, '')}
                        </p>
                    ))}
                </div>
            )}
        </div>
    );
}

/** A memory, as the notes it starts with. */
function MemoryNotes({ t }: { t: Listing }) {
    const memory = t.memories[0];
    return (
        <div className="w-[72%] rounded-xl bg-card p-4 shadow-[0_0_0_1px_hsl(var(--border)),0_10px_30px_rgb(0_0_0/0.2)]">
            <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <Brain className="h-3.5 w-3.5" strokeWidth={1.75} />
                {memory.name}
            </p>
            <ul className="mt-2 space-y-1.5">
                {memory.entries.slice(0, 3).map((e) => (
                    <li key={e.name} className="truncate text-[12px] text-foreground/85">
                        {e.description}
                    </li>
                ))}
            </ul>
        </div>
    );
}

/** An automation, as its steps in order. */
function Steps({ t }: { t: Listing }) {
    const steps = t.automations[0].steps.slice(0, 3);
    return (
        <div className="flex items-center gap-2 px-4">
            {steps.map((s, i) => (
                <span key={`${s.type}:${i}`} className="flex items-center gap-2">
                    {i > 0 && <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70" strokeWidth={1.75} />}
                    <span className="flex h-10 items-center gap-2 rounded-xl bg-card px-3 text-[12px] shadow-[0_0_0_1px_hsl(var(--border))]">
                        <NodeMark type={s.type} size="sm" />
                        <span className="max-w-[90px] truncate">{s.label ?? s.type.replace(/^automation-/, '')}</span>
                    </span>
                </span>
            ))}
        </div>
    );
}

/** The picture a card or a page leads with. */
export function TemplatePicture({ t, className, large = false }: { t: Listing; className?: string; large?: boolean }) {
    const kind = pictureKind(t);
    return (
        <div data-picture={kind} className={cn('relative flex items-center justify-center overflow-hidden rounded-[18px]', large ? PAGE_GROUND : PICTURE_GROUND, className)}>
            {kind === 'screenshots' ? (
                <Screenshots t={t} />
            ) : kind === 'faces' ? (
                <Faces t={t} size={t.agents.length === 1 ? 80 : large ? 80 : 48} />
            ) : kind === 'app' ? (
                <AppFrame t={t} />
            ) : kind === 'skill' ? (
                <SkillPage t={t} large={large} />
            ) : kind === 'memory' ? (
                <MemoryNotes t={t} />
            ) : kind === 'automation' ? (
                <Steps t={t} />
            ) : null}
        </div>
    );
}
