// Readonly value field where clicking anywhere on the field copies the value to
// the clipboard, not just a small button at the end. Added so auto-generated URLs
// (webhook trigger URL, form input URL, and other copyable readonly config fields)
// are one-click-copyable across their whole surface. The copy/check icon is a
// non-interactive overlay (pointer-events-none) so clicks pass through to the input.

import { useState } from 'react';
import { Loader2, Copy, Check } from 'lucide-react';

interface CopyableReadonlyFieldProps {
    value: string;
    /** Whether the value is still being loaded/generated from the backend */
    isLoading?: boolean;
    /** When true, the field is click-to-copy and shows a copy affordance */
    copyable?: boolean;
    /** Placeholder shown while loading an empty value */
    loadingPlaceholder?: string;
    /** Placeholder shown when there is no value yet */
    emptyPlaceholder?: string;
    /** Base input classes from the consuming widget */
    inputClassName?: string;
}

export function CopyableReadonlyField({
    value,
    isLoading = false,
    copyable = false,
    loadingPlaceholder = 'Loading...',
    emptyPlaceholder = 'Will be auto-generated...',
    inputClassName = '',
}: CopyableReadonlyFieldProps) {
    const [copied, setCopied] = useState(false);
    const displayValue = value || '';
    const isEmpty = !displayValue;
    const showLoading = isLoading && isEmpty;
    const canCopy = copyable && !isEmpty && !showLoading;

    const handleCopy = async () => {
        if (!canCopy) return;
        try {
            await navigator.clipboard.writeText(displayValue);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch (err) {
            console.error('Failed to copy:', err);
        }
    };

    return (
        <div className="relative">
            <input
                type="text"
                value={showLoading ? '' : displayValue}
                readOnly
                placeholder={showLoading ? loadingPlaceholder : emptyPlaceholder}
                onClick={canCopy ? handleCopy : undefined}
                onKeyDown={canCopy ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleCopy(); } } : undefined}
                title={canCopy ? (copied ? 'Copied!' : 'Click to copy') : undefined}
                className={`${inputClassName} ${isEmpty || showLoading ? 'text-muted-foreground/70 dark:text-zinc-500 italic' : ''} ${canCopy ? 'cursor-pointer pr-9' : 'cursor-default'} bg-card/50`}
            />
            {showLoading && (
                <div className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none">
                    <Loader2 className="w-4 h-4 text-muted-foreground/70 dark:text-zinc-500 animate-spin" />
                </div>
            )}
            {canCopy && (
                <div className="absolute right-1 top-1/2 -translate-y-1/2 p-1.5 rounded pointer-events-none">
                    {copied ? (
                        <Check className="w-4 h-4 text-green-600 dark:text-green-400" />
                    ) : (
                        <Copy className="w-4 h-4 text-muted-foreground" />
                    )}
                </div>
            )}
        </div>
    );
}
