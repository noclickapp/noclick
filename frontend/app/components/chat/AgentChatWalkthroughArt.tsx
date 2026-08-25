// Animated illustration for the top media tile of the "chat with your agent"
// walkthrough (GuidedTourHighlight), in place of a .webm. It's a faithful
// miniature of the real AgentChatBlock chat surface so the tour previews exactly
// where the user is headed: a pure-black surface, a grey user bubble on the
// right, and the agent's reply as plain light text on the left (no bubble, no
// avatar — as in the real UI) that STREAMS in token-by-token with the real
// transcript's pulsing dot. A short exchange plays out and gracefully loops,
// driven by a phase state + framer-motion (the tooltip is foregrounded while shown).

import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

type Phase = 'idle' | 'ask' | 'think' | 'reply';
const SEQUENCE: ReadonlyArray<readonly [Phase, number]> = [
    ['idle', 500],
    ['ask', 1250],
    ['think', 750],
    ['reply', 3000],
];

const SPRING = { type: 'spring', stiffness: 400, damping: 28 } as const;
const REPLY = 'Sure — here’s a draft you can send.';
const STREAM_MS = 34; // per character, ~1.2s total

export function AgentChatWalkthroughArt() {
    const [phase, setPhase] = useState<Phase>('idle');
    useEffect(() => {
        let timer: ReturnType<typeof setTimeout>;
        let i = 0;
        const run = () => {
            setPhase(SEQUENCE[i][0]);
            timer = setTimeout(() => {
                i = (i + 1) % SEQUENCE.length;
                run();
            }, SEQUENCE[i][1]);
        };
        run();
        return () => clearTimeout(timer);
    }, []);

    // Token-by-token streaming reveal of the agent reply, restarted each loop.
    const [revealed, setRevealed] = useState(0);
    useEffect(() => {
        if (phase !== 'reply') {
            setRevealed(0);
            return;
        }
        let n = 0;
        const iv = setInterval(() => {
            n += 1;
            setRevealed(n);
            if (n >= REPLY.length) clearInterval(iv);
        }, STREAM_MS);
        return () => clearInterval(iv);
    }, [phase]);

    const showAsk = phase !== 'idle';
    const thinking = phase === 'think';
    const replying = phase === 'reply';
    const streaming = replying && revealed < REPLY.length;

    return (
        <div className="absolute inset-0 flex flex-col justify-center gap-3.5 overflow-hidden bg-black px-6">
            {/* soft focal glow — a whisper of depth that lifts as the agent answers */}
            <motion.div
                aria-hidden
                className="pointer-events-none absolute left-1/2 top-1/2 h-52 w-52 -translate-x-1/2 -translate-y-1/2 rounded-full"
                style={{
                    filter: 'blur(48px)',
                    background: 'rgba(255,255,255,0.05)',
                }}
                animate={{
                    opacity: replying ? 1 : 0.55,
                    scale: replying ? 1.12 : 1,
                }}
                transition={{ duration: 0.7, ease: 'easeOut' }}
            />

            {/* user message — grey bubble, right-aligned (matches AgentChatBlock) */}
            <div className="relative z-10 flex justify-end min-h-[1.9rem]">
                <AnimatePresence>
                    {showAsk && (
                        <motion.div
                            key="ask"
                            className="max-w-[80%] rounded-2xl rounded-br-sm bg-zinc-800 px-3.5 py-2 text-[14px] leading-snug text-white"
                            initial={{ opacity: 0, y: 10, scale: 0.95 }}
                            animate={{ opacity: 1, y: 0, scale: 1 }}
                            exit={{
                                opacity: 0,
                                y: -6,
                                transition: { duration: 0.25 },
                            }}
                            transition={SPRING}
                        >
                            Draft a reply to this email
                        </motion.div>
                    )}
                </AnimatePresence>
            </div>

            {/* agent reply — plain light text, left-aligned, streaming with a pulsing dot */}
            <div className="relative z-10 flex justify-start min-h-[2.6rem] text-[14px] leading-relaxed text-zinc-100">
                <AnimatePresence mode="wait">
                    {thinking ? (
                        <motion.span
                            key="think"
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            exit={{ opacity: 0 }}
                        >
                            <PulseDot />
                        </motion.span>
                    ) : replying ? (
                        <motion.span
                            key="reply"
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            exit={{
                                opacity: 0,
                                transition: { duration: 0.25 },
                            }}
                        >
                            {REPLY.slice(0, revealed)}
                            {streaming && (
                                <span className="ml-0.5 align-middle">
                                    <PulseDot />
                                </span>
                            )}
                        </motion.span>
                    ) : (
                        <span key="empty" />
                    )}
                </AnimatePresence>
            </div>
        </div>
    );
}

// A single pulsing dot — the real transcript's streaming/thinking indicator.
function PulseDot() {
    return (
        <motion.span
            className="inline-block h-2 w-2 rounded-full bg-zinc-300 align-middle"
            animate={{ opacity: [0.35, 1, 0.35], scale: [0.8, 1, 0.8] }}
            transition={{ duration: 1, repeat: Infinity, ease: 'easeInOut' }}
        />
    );
}
