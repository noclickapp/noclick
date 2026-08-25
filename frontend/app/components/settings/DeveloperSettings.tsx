// API key management for the NoClick SDK.
// Lets users create, view, copy, and revoke API keys for external app access.

import { useState, useEffect, useCallback } from 'react';
import { Copy, Check, Trash2, Plus, Shield, Eye, EyeOff, ChevronDown, ChevronRight, Globe, Lock, Search, Workflow, ExternalLink } from 'lucide-react';
import { cn } from '~/lib/utils';
import { sendEventAsync } from '~/lib/socket-sender';
import { Popover, PopoverContent, PopoverTrigger } from '~/components/ui/popover';
import { fuzzyFilter } from '~/utils/fuzzySearch';
import { isLocalEdition } from '~/lib/edition';

// Backend API base URL
const API_BASE = import.meta.env.VITE_API_URL || '';

// Both SDKs default to the hosted API (see lib/hostedDefaults), so a copied
// snippet on a self-hosted instance would talk to the hosted service. Spell the
// URL out there; on the hosted service the default is already right, so don't.
const SDK_URL_ARG = isLocalEdition() && API_BASE ? `, url: '${API_BASE}'` : '';
const SDK_URL_ARG_PY = isLocalEdition() && API_BASE ? `, url='${API_BASE}'` : '';

interface APIKey {
  id: string;
  name: string;
  key_prefix: string;
  workflow_id: string | null;
  permissions: string[];
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
}

interface NewKeyResponse extends APIKey {
  raw_key: string;
}

interface WorkflowOption {
  id: string;
  name: string;
}

// --- Workflow scope dropdown (same pattern as Feed's WorkflowFilterDropdown) ---

function ScopeDropdown({ value, workflows, onChange }: {
  value: string;
  workflows: WorkflowOption[];
  onChange: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const selected = value ? workflows.find(w => w.id === value) : null;

  const filtered = fuzzyFilter(workflows, search, w => [
    { text: w.name.toLowerCase(), weight: 1, fuzzy: true },
  ]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button className="h-9 px-3 rounded-lg text-xs font-medium border border-input dark:border-white/[0.08] bg-background/40 text-muted-foreground hover:text-foreground/80 hover:border-muted-foreground/30 dark:hover:border-white/[0.12] transition-colors flex items-center gap-1.5 max-w-[220px] w-full">
          {selected ? <Lock className="w-3.5 h-3.5 flex-shrink-0 text-indigo-600 dark:text-indigo-400" /> : <Globe className="w-3.5 h-3.5 flex-shrink-0" />}
          <span className="truncate flex-1 text-left">{selected ? selected.name : 'All workflows'}</span>
          <ChevronDown className="w-3 h-3 flex-shrink-0 text-muted-foreground/70 dark:text-zinc-600" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-[220px] p-0 bg-popover border-border dark:border-white/[0.08] shadow-2xl rounded-lg overflow-hidden"
      >
        <div className="p-1.5">
          <div className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-foreground/[0.04]">
            <Search className="w-3 h-3 text-muted-foreground/70 dark:text-zinc-600 flex-shrink-0" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search workflows..."
              className="w-full bg-transparent text-xs text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none"
              autoFocus
            />
          </div>
        </div>
        <div className="max-h-[240px] overflow-y-auto scrollbar-subtle py-1">
          <button
            onClick={() => { onChange(''); setOpen(false); setSearch(''); }}
            className={cn(
              'w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors rounded-sm mx-auto',
              !value ? 'text-foreground' : 'text-muted-foreground dark:text-zinc-500 hover:text-foreground/80'
            )}
          >
            <Globe className="w-3 h-3 flex-shrink-0" />
            All workflows
            {!value && <Check className="w-3 h-3 ml-auto text-muted-foreground dark:text-zinc-500" />}
          </button>
          <div className="h-px bg-foreground/[0.04] mx-2 my-1" />
          {filtered.map(w => (
            <button
              key={w.id}
              onClick={() => { onChange(w.id); setOpen(false); setSearch(''); }}
              className={cn(
                'w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors rounded-sm',
                value === w.id ? 'text-foreground' : 'text-muted-foreground dark:text-zinc-500 hover:text-foreground/80'
              )}
            >
              <Workflow className="w-3 h-3 flex-shrink-0" />
              <span className="truncate">{w.name}</span>
              {value === w.id && <Check className="w-3 h-3 ml-auto flex-shrink-0 text-muted-foreground dark:text-zinc-500" />}
            </button>
          ))}
          {filtered.length === 0 && (
            <div className="px-3 py-3 text-[0.6875rem] text-muted-foreground/70 dark:text-zinc-600 text-center">No matches</div>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

// --- Main component ---

export function DeveloperSettings() {
  const [keys, setKeys] = useState<APIKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newKeyName, setNewKeyName] = useState('');
  const [newKeyWorkflow, setNewKeyWorkflow] = useState<string>('');
  const [newKeyRaw, setNewKeyRaw] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [showRevoked, setShowRevoked] = useState(false);
  const [showQuickstart, setShowQuickstart] = useState(false);
  const [workflows, setWorkflows] = useState<WorkflowOption[]>([]);

  const fetchKeys = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/keys`, { credentials: 'include' });
      if (resp.ok) setKeys(await resp.json());
    } catch (e) {
      console.error('Failed to fetch API keys:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchWorkflows = useCallback(async () => {
    try {
      const resp = await sendEventAsync({
        event_name: 'workflow:list' as any,
        request_id: `wf-list-${Date.now()}`,
      });
      setWorkflows(((resp as any)?.workflows || []).map((w: any) => ({
        id: w.id, name: w.name || 'Untitled',
      })));
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { fetchKeys(); fetchWorkflows(); }, [fetchKeys, fetchWorkflows]);

  const handleCreate = async () => {
    if (!newKeyName.trim()) return;
    setCreating(true);
    try {
      const resp = await fetch(`${API_BASE}/api/keys`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          name: newKeyName.trim(),
          permissions: ['read', 'execute', 'write'],
          workflow_id: newKeyWorkflow || null,
        }),
      });
      if (resp.ok) {
        const data: NewKeyResponse = await resp.json();
        setNewKeyRaw(data.raw_key);
        setNewKeyName('');
        setNewKeyWorkflow('');
        await fetchKeys();
      }
    } catch (e) {
      console.error('Failed to create API key:', e);
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (keyId: string) => {
    try {
      const resp = await fetch(`${API_BASE}/api/keys/${keyId}`, { method: 'DELETE', credentials: 'include' });
      if (resp.ok) await fetchKeys();
    } catch (e) {
      console.error('Failed to revoke API key:', e);
    }
  };

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Filter out auto-generated keys from publishing (name starts with "Published:")
  const userKeys = keys.filter(k => !k.name.startsWith('Published:'));
  const activeKeys = userKeys.filter(k => !k.revoked_at);
  const revokedKeys = userKeys.filter(k => !!k.revoked_at);
  const workflowName = (id: string | null) => workflows.find(w => w.id === id)?.name;

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-lg font-semibold text-foreground">Developer</h2>
        <p className="text-sm text-muted-foreground dark:text-white/40 mt-1">
          API keys for connecting external apps via the NoClick SDK.
        </p>
        <div className="flex gap-2 mt-3">
          <a href="https://docs.noclick.com/sdk/typescript" target="_blank" rel="noopener"
            className="inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium bg-card dark:bg-foreground/[0.05] border border-border dark:border-white/[0.08] hover:bg-muted dark:hover:bg-foreground/[0.08] hover:border-muted-foreground/30 dark:hover:border-white/[0.12] text-foreground/80 rounded-lg transition-colors">
            <ExternalLink className="w-3.5 h-3.5" />
            TypeScript SDK
          </a>
          <a href="https://docs.noclick.com/sdk/python" target="_blank" rel="noopener"
            className="inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium bg-card dark:bg-foreground/[0.05] border border-border dark:border-white/[0.08] hover:bg-muted dark:hover:bg-foreground/[0.08] hover:border-muted-foreground/30 dark:hover:border-white/[0.12] text-foreground/80 rounded-lg transition-colors">
            <ExternalLink className="w-3.5 h-3.5" />
            Python SDK
          </a>
          <a href="https://docs.noclick.com/sdk/api-reference" target="_blank" rel="noopener"
            className="inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium bg-card dark:bg-foreground/[0.05] border border-border dark:border-white/[0.08] hover:bg-muted dark:hover:bg-foreground/[0.08] hover:border-muted-foreground/30 dark:hover:border-white/[0.12] text-foreground/80 rounded-lg transition-colors">
            <ExternalLink className="w-3.5 h-3.5" />
            API Reference
          </a>
        </div>
      </div>

      {/* New key reveal banner */}
      {newKeyRaw && (
        <div className="mb-6 p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-xl">
          <div className="flex items-start gap-3">
            <Shield className="w-5 h-5 text-emerald-600 dark:text-emerald-400 mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-emerald-700 dark:text-emerald-300">API key created</p>
              <p className="text-xs text-emerald-700/70 dark:text-emerald-400/60 mt-0.5 mb-2">
                Copy this key now — it won't be shown again.
              </p>
              <div className="flex items-center gap-2">
                <code className="flex-1 text-xs font-mono text-emerald-800 dark:text-emerald-200 bg-background/50 dark:bg-black/30 px-3 py-2 rounded-lg break-all select-all">
                  {newKeyRaw}
                </code>
                <button
                  onClick={() => handleCopy(newKeyRaw)}
                  className="shrink-0 p-2 text-emerald-600 hover:text-emerald-700 dark:text-emerald-400 dark:hover:text-emerald-300 hover:bg-emerald-500/15 rounded-lg transition-colors"
                >
                  {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                </button>
              </div>
            </div>
            <button onClick={() => setNewKeyRaw(null)} className="text-emerald-600 hover:text-emerald-700 dark:hover:text-emerald-400 text-xs">
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Create new key */}
      <div className="mb-6 p-4 bg-card dark:bg-foreground/[0.03] border border-border dark:border-white/[0.06] rounded-xl">
        <div className="flex items-end gap-3">
          <div className="flex-1">
            <label className="block text-xs font-medium text-muted-foreground dark:text-white/50 mb-1.5">Key Name</label>
            <input
              value={newKeyName}
              onChange={e => setNewKeyName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleCreate()}
              placeholder="e.g. My Dashboard App"
              className="w-full h-9 px-3 text-sm bg-background/40 border border-input dark:border-white/[0.08] rounded-lg text-foreground placeholder:text-[hsl(var(--placeholder))] outline-none focus:border-muted-foreground/40 dark:focus:border-white/20"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-muted-foreground dark:text-white/50 mb-1.5">Scope</label>
            <ScopeDropdown value={newKeyWorkflow} workflows={workflows} onChange={setNewKeyWorkflow} />
          </div>
          <button
            onClick={handleCreate}
            disabled={creating || !newKeyName.trim()}
            className="flex items-center gap-2 h-9 px-4 text-sm font-medium bg-primary text-primary-foreground rounded-lg hover:bg-foreground/90 disabled:opacity-40 transition-colors"
          >
            <Plus className="w-4 h-4" />
            Create
          </button>
        </div>
      </div>

      {/* Quickstart — collapsible */}
      <button
        onClick={() => setShowQuickstart(!showQuickstart)}
        className="flex items-center gap-2 text-xs text-muted-foreground/70 dark:text-white/30 hover:text-muted-foreground dark:hover:text-white/50 mb-4 transition-colors"
      >
        {showQuickstart ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
        Quick start
      </button>
      {showQuickstart && (
        <div className="mb-6 p-4 bg-card dark:bg-foreground/[0.02] border border-border dark:border-white/[0.04] rounded-xl">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <p className="text-xs text-muted-foreground/70 dark:text-white/30 mb-1">TypeScript</p>
              <code className="block text-[0.6875rem] font-mono text-muted-foreground dark:text-white/50 bg-background/50 dark:bg-black/30 px-3 py-2 rounded-lg whitespace-pre">{`npm install noclick socket.io-client
import { init } from 'noclick';
await init({ apiKey: 'nk_live_...'${SDK_URL_ARG} });`}</code>
            </div>
            <div>
              <p className="text-xs text-muted-foreground/70 dark:text-white/30 mb-1">Python</p>
              <code className="block text-[0.6875rem] font-mono text-muted-foreground dark:text-white/50 bg-background/50 dark:bg-black/30 px-3 py-2 rounded-lg whitespace-pre">{`pip install noclick
import noclick
sdk = noclick.Client(api_key='nk_live_...'${SDK_URL_ARG_PY})
await sdk.connect()`}</code>
            </div>
          </div>
        </div>
      )}

      {/* Active keys */}
      {loading ? (
        <div className="text-sm text-muted-foreground/70 dark:text-white/30 py-8 text-center">Loading...</div>
      ) : activeKeys.length === 0 && !newKeyRaw ? (
        <div className="text-sm text-muted-foreground/70 dark:text-white/30 py-8 text-center">
          No API keys yet. Create one above to get started.
        </div>
      ) : (
        <div className="space-y-2">
          {activeKeys.map(key => (
            <div key={key.id} className="flex items-center gap-4 px-4 py-3 bg-card dark:bg-foreground/[0.03] border border-border dark:border-white/[0.06] rounded-xl">
              <Shield className="w-4 h-4 text-muted-foreground/70 dark:text-white/30 shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-foreground">{key.name}</span>
                  <code className="text-xs font-mono text-muted-foreground/70 dark:text-white/30">{key.key_prefix}...</code>
                </div>
                <div className="flex items-center gap-3 mt-0.5">
                  <span className="text-xs text-muted-foreground/50 dark:text-white/20">
                    Created {new Date(key.created_at).toLocaleDateString()}
                  </span>
                  {key.last_used_at && (
                    <span className="text-xs text-muted-foreground/50 dark:text-white/20">
                      Last used {new Date(key.last_used_at).toLocaleDateString()}
                    </span>
                  )}
                  {key.workflow_id ? (
                    <span className="inline-flex items-center gap-1 text-xs text-indigo-600/70 dark:text-indigo-400/60">
                      <Lock className="w-3 h-3" />
                      {workflowName(key.workflow_id) || key.workflow_id.substring(0, 8)}
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground/50 dark:text-white/15">
                      <Globe className="w-3 h-3" />
                      All workflows
                    </span>
                  )}
                </div>
              </div>
              <button
                onClick={() => handleRevoke(key.id)}
                className="p-2 text-muted-foreground/50 dark:text-white/20 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
                title="Revoke key"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Revoked keys */}
      {revokedKeys.length > 0 && (
        <div className="mt-6">
          <button
            onClick={() => setShowRevoked(!showRevoked)}
            className="flex items-center gap-2 text-xs text-muted-foreground/50 dark:text-white/20 hover:text-muted-foreground dark:hover:text-white/40 transition-colors"
          >
            {showRevoked ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
            {showRevoked ? 'Hide' : 'Show'} {revokedKeys.length} revoked key{revokedKeys.length !== 1 ? 's' : ''}
          </button>
          {showRevoked && (
            <div className="mt-2 space-y-2 opacity-50">
              {revokedKeys.map(key => (
                <div key={key.id} className="flex items-center gap-4 px-4 py-3 bg-card dark:bg-foreground/[0.02] border border-border dark:border-white/[0.04] rounded-xl">
                  <Shield className="w-4 h-4 text-muted-foreground/50 dark:text-white/15 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-muted-foreground dark:text-white/40 line-through">{key.name}</span>
                      <code className="text-xs font-mono text-muted-foreground/50 dark:text-white/15">{key.key_prefix}...</code>
                    </div>
                    <span className="text-xs text-red-600/50 dark:text-red-400/40">
                      Revoked {new Date(key.revoked_at!).toLocaleDateString()}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
