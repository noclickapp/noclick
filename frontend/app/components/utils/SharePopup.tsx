/**
 * Placeholder share popup for apps.
 * App sharing is not yet implemented - this shows a coming soon message.
 * For workflow/database sharing, use ShareDialog instead.
 */

import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
} from '~/components/ui/dialog';
import { Button } from '~/components/ui/button';
import { Share2 } from 'lucide-react';

interface SharePopupProps {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
}

export function SharePopup({ isOpen, onOpenChange }: SharePopupProps) {
    return (
        <Dialog open={isOpen} onOpenChange={onOpenChange}>
            <DialogContent className="bg-popover dark:bg-zinc-950 border-border text-foreground max-w-sm">
                <DialogHeader>
                    <DialogTitle className="text-lg font-medium text-foreground flex items-center gap-2">
                        <Share2 className="h-5 w-5" />
                        Share App
                    </DialogTitle>
                    <DialogDescription className="text-sm text-muted-foreground pt-2">
                        App sharing is coming soon. For now, you can publish
                        your app to get a shareable link.
                    </DialogDescription>
                </DialogHeader>
                <div className="flex justify-end pt-4">
                    <Button
                        variant="outline"
                        onClick={() => onOpenChange(false)}
                        className="h-10 bg-transparent text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] border border-border hover:border-foreground/20 rounded-md"
                    >
                        Got it
                    </Button>
                </div>
            </DialogContent>
        </Dialog>
    );
}
