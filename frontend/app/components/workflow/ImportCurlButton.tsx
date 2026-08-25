// ImportCurlButton - a form-level action for the HTTP Request node that lets a
// user paste a `curl` command (as found in nearly every API's docs) and have
// the node's method, URL, query params, headers, and body filled in for them.
// Applies the parsed result through the standard node:update-data event so the
// change persists and syncs to collaborators like any other edit.

import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Terminal, X } from 'lucide-react';
import { parseCurl, methodToOperation } from '~/lib/curlParser';

interface ImportCurlButtonProps {
    nodeId: string;
}

export function ImportCurlButton({ nodeId }: ImportCurlButtonProps) {
    const [open, setOpen] = useState(false);
    const [text, setText] = useState('');
    const [error, setError] = useState<string | null>(null);

    // Close on Escape while open. Capture phase + stopImmediatePropagation so
    // this modal consumes the Escape and it doesn't also close whatever popup
    // is underneath (matches MCPConnectModal's handling).
    useEffect(() => {
        if (!open) return;
        const onKey = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                e.stopImmediatePropagation();
                setOpen(false);
            }
        };
        document.addEventListener('keydown', onKey, true);
        return () => document.removeEventListener('keydown', onKey, true);
    }, [open]);

    const handleImport = () => {
        if (!text.trim()) {
            setError('Paste a cURL command first.');
            return;
        }
        // Parsing is the only step that should keep the modal open on failure.
        let parsed;
        try {
            parsed = parseCurl(text);
        } catch (e) {
            setError(e instanceof Error ? e.message : 'Could not parse the cURL command.');
            return;
        }
        const config: Record<string, unknown> = {
            url: parsed.url,
            query_params: parsed.queryParams,
            headers: parsed.headers,
            body_type: parsed.bodyType,
            body: parsed.body,
            body_form: parsed.bodyForm,
        };
        if (parsed.verifySsl === false) config.verify_ssl = 'false';

        // Close first, then apply — so an exception in a downstream
        // node:update-data handler can't leave the modal stuck open.
        setOpen(false);
        setText('');
        setError(null);
        document.dispatchEvent(
            new CustomEvent('noclick:node:update-data', {
                detail: {
                    nodeId,
                    data: { config, operation: methodToOperation(parsed.method) },
                },
            })
        );
    };

    return (
        <>
            <button
                type="button"
                onClick={() => setOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-md border border-foreground/[0.08] bg-foreground/[0.04] px-2.5 py-1.5 text-xs text-muted-foreground dark:text-zinc-300 transition-colors hover:bg-foreground/[0.08] hover:text-foreground"
                title="Fill this node from a cURL command"
            >
                <Terminal className="h-3.5 w-3.5" />
                <span>Import cURL</span>
            </button>

            {open &&
                createPortal(
                    <>
                        <div
                            className="fixed inset-0 z-[100] bg-black/60"
                            onMouseDown={() => setOpen(false)}
                        />
                        <div className="fixed left-1/2 top-[12vh] z-[101] w-[92vw] max-w-lg -translate-x-1/2 overflow-hidden rounded-xl border border-foreground/10 bg-popover dark:bg-[#0a0a0b] shadow-2xl shadow-black/60">
                            <div className="flex items-start justify-between gap-3 border-b border-foreground/[0.06] px-4 py-3">
                                <div>
                                    <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                                        <Terminal className="h-4 w-4 text-muted-foreground" />
                                        Import from cURL
                                    </div>
                                    <p className="mt-1 text-xs leading-relaxed text-muted-foreground/70 dark:text-zinc-500">
                                        Method, URL, query params, headers, and body are filled in.
                                        Credentials in the command land as headers — move them to a
                                        credential afterwards if you prefer.
                                    </p>
                                </div>
                                <button
                                    type="button"
                                    onClick={() => setOpen(false)}
                                    className="-mr-1 shrink-0 rounded-md p-1 text-muted-foreground/70 dark:text-zinc-500 transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                                >
                                    <X className="h-4 w-4" />
                                </button>
                            </div>

                            <div className="px-4 py-3">
                                <textarea
                                    value={text}
                                    onChange={(e) => {
                                        setText(e.target.value);
                                        setError(null);
                                    }}
                                    placeholder={"curl 'https://api.example.com/v1/users' \\\n  -H 'Authorization: Bearer ...' \\\n  -d '{\"name\":\"Ada\"}'"}
                                    rows={7}
                                    spellCheck={false}
                                    autoFocus
                                    className="scrollbar-subtle w-full rounded-lg border border-foreground/[0.08] bg-foreground/[0.03] dark:bg-black/40 px-3 py-2.5 font-mono text-xs leading-relaxed text-foreground outline-none transition-colors placeholder:text-foreground/25 focus:border-foreground/20"
                                />
                                {error && <p className="mt-2 text-xs text-red-600 dark:text-red-400">{error}</p>}
                            </div>

                            <div className="flex items-center justify-end gap-2 border-t border-foreground/[0.06] px-4 py-2.5">
                                <button
                                    type="button"
                                    onClick={() => setOpen(false)}
                                    className="rounded-md px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
                                >
                                    Cancel
                                </button>
                                <button
                                    type="button"
                                    onClick={handleImport}
                                    className="rounded-md bg-foreground/[0.1] px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-foreground/[0.16]"
                                >
                                    Import
                                </button>
                            </div>
                        </div>
                    </>,
                    document.body
                )}
        </>
    );
}
