// Reusable popup dialog for embedding YouTube videos.
// Used by WorkflowBrowser (Connect to X tutorials) and NavBar (Tutorial button).

import { useState } from 'react';
import { Copy, Check } from 'lucide-react';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from '~/components/ui/dialog';

interface VideoPopupProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    title: string;
    youtubeUrl: string;
    children?: React.ReactNode;
}

export function VideoPopup({ open, onOpenChange, title, youtubeUrl, children }: VideoPopupProps) {
    // Convert watch URLs to embed URLs
    const embedUrl = youtubeUrl.includes('watch?v=')
        ? youtubeUrl.replace('watch?v=', 'embed/')
        : youtubeUrl.includes('youtu.be/')
            ? youtubeUrl.replace('youtu.be/', 'www.youtube.com/embed/')
            : youtubeUrl;

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-4xl p-0 overflow-hidden">
                <DialogHeader className="p-4 pb-0">
                    <DialogTitle>{title}</DialogTitle>
                </DialogHeader>
                <div className="aspect-video w-full">
                    <iframe
                        src={open ? `${embedUrl}?autoplay=1` : ''}
                        className="w-full h-full"
                        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                        allowFullScreen
                        title={title}
                    />
                </div>
                {children && <div className="px-4 pb-4">{children}</div>}
            </DialogContent>
        </Dialog>
    );
}

export function CopyableCode({ label, code }: { label: string; code: string }) {
    const [copied, setCopied] = useState(false);

    const handleCopy = () => {
        navigator.clipboard.writeText(code);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    };

    return (
        <div className="space-y-1.5">
            <span className="text-sm font-medium text-foreground">{label}</span>
            <div
                className="flex items-center gap-3 bg-foreground/[0.04] border border-border dark:border-white/[0.08] rounded-lg px-4 py-2.5 cursor-pointer hover:bg-foreground/[0.07] hover:border-muted-foreground/30 dark:hover:border-white/[0.12] transition-colors group"
                onClick={handleCopy}
            >
                <code className="text-sm text-foreground/80 flex-1 select-all font-mono">{code}</code>
                <button className={`shrink-0 px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${copied ? 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400' : 'bg-foreground/[0.08] text-muted-foreground group-hover:bg-accent dark:group-hover:bg-white/[0.12] group-hover:text-foreground/80'}`}>
                    {copied ? (
                        <span className="flex items-center gap-1"><Check className="w-3 h-3" /> Copied</span>
                    ) : (
                        <span className="flex items-center gap-1"><Copy className="w-3 h-3" /> Copy</span>
                    )}
                </button>
            </div>
        </div>
    );
}
