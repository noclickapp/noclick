// The Chat page's slots: the places in it a host may fill (src/slots.ts), each with what stands there otherwise. A
// reply's Markdown and a texted message's file are Work's (`work.reply.markdown`, `work.message.file`), an app's mark
// the shared `connection.mark`, an agent's face the channels layer's.
import type { ComponentType, ReactNode } from 'react';
import { slot } from '@/slots';
import type { WorkflowSetupRef } from '@/lib/agentThread/thread';
import type { JsonObject } from '@/lib/toolCalls';
import type { OwnerAnswer, OwnerPick, OwnerQuestion } from '@/screens/humans/useHumanRequest';
import type { TextApp } from '@/ui/AppTile';
import type { HeldApproval } from './atWork/types';
import type { CanvasOf, NewestCard } from './cards/canvases';
import type { CardEntry, ConnectAskOf, ToolCard } from './cards/toolCardRegistry';
import {
    AnswerOnNoClick,
    ConnectAccountLink,
    ConnectAsksLinks,
    ConnectPlansLinks,
    OutOfFundsLink,
    PickInWords,
    StepOnNoClick,
    WorkingDot,
    noclickPlaces,
    textOnNoClick,
    emailOnNoClick,
} from './slotStandards';

// ── a turn's cards ─────────────────────────────────────────────────────────

/** What a host adds to the chat's own cards. */
export interface MoreCards {
    /** Cards tried ahead of every other (a refused call's way past its refusal). */
    ahead: readonly CardEntry[];
    /** Cards for a chat's own tools, by the tool's name, ahead of every card matched by what a call answered. */
    named: Readonly<Record<string, ToolCard>>;
    /** Cards matched by what a call answered, tried before the chat's own. */
    cards: readonly CardEntry[];
    /** More of what a call asks the owner to connect, joining the turn's one connect card. */
    asks: readonly ConnectAskOf[];
    /** More of what a call's card draws on its canvas, tried before the chat's own. */
    canvases: readonly CanvasOf[];
}

/** Under a turn: cards of the host's own, beside the chat's (table.tsx). Nothing more stands there. */
export const MORE_CARDS = slot<MoreCards>('chat.cards.more', { ahead: [], named: {}, cards: [], asks: [], canvases: [] });

/** How a build at work marks itself beside "Building" in its card's header. The standard is a live dot. */
export const WORKING_MARK = slot<() => ReactNode>('chat.working', WorkingDot);

export interface BuildQuestionProps {
    /** The question's id, and the workflow it's building. */
    askId: string;
    workflowId: string;
    /** The question as the build's operation carries it (`title`, `inputs`, `answer_url`). */
    question: JsonObject;
    /** The question sent (its id), or back on the card when it was refused (null). */
    onSending: (askId: string | null) => void;
}

/** Under a build's card, the question it waits on. The standard says what it asks and opens its page on NoClick to
 *  answer it there. */
export const BUILD_QUESTION = slot<ComponentType<BuildQuestionProps>>('chat.build.question', AnswerOnNoClick);

export interface QuestionPickProps {
    /** The field the agent asks the owner to pick from their own account (a repository, a team, a channel). */
    pick: OwnerPick;
    question: string;
    onAnswer: (choice: string) => void;
}

/** Under an agent's question about the owner's own account: how they pick. The standard takes the answer in words. */
export const QUESTION_PICK = slot<ComponentType<QuestionPickProps>>('chat.question.pick', PickInWords);

export interface QuestionStepProps {
    /** A question that fills in a workflow step: which connection it uses (`connect`), or a secret's values
     *  (`secret`), as `/v1/humans/requests/{id}` reads it for the signed-in owner. */
    question: OwnerQuestion;
    /** Answers it: `{ connection }` (a connection's ref) or `{ secret_values }`. */
    onAnswer: (answer: OwnerAnswer) => void;
    disabled: boolean;
}

/** Under a question that fills in a workflow step (the builder's: the step's account, an agent step's secret): how
 *  the owner answers it. The standard opens its page on NoClick. */
export const QUESTION_STEP = slot<ComponentType<QuestionStepProps>>('chat.question.step', StepOnNoClick);

/** The card under a note that sets up an automation picked on another page (its setup); `newer` is a newer card in the
 *  thread about the same automation, which folds it. Nothing stands there: the note's words do. (An agent an agents
 *  page made draws the chat's own card.) */
export const SETUP_CARD = slot<ComponentType<{ setup: WorkflowSetupRef; newer?: NewestCard }> | null>('chat.note.setup', null);

/** Under a reply NoClick turned down for want of funds: how to get going again. The standard says so and links to
 *  adding funds on NoClick. */
export const OUT_OF_FUNDS = slot<ComponentType<{ refusal: Record<string, unknown> }>>('chat.outOfFunds', OutOfFundsLink);

// ── connecting an account a card asks for ─────────────────────────────────

export interface ConnectAccountProps {
    /** The account's credential type, its link's page, what it's for, and when it was asked. */
    type: string;
    url: string;
    message?: string;
    startedAt: number;
    /** The operation the link waits on, which settles once it's connected. */
    operationId?: string;
}

export interface ConnectLinkParts {
    /** The turn's asks to connect, on one card (drawn under the first that asked). */
    Asks: ToolCard;
    /** One account to connect, on a card of its own. */
    Account: ComponentType<ConnectAccountProps>;
    /** An AI company's account for an agent's model, offered as its plan's sign-in where it has one. */
    Plans: ToolCard;
}

/** Connecting an account a card asks for. The standard opens the link's page on NoClick in a new tab, and the card
 *  says connected once the operation the link waits on settles. */
export const CONNECT_LINK = slot<ConnectLinkParts>('chat.connect.link', { Asks: ConnectAsksLinks, Account: ConnectAccountLink, Plans: ConnectPlansLinks });

// ── the Beside ──────────────────────────────────────────────────────────────

export interface ApprovalReviewProps {
    open: boolean;
    /** The calls held for the owner's yes, and the one it opens on. */
    approvals: HeldApproval[];
    openOn: string | null;
    onClose: () => void;
}

/** Reviewing the calls held for the owner's yes from the Beside, over the chat. Nothing stands there: each opens its
 *  page on NoClick. */
export const APPROVAL_REVIEW = slot<ComponentType<ApprovalReviewProps> | null>('chat.approval', null);

// ── the Connect menu ────────────────────────────────────────────────────────

/** Texting NoClick, as the Connect menu reads it while it's open (`open`). */
export interface Texting {
    /** The apps to offer, in the order to offer them. */
    apps: readonly TextApp[];
    /** What opens the app on a phone, there; null while it isn't ready. */
    hrefFor: (app: TextApp) => string | null;
    /** The app picked from the menu. */
    pick: (app: TextApp) => void;
}

export interface ConnectText {
    useTexting: (open: boolean) => Texting;
    /** The app's own view under the menu's back row. */
    View: ComponentType<{ app: TextApp; texting: Texting }>;
}

/** The Connect menu's WhatsApp and iMessage. The standard offers NoClick's own lines (`Human.owner().reach()`) to text
 *  from the owner's linked phone, and, with none linked, sends them to link one on NoClick. */
export const CONNECT_TEXT = slot<ConnectText>('chat.connect.text', textOnNoClick);

/** NoClick's address, as the Connect menu's email row reads it: undefined until read, null where it has none. */
export interface Mailbox {
    address: string | null;
    paused: boolean;
}

export interface ConnectEmail {
    useMailbox: () => Mailbox | undefined;
    /** Read it again (as the menu opens: it may have changed elsewhere). */
    refresh: () => void;
    /** Its view under the menu's back row: `ask` drafts a message to NoClick; `escape` lets Escape end an edit before
     *  it leaves the view. */
    View: ComponentType<{ ownerEmail: string | null; ask: (text: string) => void; escape: { current: (() => boolean) | null } }>;
}

/** The Connect menu's email. The standard reads NoClick's inbox and switches its mail on or off; claiming or renaming
 *  its address is asking NoClick. */
export const CONNECT_EMAIL = slot<ConnectEmail>('chat.connect.email', emailOnNoClick);

// ── where the app's pages are ───────────────────────────────────────────────

/** The app's own pages a card goes to, each with its own place (Resources' `{ kind, resource, view, sha }`). */
export type ChatPage = 'resources';

export interface ChatPlaces {
    href: (page: ChatPage, params: Record<string, string | null>) => string;
    go: (page: ChatPage, params: Record<string, string | null>) => void;
    /** Opens an automation on its canvas. */
    openWorkflow: (workflowId: string, name: string) => void;
}

/** Where a card's links go. The standard is this app's Resources at `/resources`, and an automation's canvas on
 *  NoClick, in a new tab. */
export const CHAT_PLACES = slot<ChatPlaces>('chat.places', noclickPlaces);
