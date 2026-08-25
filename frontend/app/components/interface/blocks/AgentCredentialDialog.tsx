// AgentCredentialDialog surfaces the agent's credential form in a centered modal
// popup — opened from the chat error banner's "Add credential" button — so adding
// a key is a prominent, obvious flow instead of a subtle change buried in the
// right settings sidebar. It reuses AgentCredentialsForm unchanged (the same
// component the sidebar renders) so it shows exactly what that form naturally
// shows for the provider — OAuth ("Connect with ChatGPT"), API-key entry, saved
// credentials — with zero duplicated credential logic. It just closes once a
// credential is added so the user returns to the chat and can retry.

import { Dialog, DialogContent, DialogTitle } from '~/components/ui/dialog';
import { AgentCredentialsForm } from '~/components/workflow/AgentCredentialsForm';

interface AgentCredentialDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    /** The agent node's config — drives which provider credential is needed. */
    config: Record<string, unknown>;
    credentialIds: Record<string, string>;
    onCredentialIdsChange: (next: Record<string, string>) => void;
}

export function AgentCredentialDialog({
    open,
    onOpenChange,
    config,
    credentialIds,
    onCredentialIdsChange,
}: AgentCredentialDialogProps) {
    const handleChange = (next: Record<string, string>) => {
        // A credential type that newly gains a non-empty id means one was just
        // created/connected — close the popup so the user returns to the chat and
        // can retry immediately (the pre-flight error clears on credentialIds change).
        const created = Object.keys(next).some(
            (type) => next[type]?.trim() && credentialIds[type] !== next[type],
        );
        onCredentialIdsChange(next);
        if (created) onOpenChange(false);
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent
                data-testid="agent-credential-dialog"
                aria-describedby={undefined}
                // No exit animation: the chat mounts several AgentChatBlock
                // instances that re-render on every stream chunk, which stalls
                // Radix's Presence exit-animation so the content never unmounts.
                // noAnimation makes Radix unmount immediately on close.
                noAnimation
                // No overflow clip / inner scroll: the saved-credential picker is
                // an absolutely-positioned dropdown that a clipping ancestor would
                // cut off. Credential forms are short, so the dialog just sizes to
                // its content and the dropdown can extend freely.
                className="max-w-md p-0 gap-0"
            >
                <div className="flex flex-col">
                    <div className="px-5 py-4 border-b border-foreground/[0.06]">
                        <DialogTitle className="text-base font-semibold text-foreground tracking-tight">
                            Add credential
                        </DialogTitle>
                    </div>
                    <div className="px-5 py-4">
                        <AgentCredentialsForm
                            nodeData={config}
                            credentialIds={credentialIds}
                            onCredentialIdsChange={handleChange}
                        />
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    );
}
