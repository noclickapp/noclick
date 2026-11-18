// Copy-link button that copies a URL to clipboard with link icon and visual feedback.
// Used for deep-link copy actions on nodes and fields in the workflow editor.

import { useState } from 'react';
import { Link2, Check } from 'lucide-react';
import { toast } from 'sonner';

interface CopyLinkButtonProps {
    url: string;
    tooltip?: string;
    className?: string;
}

export function CopyLinkButton({ url, tooltip = 'Copy link', className = '' }: CopyLinkButtonProps) {
    const [copied, setCopied] = useState(false);

    const handleCopy = async (e: React.MouseEvent) => {
        e.stopPropagation();
        try {
            await navigator.clipboard.writeText(url);
            setCopied(true);
            toast.success('Link copied to clipboard');
            setTimeout(() => setCopied(false), 2000);
        } catch (err) {
            console.error('Failed to copy link:', err);
            toast.error('Failed to copy link');
        }
    };

    return (
        <button
            type="button"
            onClick={handleCopy}
            className={`p-1 rounded hover:bg-foreground/[0.08] transition-all shrink-0 ${className}`}
            title={copied ? 'Copied!' : tooltip}
        >
            {copied ? (
                <Check className="w-3 h-3 text-green-600 dark:text-green-400" />
            ) : (
                <Link2 className="w-3 h-3 text-muted-foreground dark:text-zinc-500 hover:text-foreground/80" />
            )}
        </button>
    );
}
