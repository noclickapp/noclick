// The Chat page's box: Work's, the one box of every agent session, over NoClick's one session as the page keeps it
// live (useHostedThread). Its "+" adds files and what a message points at; its / offers what NoClick runs here (/loop,
// said in a toast and then shown in the Beside, never drawn as a message; /clear and /resume, confirmed first) and any
// commands its harness reports, $ the skills it reports; Stop and Steer while NoClick works; the coordinator's
// switchers on and under it.
import { useMemo } from 'react';
import { useChatSource, type ChatComposerProps } from './source';
import { pendingRequests, subagentsOf } from '@/lib/agentThread/thread';
import { Composer } from '@/screens/work/conversation/Composer';
import { runLoop } from '@/screens/work/conversation/loops';
import type { Control } from '@/screens/work/conversation/menus';
import { useChatThread } from './thread';

// NoClick's own commands the Chat page runs (the rest open Work's panels, which this page doesn't have).
const CHAT_CONTROLS: readonly Control[] = ['loop', 'clear', 'resume'];

export function ChatComposer({ placeholder, size, putBack, transition, transitionName, className }: ChatComposerProps) {
    const { state, session, sessions } = useChatThread();
    const chat = useChatSource();
    const controls = chat.composerControls;
    const conversation = useMemo(() => (session ? state.agent.conversation(session) : null), [state.agent, session]);
    const subagents = useMemo(() => subagentsOf(state.thread), [state.thread]);
    return (
        <Composer
            className={className}
            transitionName={transitionName}
            size={size}
            placeholder={placeholder}
            focusOnReady
            putBack={putBack ?? undefined}
            agentName="NoClick"
            harnessLabel="NoClick"
            working={state.working}
            ready={state.ready}
            commands={state.commands}
            controls={CHAT_CONTROLS}
            queued={state.queued}
            requests={pendingRequests(state.thread)}
            subagents={subagents}
            onShowSubagents={() => undefined}
            listFiles={chat.listFiles}
            session={sessions.menu}
            model={controls?.model ?? null}
            footer={controls?.footer}
            ask={controls?.ask ?? null}
            onControl={(control, args = '') => {
                if (control === 'loop' && conversation) void runLoop(conversation, args, 'NoClick');
                else if (control === 'clear') sessions.clear();
                else if (control === 'resume') sessions.resume();
            }}
            drawer={null}
            // The first message moves the box to the thread's foot: its send runs inside the page's transition.
            onSend={(input) => new Promise<boolean>((resolve) => transition(() => void state.send(input).then(resolve)))}
            onStop={() => void state.stop()}
            onUnqueue={state.unqueue}
            onAnswer={(request, decision, options) => void state.answer(request, decision, options)}
            upload={(file) => state.agent.upload(file)}
        />
    );
}
