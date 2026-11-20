// The frame around the signed-in owner's pages (src/screens/shell/AppFrame.tsx): the home, the chat, Work and
// Resources draw inside it, each its own route below. It reads nothing on the server, so moving between them never
// waits on it.
import { Outlet } from 'react-router';
import { AppFrame } from '@/screens/shell/AppFrame';

export const shouldRevalidate = () => false;

export default function Shell() {
    return (
        <AppFrame>
            <Outlet />
        </AppFrame>
    );
}
