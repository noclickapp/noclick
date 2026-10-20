// API key management for the NoClick SDK.
// Lets users create, view, copy, and revoke API keys for external app access.

import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router';
import { Copy, Check, Trash2, Plus, Shield, Eye, EyeOff, ChevronDown, ChevronRight, Globe, Lock, Search, Workflow, ArrowRight, ArrowUpRight } from 'lucide-react';
import { cn } from '~/lib/utils';
import { sendEventAsync } from '~/lib/socket-sender';
import { Popover, PopoverContent, PopoverTrigger } from '~/components/ui/popover';
import { fuzzyFilter } from '~/utils/fuzzySearch';
import { isLocalEdition } from '~/lib/edition';
import { backendAuthHeaders } from '~/lib/apiAuth';
import { getDeveloperConsoleHref } from '~/lib/developerConsole';
import { BUTTON_PRIMARY } from '~/components/shell/buttons';
import { FIELD, FIELD_LABEL, QUIET_LINK } from '~/components/shell/fields';
import { SettingsEmpty, SettingsGroup, SettingsGroupTitle, SettingsHeader, SettingsRow } from '~/components/settings/SettingsParts';

// Backend API base URL
const API_BASE = import.meta.env.VITE_API_URL || '';

// Shown only without a developer console, where these keys work with the open repo's own SDK clients.
const DOC_LINKS = [
  { label: 'TypeScript SDK', href: 'https://github.com/noclickapp/noclick/tree/main/sdk/typescript#readme' },
  { label: 'Python SDK', href: 'https://github.com/noclickapp/noclick/tree/main/sdk/python#readme' },
];

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

async function responseError(resp: Response): Promise<string> {
  const detail = await resp.json().then(b => b?.detail).catch(() => null);
  return typeof detail === 'string' ? detail : `request failed (${resp.status})`;
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
        <button className="flex h-10 w-full max-w-[220px] items-center gap-1.5 rounded-xl border border-border px-3.5 text-[13.5px] text-foreground/85 transition-colors hover:border-foreground/25 dark:border-foreground/[0.1] dark:hover:border-foreground/25">
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
  const [error, setError] = useState<string | null>(null);

  const fetchKeys = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/keys`, { credentials: 'include', headers: await backendAuthHeaders() });
      if (!resp.ok) throw new Error(await responseError(resp));
      setKeys(await resp.json());
      setError(null);
    } catch (e) {
      console.error('Failed to fetch API keys:', e);
      setError(`Couldn't load API keys: ${(e as Error).message}`);
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
        headers: { 'Content-Type': 'application/json', ...(await backendAuthHeaders()) },
        credentials: 'include',
        body: JSON.stringify({
          name: newKeyName.trim(),
          permissions: ['read', 'execute', 'write'],
          workflow_id: newKeyWorkflow || null,
        }),
      });
      if (!resp.ok) throw new Error(await responseError(resp));
      const data: NewKeyResponse = await resp.json();
      setNewKeyRaw(data.raw_key);
      setNewKeyName('');
      setNewKeyWorkflow('');
      setError(null);
      await fetchKeys();
    } catch (e) {
      console.error('Failed to create API key:', e);
      setError(`Couldn't create API key: ${(e as Error).message}`);
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (keyId: string) => {
    try {
      const resp = await fetch(`${API_BASE}/api/keys/${keyId}`, {
        method: 'DELETE', credentials: 'include', headers: await backendAuthHeaders(),
      });
      if (!resp.ok) throw new Error(await responseError(resp));
      setError(null);
      await fetchKeys();
    } catch (e) {
      console.error('Failed to revoke API key:', e);
      setError(`Couldn't revoke API key: ${(e as Error).message}`);
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
  const consoleHref = getDeveloperConsoleHref();
  const keyRow = (key: APIKey) => (
    <SettingsRow
      key={key.id}
      label={
        <span className="flex items-center gap-2">
          {key.name}
          <code className="font-mono text-xs font-normal text-muted-foreground">{key.key_prefix}…</code>
        </span>
      }
      description={
        <span className="flex flex-wrap items-center gap-x-3">
          <span>Created {new Date(key.created_at).toLocaleDateString()}</span>
          {key.last_used_at && <span>Last used {new Date(key.last_used_at).toLocaleDateString()}</span>}
          {key.workflow_id ? (
            <span className="inline-flex items-center gap-1">
              <Lock className="h-3 w-3" />
              {workflowName(key.workflow_id) || key.workflow_id.substring(0, 8)}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1">
              <Globe className="h-3 w-3" />
              All workflows
            </span>
          )}
        </span>
      }
      control={
        <button
          onClick={() => handleRevoke(key.id)}
          className="rounded-full p-2 text-muted-foreground transition-colors hover:bg-red-500/10 hover:text-red-600 dark:hover:text-red-400"
          title="Revoke key"
          aria-label={`Revoke ${key.name}`}
        >
          <Trash2 className="h-4 w-4" />
        </button>
      }
    />
  );

  // A deployment with a developer console makes keys there: this section opens it, and lists the older keys that
  // still work so they can be revoked.
  if (consoleHref) {
    return (
      <div>
        <SettingsHeader title="Developer" description="Build on NoClick from your own code." />
        <SettingsGroup>
          <SettingsRow
            label="Developer console"
            description="API keys, users, agents, logs and usage."
            control={
              <Link to={consoleHref} className={BUTTON_PRIMARY}>
                Open console
                <ArrowRight className="h-4 w-4" />
              </Link>
            }
          />
        </SettingsGroup>
        {error && <p role="alert" className="mt-3 text-[13px] text-red-600 dark:text-red-400">{error}</p>}
        {activeKeys.length > 0 && (
          <div className="mt-8">
            <SettingsGroupTitle title="Older keys" description="They keep working. New keys are made in the console." />
            <SettingsGroup>{activeKeys.map(keyRow)}</SettingsGroup>
          </div>
        )}
      </div>
    );
  }


  return (
    <div>
      <SettingsHeader title="Developer" description="API keys for connecting external apps via the NoClick SDK.">
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[13px]">
          {DOC_LINKS.map(({ label, href }) => (
            <a key={href} href={href} target="_blank" rel="noopener noreferrer" className={QUIET_LINK}>
              {label}
              <ArrowUpRight className="h-3.5 w-3.5" />
            </a>
          ))}
        </div>
      </SettingsHeader>

      {error && (
        <div className="mb-6 px-4 py-3 bg-red-500/10 border border-red-500/30 rounded-xl text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

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
      <div className="mb-6 flex flex-wrap items-end gap-2.5">
        <div className="min-w-[12rem] flex-1">
          <label htmlFor="new-key-name" className={FIELD_LABEL}>Key name</label>
          <input
            id="new-key-name"
            value={newKeyName}
            onChange={e => setNewKeyName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleCreate()}
            placeholder="e.g. My Dashboard App"
            className={FIELD}
          />
        </div>
        <div>
          <span className={FIELD_LABEL}>Scope</span>
          <ScopeDropdown value={newKeyWorkflow} workflows={workflows} onChange={setNewKeyWorkflow} />
        </div>
        <button onClick={handleCreate} disabled={creating || !newKeyName.trim()} className={cn(BUTTON_PRIMARY, 'h-10 px-4')}>
          <Plus className="w-4 h-4" />
          Create
        </button>
      </div>

      {/* Quickstart — collapsible */}
      <button
        onClick={() => setShowQuickstart(!showQuickstart)}
        className="mb-8 flex items-center gap-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
      >
        {showQuickstart ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
        Quick start
      </button>
      {showQuickstart && (
        <div className="-mt-5 mb-8 p-4 bg-card dark:bg-foreground/[0.02] border border-border dark:border-white/[0.04] rounded-xl">
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
      <SettingsGroupTitle title="Keys" />
      <SettingsGroup>
        {loading ? (
          <SettingsEmpty>Loading…</SettingsEmpty>
        ) : activeKeys.length === 0 ? (
          <SettingsEmpty>No keys yet. Create one above.</SettingsEmpty>
        ) : (
          activeKeys.map(keyRow)
        )}
      </SettingsGroup>

      {/* Revoked keys */}
      {revokedKeys.length > 0 && (
        <div className="mt-6">
          <button
            onClick={() => setShowRevoked(!showRevoked)}
            className="flex items-center gap-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
          >
            {showRevoked ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
            {showRevoked ? 'Hide' : 'Show'} {revokedKeys.length} revoked key{revokedKeys.length !== 1 ? 's' : ''}
          </button>
          {showRevoked && (
            <SettingsGroup className="mt-2 opacity-60">
              {revokedKeys.map(key => (
                <SettingsRow
                  key={key.id}
                  label={
                    <span className="flex items-center gap-2 text-muted-foreground line-through">
                      {key.name}
                      <code className="font-mono text-xs font-normal">{key.key_prefix}…</code>
                    </span>
                  }
                  description={`Revoked ${new Date(key.revoked_at!).toLocaleDateString()}`}
                />
              ))}
            </SettingsGroup>
          )}
        </div>
      )}
    </div>
  );
}
