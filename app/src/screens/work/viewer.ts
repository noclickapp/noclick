// Who is looking at Work: the account itself in its own spaces, or, in a space joined from another account, that
// account's user the signed-in person is there (whose id their messages carry as author). Views tell "you" apart
// from everyone else by it: your bubbles, your reactions, "You" in a list.
import { createContext, useContext } from 'react';

export interface WorkViewer {
    /** `account` in your own spaces (its posts are yours); `user` in a space you joined. */
    type: 'account' | 'user';
    /** Your user id in the joined space's account; null for the account. */
    id: string | null;
    name: string | null;
}

export const WorkViewerContext = createContext<WorkViewer | null>(null);

export function useWorkViewer(): WorkViewer {
    const viewer = useContext(WorkViewerContext);
    if (!viewer) throw new Error('Work views render inside WorkViewerContext.');
    return viewer;
}

/** Whether an author `{type, id}` is the viewer. */
export const isViewer = (viewer: WorkViewer, author: { type: string; id: string | null }) => author.type === viewer.type && (viewer.type === 'account' ? !author.id : author.id === viewer.id);

/** Whether the person reading (Work's viewer) wrote a message: one this page sent, or one whose author is them.
 *  Someone it was handed off to, or another agent, never is. */
export function wroteIt(author: { type: string; id: string | null; name?: string } | null, viewer: WorkViewer): boolean {
    if (!author) return true;
    if (author.type === 'person' || author.type === 'agent') return false;
    return isViewer(viewer, author);
}
