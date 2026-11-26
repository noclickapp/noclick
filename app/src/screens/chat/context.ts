// What whoever shows the Chat page hands it besides its client (ConsoleProviders gives that, with `site`, `actsAs` and
// who is signed in): NoClick's MCP server, and what only a host that signs its owner in can do (finish a setup started
// on another page). A missing value hides what needs it. Where the app's pages are, which the chat's cards link to
// wherever they're drawn, is a slot (`chat.places`). The page never says the owner is watching it: a key isn't the
// owner, and NoClick would stop texting them what it shows.
import { createContext, useContext, type ReactNode } from 'react';
import type { SetupArrival } from './source';

export interface ChatArrival {
    /** What's being set up from another page, until its note is in the thread: its name, and once it's made what its
     *  setup is about (`setupSubject`: its automation's id, or `agent:<id>`). */
    arriving: { name: string; subject?: string | null } | null;
    /** What the arrival draws beside the page (a refusal it met); nothing otherwise. */
    aside?: ReactNode;
}

export interface ChatContextValue {
    /** NoClick's MCP server, which the Connect menu's setup guides name: its address and one line under their title.
     *  Absent: NoClick's own (`MCP_URL`). */
    mcp?: { url: string; intro: string };
    /** An automation picked on another page and finished here: what is being set up, as `arrive` puts its note in the
     *  thread. Absent: nothing arrives. */
    useArrival?: (conversationId: string | null, arrive: (arrival: SetupArrival) => Promise<void>) => ChatArrival;
}

export const ChatContext = createContext<ChatContextValue>({});

export function useChatContext(): ChatContextValue {
    return useContext(ChatContext);
}
