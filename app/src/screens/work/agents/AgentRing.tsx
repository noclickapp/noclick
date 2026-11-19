// An agent's avatar (or a harness subagent's mark) with its state drawn as a ring round it, 3px out: solid ink when it
// needs you, red when its last turn failed, dashed and turning while it wakes, and the thinking shimmer while it works
// (one ink band running at a constant speed round a faint ring that breathes). Ink is the page's own foreground, never
// a colour. An agent's mascot inside the ring wears the same state as its face and loop.
import type { ReactNode } from 'react';
import { MemberAvatar, type AvatarSize } from '@/screens/channels/avatars';
import type { AgentState as FaceState, ChannelMember } from '@/screens/channels/types';
import { cn } from '@/ui/utils';
import type { RingStatus } from './states';

const INK = 'hsl(var(--foreground))';
const ink = (alpha: number) => `hsl(var(--foreground) / ${alpha})`;
/** Cuts a filled disc down to a 2px ring. */
const RING_MASK = 'radial-gradient(farthest-side, transparent calc(100% - 2.25px), #000 calc(100% - 2px))';

/** The motion Work's rings and working lines use; React hoists it once however many draw it. */
export const WORK_MOTION_CSS = `@keyframes work-spin { to { transform: rotate(360deg) } }
@keyframes work-breathe { 0%, 100% { opacity: .35 } 50% { opacity: 1 } }
.work-spin { animation: work-spin 1.1s linear infinite }
.work-breathe { animation: work-breathe 1.8s ease-in-out infinite }
@keyframes work-shine { from { background-position: -4.5rem 0, 0 0 } to { background-position: calc(100% + 4.5rem) 0, 0 0 } }
.work-shine { color: transparent; -webkit-background-clip: text; background-clip: text; background-repeat: no-repeat;
  background-image: linear-gradient(90deg, transparent, hsl(var(--foreground)), transparent), linear-gradient(hsl(var(--muted-foreground)), hsl(var(--muted-foreground)));
  background-size: 4.5rem 100%, 100% 100%; animation: work-shine 2.2s steps(30) infinite }
@keyframes work-step-in { from { transform: translateY(5px); opacity: 0 } }
.work-step-in { display: inline-block; animation: work-step-in 320ms cubic-bezier(0.32, 0.72, 0, 1) both }
@keyframes work-dot { 0%, 60%, 100% { transform: translateY(0); opacity: .45 } 30% { transform: translateY(-1.5px); opacity: 1 } }
.work-dot { animation: work-dot 1.3s ease-in-out infinite }
@keyframes work-rise { from { transform: scale(0.98); opacity: 0 } }
.work-rise { animation: work-rise 150ms cubic-bezier(0.32, 0.72, 0, 1); transform-origin: var(--radix-popover-content-transform-origin, var(--radix-dropdown-menu-content-transform-origin, bottom)) }
@keyframes work-trigger-ring { 0% { box-shadow: inset 0 0 0 1px rgb(16 185 129 / .5), 0 0 0 0 rgb(16 185 129 / .3) } 70% { box-shadow: inset 0 0 0 1px rgb(16 185 129 / .5), 0 0 0 6px rgb(16 185 129 / 0) } 100% { box-shadow: inset 0 0 0 1px rgb(16 185 129 / .5), 0 0 0 0 rgb(16 185 129 / 0) } }
.work-trigger-running { animation: work-trigger-ring 1.8s ease-out infinite }
@keyframes work-bolt { 0%, 100% { opacity: 1 } 50% { opacity: .4 } }
.work-bolt { animation: work-bolt 1.2s ease-in-out infinite }
@media (prefers-reduced-motion: reduce) { .work-spin, .work-breathe, .work-rise, .work-bolt, .work-step-in, .work-dot { animation: none } .work-trigger-running { animation: none; box-shadow: inset 0 0 0 1px rgb(16 185 129 / .5) } .work-shine { animation: none; color: hsl(var(--muted-foreground)); background: none } }`;

/** Puts Work's motion on the page once (React 19 dedupes a style by its href). */
export function WorkMotion() {
    return (
        <style href="work-motion" precedence="default">
            {WORK_MOTION_CSS}
        </style>
    );
}

/** The face a ring's state gives the mascot inside it: waking is a turn of its own about to start, so it is at work,
 *  as the Running chip counts it; idle rests, asleep while its triggers are paused. */
const FACE: Record<RingStatus, FaceState> = { working: 'working', waking: 'working', needs: 'needs', failed: 'failed', idle: 'waiting' };

/** `mark` stands in for the avatar where there's no member to draw (a harness subagent: its harness's mark). `face`
 *  gives the mascot a state the ring has no word for (a subagent done or stopped). */
export function AgentRing({ member, mark, status, face, size = 32, avatarClassName }: { member?: ChannelMember; mark?: ReactNode; status: RingStatus; face?: FaceState; size?: AvatarSize; avatarClassName?: string }) {
    const ring = 'pointer-events-none absolute -inset-[3px] rounded-full';
    let overlay: ReactNode = null;
    if (status === 'working') {
        overlay = (
            <>
                <span className={cn(ring, 'work-breathe')} style={{ boxShadow: `inset 0 0 0 2px ${ink(0.3)}` }} />
                <span
                    className={cn(ring, 'work-spin')}
                    style={{
                        background: `conic-gradient(from 0deg, transparent 0deg, transparent 180deg, ${ink(0.35)} 230deg, ${INK} 275deg, ${ink(0.35)} 320deg, transparent 360deg)`,
                        WebkitMask: RING_MASK,
                        mask: RING_MASK,
                        animationDuration: '1.8s',
                        filter: `drop-shadow(0 0 2px ${ink(0.5)})`,
                    }}
                />
            </>
        );
    } else if (status === 'needs') overlay = <span className={cn(ring, 'border-2 border-foreground')} />;
    else if (status === 'failed') overlay = <span className={cn(ring, 'border-2 border-red-500')} />;
    else if (status === 'waking')
        overlay = (
            <svg className={cn(ring, 'work-spin')} style={{ animationDuration: '9s' }} viewBox="0 0 40 40" aria-hidden>
                <circle cx="20" cy="20" r="18.5" fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="3 4" strokeLinecap="round" />
            </svg>
        );
    return (
        <span className={cn('relative inline-flex shrink-0', status === 'waking' && 'text-foreground/45')} data-ring={status}>
            <WorkMotion />
            {member ? (
                // Where a ring says the state, the mascot drops its own marks (ticks, red dot) so the two never crowd.
                <MemberAvatar member={member} size={size} className={avatarClassName} state={face ?? (status === 'idle' && member.paused ? 'asleep' : FACE[status])} marks={status === 'idle'} />
            ) : (
                <span className="grid shrink-0 place-items-center rounded-full bg-foreground/[0.06]" style={{ width: size, height: size }}>
                    {mark}
                </span>
            )}
            {overlay}
        </span>
    );
}
