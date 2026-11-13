// The one rule for what a chat box's round button does now, for every box that has one (the Chat page, Work's
// conversation, an interface block's chat, a shared agent's page): send what's written, join the turn at work (steer),
// go once it ends (queue), stop it, or answer what it asked (submit); and when it can't act yet. Pure, so each box asks
// the same questions instead of keeping its own copy of the rule.

export type PrimaryKind = 'send' | 'steer' | 'queue' | 'stop' | 'submit';

export interface ComposerState {
    /** Something to send: words, or a file or reference ready to go. */
    filled: boolean;
    /** The box can send at all: its conversation is known and the page may write. */
    ready: boolean;
    /** A file is still uploading. */
    uploading?: boolean;
    /** A file failed to upload, in a box that never sends without it. */
    failed?: boolean;
    /** A turn of the agent's runs. */
    working?: boolean;
    /** While a turn runs, what the box can do about it: stop it, have words join it (steer), or have them go once it
     *  ends (queue). A box that can do none waits for the turn to end. */
    canStop?: boolean;
    canSteer?: boolean;
    canQueue?: boolean;
    /** What's in the box can't join a running turn: files go with a message of their own. */
    unsteerable?: boolean;
    /** Its harness asked a question: the button answers it. */
    question?: boolean;
    /** It waits on an approval: words typed decline it, sent at once. */
    approval?: boolean;
    /** What's typed is a command: one of NoClick's own controls runs at once; the harness's runs as a turn of its own. */
    command?: 'control' | 'harness' | null;
    /** ⌘ or Ctrl held: go once the turn ends rather than join it. */
    queueHeld?: boolean;
    /** Written to one of its harness's subagents: words join that subagent's turn, never stop or queue it. */
    scoped?: boolean;
    /** A send is on its way. */
    sending?: boolean;
}

export interface ComposerPrimary {
    kind: PrimaryKind;
    disabled: boolean;
}

function kindOf(s: ComposerState): PrimaryKind {
    if (s.question) return 'submit';
    if (s.scoped) return s.working && s.filled && !s.approval ? 'steer' : 'send';
    if (!s.working || s.command === 'control' || (s.approval && s.filled)) return 'send';
    if (!s.filled) return s.canStop ? 'stop' : 'send';
    if (s.canQueue && (s.command === 'harness' || s.queueHeld || s.unsteerable)) return 'queue';
    return s.canSteer ? 'steer' : 'send';
}

/** What the box's button is now, and whether it can act. */
export function composerPrimary(s: ComposerState): ComposerPrimary {
    const kind = kindOf(s);
    if (kind === 'stop') return { kind, disabled: !s.ready };
    if (kind === 'submit') return { kind, disabled: !s.filled || !!s.sending };
    // A box that can't act on a running turn waits for it to end; one that can't join it with what it holds waits too.
    const waits = !!s.working && kind === 'send' && !s.scoped && !s.approval && s.command !== 'control';
    const blocked = kind === 'steer' && !!s.unsteerable && !s.scoped;
    return { kind, disabled: !s.ready || !s.filled || !!s.uploading || !!s.failed || !!s.sending || waits || blocked };
}
