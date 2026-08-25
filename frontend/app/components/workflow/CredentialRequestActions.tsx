// Reusable "ask someone else for a credential" actions: an email-request
// dialog plus a copy-shareable-link button, both targeting a single
// credential_type. Extracted from NodeCredentials so the AI-agent credential
// form (which renders its own custom credential UI) can offer the same flow.

import { useState, useCallback } from 'react';
import { Check, Send, Loader2, Link2 } from 'lucide-react';
import { toast } from 'sonner';
import { sendEventAsync } from '~/lib/socket-sender';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from '~/components/ui/dialog';
import { Button } from '~/components/ui/button';
import { Input } from '~/components/ui/input';

interface CredentialRequestActionsProps {
    /** The credential_type to request (e.g. 'apollo_api_key', 'agent_anthropic'). */
    credentialType: string;
}

export function CredentialRequestActions({
    credentialType,
}: CredentialRequestActionsProps) {
    const [dialogOpen, setDialogOpen] = useState(false);
    const [requestEmail, setRequestEmail] = useState('');
    const [requestMessage, setRequestMessage] = useState('');
    const [requestLoading, setRequestLoading] = useState(false);
    const [requestSuccess, setRequestSuccess] = useState(false);
    const [copyLinkLoading, setCopyLinkLoading] = useState(false);
    const [copyLinkCopied, setCopyLinkCopied] = useState(false);

    // Create a link-mode credential request (no email) and copy its provision
    // URL, so the user can hand it off however they like (Slack, DM, etc.).
    const handleCopyRequestLink = useCallback(async () => {
        setCopyLinkLoading(true);
        try {
            const response = (await sendEventAsync({
                event_name: 'credential:request:create',
                request_id: `cred-req-link-${Date.now()}`,
                credential_type: credentialType,
                frontend_url: window.location.origin,
            } as any)) as any;
            if (response?.provide_url) {
                await navigator.clipboard.writeText(response.provide_url);
                setCopyLinkCopied(true);
                toast.success(
                    'Request link copied — anyone with it can provide this credential'
                );
                setTimeout(() => setCopyLinkCopied(false), 2000);
            } else {
                toast.error('Failed to create request link');
            }
        } catch (err) {
            console.error('Failed to copy credential request link:', err);
            toast.error('Failed to copy request link');
        } finally {
            setCopyLinkLoading(false);
        }
    }, [credentialType]);

    const openDialog = useCallback(() => {
        setRequestEmail('');
        setRequestMessage('');
        setRequestSuccess(false);
        setDialogOpen(true);
    }, []);

    return (
        <>
            <div className="flex items-center gap-3 max-w-md pt-1">
                <div className="flex-1 border-t border-border" />
                <span className="text-[10px] text-muted-foreground/60 dark:text-zinc-600 uppercase tracking-wider">
                    or
                </span>
                <div className="flex-1 border-t border-border" />
            </div>
            <div className="flex items-center gap-2 max-w-md">
                <button
                    onClick={openDialog}
                    className="flex-1 flex items-center justify-center gap-2 px-3 py-2 text-xs text-muted-foreground hover:text-foreground/80 bg-card dark:bg-zinc-900/50 hover:bg-accent dark:hover:bg-zinc-900 border border-border hover:border-foreground/20 rounded-lg transition-all"
                >
                    <Send className="h-3.5 w-3.5" />
                    Request via email
                </button>
                <button
                    onClick={handleCopyRequestLink}
                    disabled={copyLinkLoading}
                    title="Create a shareable link and copy it to your clipboard"
                    className="flex-1 flex items-center justify-center gap-2 px-3 py-2 text-xs text-muted-foreground hover:text-foreground/80 bg-card dark:bg-zinc-900/50 hover:bg-accent dark:hover:bg-zinc-900 border border-border hover:border-foreground/20 rounded-lg transition-all disabled:opacity-40"
                >
                    {copyLinkLoading ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : copyLinkCopied ? (
                        <Check className="h-3.5 w-3.5 text-green-600 dark:text-green-400" />
                    ) : (
                        <Link2 className="h-3.5 w-3.5" />
                    )}
                    {copyLinkCopied ? 'Link copied' : 'Copy request link'}
                </button>
            </div>

            <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
                <DialogContent className="bg-sunken border-border text-foreground max-w-md p-6">
                    <DialogHeader className="pb-2">
                        <DialogTitle className="text-xl text-foreground flex items-center gap-2">
                            <Send className="h-5 w-5" />
                            Request Credential
                        </DialogTitle>
                        <div className="text-sm text-muted-foreground pt-1.5">
                            Send a request via email. They can provide it
                            without a NoClick account.
                        </div>
                    </DialogHeader>

                    {requestSuccess ? (
                        <div className="text-center py-6 space-y-3">
                            <div className="w-12 h-12 bg-green-500/20 rounded-full flex items-center justify-center mx-auto">
                                <Check className="w-6 h-6 text-green-500" />
                            </div>
                            <div>
                                <p className="text-sm text-foreground/90">
                                    Request sent to{' '}
                                    <span className="text-foreground font-medium">
                                        {requestEmail}
                                    </span>
                                </p>
                                <p className="text-xs text-muted-foreground/70 dark:text-zinc-500 mt-1">
                                    They'll receive an email with a link to
                                    provide the credential.
                                </p>
                            </div>
                            <div className="pt-2">
                                <Button
                                    variant="outline"
                                    onClick={() => setDialogOpen(false)}
                                    className="h-10 bg-transparent text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] border border-border hover:border-foreground/20 rounded-md"
                                >
                                    Done
                                </Button>
                            </div>
                        </div>
                    ) : (
                        <div className="space-y-4">
                            <div className="space-y-3">
                                <div className="space-y-1.5">
                                    <label className="text-xs text-muted-foreground">
                                        Email address
                                    </label>
                                    <Input
                                        type="email"
                                        value={requestEmail}
                                        onChange={(e) =>
                                            setRequestEmail(e.target.value)
                                        }
                                        placeholder="colleague@company.com"
                                        className="bg-card border-input dark:border-zinc-700 text-foreground text-sm placeholder:text-[hsl(var(--placeholder))]"
                                        autoFocus
                                    />
                                </div>
                                <div className="space-y-1.5">
                                    <label className="text-xs text-muted-foreground">
                                        Message (optional)
                                    </label>
                                    <textarea
                                        value={requestMessage}
                                        onChange={(e) =>
                                            setRequestMessage(e.target.value)
                                        }
                                        placeholder="e.g., Need your credentials for the marketing workflow"
                                        rows={2}
                                        className="flex w-full rounded-md border border-input dark:border-zinc-700 bg-card px-3 py-2 text-sm text-foreground placeholder:text-[hsl(var(--placeholder))] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background resize-none"
                                    />
                                </div>
                            </div>

                            <div className="flex justify-end gap-2 pt-2">
                                <Button
                                    variant="outline"
                                    onClick={() => setDialogOpen(false)}
                                    className="h-10 bg-transparent text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] border border-border hover:border-foreground/20 rounded-md"
                                >
                                    Cancel
                                </Button>
                                <Button
                                    onClick={async () => {
                                        if (!requestEmail.trim()) return;
                                        setRequestLoading(true);
                                        try {
                                            const response =
                                                (await sendEventAsync({
                                                    event_name:
                                                        'credential:request:create',
                                                    request_id: `cred-req-${Date.now()}`,
                                                    target_email:
                                                        requestEmail.trim(),
                                                    credential_type:
                                                        credentialType,
                                                    message:
                                                        requestMessage.trim() ||
                                                        undefined,
                                                    frontend_url:
                                                        window.location.origin,
                                                } as any)) as any;
                                            if (response?.success) {
                                                setRequestSuccess(true);
                                            }
                                        } finally {
                                            setRequestLoading(false);
                                        }
                                    }}
                                    disabled={
                                        !requestEmail.trim() || requestLoading
                                    }
                                    className="h-10 bg-primary hover:bg-primary text-primary-foreground font-medium rounded-md border-0 shadow-[0_2.5px_0_0_#a0a0a0] hover:shadow-[0_1px_0_0_#a0a0a0] hover:translate-y-[1.5px] active:shadow-none active:translate-y-[2.5px] transition-all duration-100 disabled:opacity-40"
                                >
                                    {requestLoading ? (
                                        <Loader2 className="h-4 w-4 animate-spin" />
                                    ) : (
                                        <>
                                            <Send className="h-3.5 w-3.5 mr-1.5" />
                                            Send Request
                                        </>
                                    )}
                                </Button>
                            </div>
                        </div>
                    )}
                </DialogContent>
            </Dialog>
        </>
    );
}
