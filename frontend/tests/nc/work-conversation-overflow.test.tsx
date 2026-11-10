// An agent's conversation in Work, in the real browser, over a thread of long unbroken text in every kind of row (a URL,
// one-line JSON and base64, inline code, a wide markdown table and code block, a long command and its output, a long
// file path, a long word and a long command in your bubble), laid out at a laptop's width and a phone's: the thread
// never scrolls sideways. A table or code block too wide scrolls inside its own box instead. Nothing real is called:
// the platform client runs over the fixture.
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { AgentConversation } from '~/cloud/components/work/conversation/AgentConversation';
import { overflowHistory } from '~/cloud/components/work/conversation/fixtures/scenes';
import { AGENT_ID, fakeWorkAgent } from '~/cloud/components/work/conversation/fixtures/workAgent';
import { WorkProviders } from '~/cloud/components/work/agents/fixtures/providers';
import { nc } from '~/lib/nc';

async function at(width: number) {
    const fake = fakeWorkAgent({ histories: { main: overflowHistory() } });
    const host = document.createElement('div');
    host.style.cssText = `position:fixed;inset:0 auto auto 0;width:${width}px;height:820px;display:flex;flex-direction:column;z-index:2147483000;background:hsl(var(--background))`;
    document.body.appendChild(host);
    const root = createRoot(host);
    try {
        flushSync(() =>
            root.render(
                <WorkProviders client={fake.client}>
                    <AgentConversation agentId={AGENT_ID} conversation="main" onOpenProfile={() => undefined} onOpenMachine={() => undefined} onOpenConversation={() => undefined} />
                </WorkProviders>
            )
        );
        await nc.wait.until(() => !!host.querySelector('table') && !!host.querySelector('[data-row="user"]'), 10000);
        // Every step opened: its command's output, its diff, its tool call.
        for (const b of host.querySelectorAll<HTMLButtonElement>('[data-step] button[aria-expanded="false"]')) b.click();
        await nc.wait.ms(300);
        const scroller = host.querySelector('table')!.closest<HTMLElement>('.overflow-y-auto')!;
        nc.assert.ok(scroller.scrollWidth <= scroller.clientWidth, `At ${width}px the thread doesn't scroll sideways (${scroller.scrollWidth} wide in ${scroller.clientWidth})`);
        const box = host.querySelector('table')!.parentElement!;
        nc.assert.ok(box.scrollWidth > box.clientWidth && getComputedStyle(box).overflowX === 'auto', 'The wide table scrolls inside its own box');
        const pre = host.querySelector<HTMLElement>('pre')!;
        nc.assert.ok(pre.scrollWidth > pre.clientWidth && getComputedStyle(pre).overflowX === 'auto', 'and so does the wide code block');
    } finally {
        root.unmount();
        host.remove();
    }
}

export default async function () {
    await at(900);
    await at(390);
}
