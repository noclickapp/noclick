import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from '~/components/ui/dialog';
import { Button } from '~/components/ui/button';

interface InstanceLimitDialogProps {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
    title?: string;
    description?: string;
    errorMessage?: string;
}

/**
 * Compatibility dialog for a limit response from an older server or extension.
 * The community runtime itself does not implement paid plans or checkout.
 */
export function InstanceLimitDialog({
    isOpen,
    onOpenChange,
    title = 'Operation unavailable',
    description,
    errorMessage,
}: InstanceLimitDialogProps) {
    return (
        <Dialog open={isOpen} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-md">
                <DialogHeader>
                    <DialogTitle>{title}</DialogTitle>
                    <DialogDescription>
                        {description || errorMessage || 'Check your instance configuration and try again.'}
                    </DialogDescription>
                </DialogHeader>
                <div className="flex justify-end">
                    <Button onClick={() => onOpenChange(false)}>Close</Button>
                </div>
            </DialogContent>
        </Dialog>
    );
}
