// Reusable copy button with visual feedback (icon changes to checkmark for 2 seconds).
// Used in readonly fields, webhook URLs, and anywhere clipboard copy is needed.

import { useState } from 'react';
import { Copy, Check } from 'lucide-react';
import { ShortcutTooltip } from '~/components/shared/ShortcutTooltip';

interface CopyButtonProps {
    value: string;
    className?: string;
}

export function CopyButton({ value, className = '' }: CopyButtonProps) {
    const [copied, setCopied] = useState(false);

    const handleCopy = async (e: React.MouseEvent) => {
        e.stopPropagation();
        try {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch (err) {
            console.error('Failed to copy:', err);
        }
    };

    return (
        // An icon button is a circle, named by the app's tooltip.
        <ShortcutTooltip label={copied ? 'Copied' : 'Copy'}>
            <button
                type="button"
                onClick={handleCopy}
                aria-label={copied ? 'Copied' : 'Copy'}
                className={`p-1.5 rounded-full hover:bg-foreground/[0.08] transition-colors shrink-0 ${className}`}
            >
                {copied ? (
                    <Check className="w-4 h-4 text-green-600 dark:text-green-400" />
                ) : (
                    <Copy className="w-4 h-4 text-muted-foreground" />
                )}
            </button>
        </ShortcutTooltip>
    );
}
