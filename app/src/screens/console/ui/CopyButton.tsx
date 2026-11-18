import { useState, type ReactNode } from 'react';
import { Check, Copy } from 'lucide-react';
import { cn } from '@/ui/utils';

/** Copy to the clipboard; the icon turns to an ink check for a moment. `children` shows beside the icon. */
export function CopyButton({ value, label = 'Copy', className, children }: { value: string; label?: string; className?: string; children?: ReactNode }) {
    const [copied, setCopied] = useState(false);
    return (
        <button
            type="button"
            aria-label={copied ? 'Copied' : label}
            title={copied ? 'Copied' : label}
            onClick={async (e) => {
                e.stopPropagation();
                try {
                    await navigator.clipboard.writeText(value);
                    setCopied(true);
                    window.setTimeout(() => setCopied(false), 1500);
                } catch (err) {
                    console.error('Copy failed', err);
                }
            }}
            className={cn(
                'inline-flex h-6 w-6 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-foreground/[0.08] hover:text-foreground',
                className
            )}
        >
            {children}
            {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
    );
}
