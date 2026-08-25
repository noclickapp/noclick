// Share dialog for the fullscreen agent chat: mints (or fetches) the agent
// node's public capability link (/a/{link_id}), with a prominent copy CTA,
// an active toggle, and a reset-link (rotate) action that kills the old URL.
// Owner-only — the backend rejects non-owners; anyone opening the link chats
// on the owner's credits.

import { useCallback, useEffect, useState } from 'react';
import { Check, Copy, ExternalLink, Link2, Loader2, RotateCcw } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '~/components/ui/dialog';
import { Switch } from '~/components/ui/switch';
import {
  sendEventAsync,
  AgentShareGetOrCreateRequest,
  AgentShareRotateRequest,
  AgentShareSetActiveRequest,
} from '~/lib/socket-sender';
import type { AgentShareLinkResponse } from '~/types/socket-events.generated';

export function AgentShareDialog({
  isOpen,
  onOpenChange,
  workflowId,
  nodeId,
  agentLabel,
}: {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  workflowId: string;
  nodeId: string;
  agentLabel?: string;
}) {
  const [link, setLink] = useState<AgentShareLinkResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [confirmingReset, setConfirmingReset] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!isOpen) {
      setConfirmingReset(false);
      setCopied(false);
      return;
    }
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const resp = (await sendEventAsync(
          AgentShareGetOrCreateRequest.create({ workflow_id: workflowId, node_id: nodeId }),
        )) as AgentShareLinkResponse;
        if (resp.success) setLink(resp);
        else setError(resp.error || 'Failed to create share link');
      } catch {
        setError('Failed to create share link');
      } finally {
        setLoading(false);
      }
    })();
  }, [isOpen, workflowId, nodeId]);

  // Prefer the browser origin so dev links point at the dev server; the
  // backend URL (FRONTEND_URL-based) is the fallback for odd contexts.
  const shareUrl = link?.link_id
    ? typeof window !== 'undefined'
      ? `${window.location.origin}/a/${link.link_id}`
      : link.url ?? ''
    : '';

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  }, [shareUrl]);

  const handleToggleActive = useCallback(async (next: boolean) => {
    setLink(prev => (prev ? { ...prev, is_active: next } : prev));
    try {
      const resp = (await sendEventAsync(
        AgentShareSetActiveRequest.create({ workflow_id: workflowId, node_id: nodeId, is_active: next }),
      )) as AgentShareLinkResponse;
      if (!resp.success) throw new Error(resp.error || 'toggle failed');
      setLink(resp);
    } catch {
      setLink(prev => (prev ? { ...prev, is_active: !next } : prev));
      setError('Failed to update the link');
    }
  }, [workflowId, nodeId]);

  const handleRotate = useCallback(async () => {
    if (!confirmingReset) {
      setConfirmingReset(true);
      return;
    }
    setConfirmingReset(false);
    setLoading(true);
    setError(null);
    try {
      const resp = (await sendEventAsync(
        AgentShareRotateRequest.create({ workflow_id: workflowId, node_id: nodeId }),
      )) as AgentShareLinkResponse;
      if (resp.success) setLink(resp);
      else setError(resp.error || 'Failed to reset the link');
    } catch {
      setError('Failed to reset the link');
    } finally {
      setLoading(false);
    }
  }, [confirmingReset, workflowId, nodeId]);

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent data-testid="agent-share-dialog" className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Share agent</DialogTitle>
        </DialogHeader>

        <p className="text-sm text-muted-foreground leading-relaxed">
          Anyone with this link can chat with{' '}
          <span className="text-foreground">{agentLabel || 'this agent'}</span> — no account
          needed. Usage bills to your account.
        </p>

        {loading && !link ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-5 h-5 animate-spin text-muted-foreground/70 dark:text-zinc-500" />
          </div>
        ) : null}

        {link?.link_id ? (
          <div className="space-y-5">
            {/* Public link + copy CTA. */}
            <div>
              <label htmlFor="agent-share-url-input" className="block text-[11px] uppercase tracking-wider text-muted-foreground/70 dark:text-zinc-500 mb-2">
                Public link
              </label>
              <div className="flex items-stretch gap-2">
                <div className="flex-1 min-w-0 flex items-center gap-2 rounded-xl border border-border bg-background dark:bg-zinc-950 px-3 focus-within:border-foreground/30 transition-colors">
                  <Link2 className="w-4 h-4 text-muted-foreground/60 dark:text-zinc-600 shrink-0" />
                  <input
                    id="agent-share-url-input"
                    readOnly
                    value={shareUrl}
                    data-testid="agent-share-url"
                    onFocus={e => e.currentTarget.select()}
                    className="flex-1 min-w-0 bg-transparent text-sm text-foreground py-2.5 outline-none font-mono"
                  />
                </div>
                <button
                  type="button"
                  onClick={handleCopy}
                  data-testid="agent-share-copy"
                  className="shrink-0 inline-flex items-center gap-1.5 rounded-xl bg-primary text-primary-foreground text-sm font-medium px-4 hover:bg-primary/90 transition-colors"
                >
                  {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                  {copied ? 'Copied' : 'Copy'}
                </button>
                <a
                  href={shareUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  title="Open the public page"
                  aria-label="Open the public page"
                  data-testid="agent-share-open"
                  className="shrink-0 inline-flex items-center justify-center rounded-xl border border-border text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] hover:border-foreground/20 px-3 transition-colors"
                >
                  <ExternalLink className="w-4 h-4" />
                </a>
              </div>
            </div>

            {/* Active toggle in its own card row. */}
            <div className="flex items-center justify-between gap-4 rounded-xl border border-border bg-background/60 dark:bg-zinc-950/60 px-4 py-3">
              <div>
                <div className="text-sm font-medium text-foreground">Link active</div>
                <div className="text-xs text-muted-foreground/70 dark:text-zinc-500 mt-0.5">
                  {link.is_active
                    ? 'Visitors can chat with this agent.'
                    : 'The link is paused — visitors are turned away.'}
                </div>
              </div>
              <Switch
                checked={!!link.is_active}
                onCheckedChange={handleToggleActive}
                data-testid="agent-share-active-toggle"
                aria-label="Link active"
              />
            </div>

            {/* Reset (rotate) footer. */}
            <div className="flex items-center justify-between gap-3 border-t border-border/60 dark:border-zinc-800/60 pt-4">
              <div className="text-xs text-muted-foreground/70 dark:text-zinc-500">
                {confirmingReset
                  ? 'The current link stops working immediately.'
                  : 'Generate a new link and disable the current one.'}
              </div>
              <button
                type="button"
                onClick={handleRotate}
                disabled={loading}
                data-testid="agent-share-rotate"
                className={`shrink-0 inline-flex items-center gap-1.5 text-sm font-medium rounded-lg px-3 py-1.5 border transition-colors disabled:opacity-50 ${
                  confirmingReset
                    ? 'text-red-600 dark:text-red-300 border-red-500/40 dark:border-red-900/60 bg-red-500/10 dark:bg-red-950/40 hover:bg-red-500/20 dark:hover:bg-red-950/60'
                    : 'text-foreground border-border dark:border-zinc-700 bg-foreground/[0.06] hover:bg-foreground/[0.12]'
                }`}
              >
                <RotateCcw className="w-4 h-4" />
                {confirmingReset ? 'Reset link?' : 'Reset link'}
              </button>
            </div>
          </div>
        ) : null}

        {error ? (
          <div data-testid="agent-share-error" className="text-sm text-red-600 dark:text-red-400/90 border border-red-500/30 dark:border-red-900/40 bg-red-500/10 dark:bg-red-950/30 rounded-lg px-3 py-2">
            {error}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
