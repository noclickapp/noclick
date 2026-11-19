// `/chat-lab`, in development only: the Chat page over made-up data (src/screens/chat/lab), with no account and no
// network. `?scene=` picks a view (the index lists them all) and `?as=key` shows the chat as it is here, acting as a key
// (the default shows what a signed-in owner sees). A built app answers 404 and carries none of it: the lab is imported
// only where `import.meta.env.DEV` is true.
import { lazy, Suspense } from 'react';
import { data } from 'react-router';
import { NOCLICK_SITE } from '@/screens/console/lib/site';
import type { Route } from './+types/chat-lab';

export const meta: Route.MetaFunction = () => [{ title: 'Chat lab · NoClick' }];

export function loader() {
    if (!import.meta.env.DEV) throw data(null, { status: 404 });
    return null;
}

const ChatLab = import.meta.env.DEV ? lazy(() => import('@/screens/chat/lab/ChatLab')) : null;

export default function ChatLabRoute() {
    if (!ChatLab) return null;
    return (
        <Suspense>
            <ChatLab basePath="/chat-lab" site={NOCLICK_SITE} />
        </Suspense>
    );
}
