/**
 * Generic delete confirmation popup component.
 * Used for confirming deletion of apps, databases, columns, rows, and other items.
 *
 * This component provides a consistent delete confirmation experience across the application
 * with optional warning icon and item name highlighting.
 */

import { AlertTriangle } from 'lucide-react';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
} from '~/components/ui/dialog';
import { Button } from '~/components/ui/button';
import { cn } from '~/lib/utils';

interface DeleteConfirmPopupProps {
    /** The ID of the item to delete (optional - some items don't need IDs) */
    itemId?: string | null;
    /** Type of item being deleted (e.g., "App", "Database", "Column", "Row") */
    itemType: string;
    /** Optional name of the specific item being deleted (e.g., column name) */
    itemName?: string;
    /** Optional count for batch deletions (e.g., "3 rows") */
    itemCount?: number;
    /** Whether the dialog is open */
    isOpen: boolean;
    /** Callback to handle dialog open/close state */
    onOpenChange: (open: boolean) => void;
    /** Callback when deletion is confirmed */
    onConfirmDelete: (itemId?: string) => void;
    /** Optional custom warning message */
    customMessage?: string;
    /** Show warning icon (default: true) */
    showWarningIcon?: boolean;
    /** When true, shows softer "Move to Trash" UI instead of permanent delete */
    softDelete?: boolean;
    /** Override the dialog title (e.g. "Remove shared workflow") */
    title?: string;
    /** Override the confirm button label (e.g. "Remove") */
    confirmLabel?: string;
    /** Override the secondary line under the message (e.g. the restore/permanence note) */
    subText?: string;
    /** Extra classes on the dialog content — e.g. a higher z-index when the
     *  confirm must stack above another modal (default content z is 70). */
    dialogClassName?: string;
}

export function DeleteConfirmPopup({
    itemId,
    itemType,
    itemName,
    itemCount,
    isOpen,
    onOpenChange,
    onConfirmDelete,
    customMessage,
    showWarningIcon = true,
    softDelete = false,
    title,
    confirmLabel,
    subText,
    dialogClassName,
}: DeleteConfirmPopupProps) {
    const titleText = title ?? (softDelete ? 'Move to Trash' : `Delete ${itemType}`);
    const confirmText = confirmLabel ?? (softDelete ? 'Move to Trash' : `Delete ${itemType}`);
    const subTextContent = subText ?? (softDelete
        ? 'You can restore this workflow within 30 days.'
        : 'This action cannot be undone. All data will be permanently removed.');
    const handleConfirm = () => {
        // Close dialog first to prevent duplicate calls from React Strict Mode
        onOpenChange(false);
        // Then trigger the delete callback
        onConfirmDelete(itemId || undefined);
    };

    // Build default message based on props
    let defaultMessage: React.ReactNode;
    if (customMessage) {
        defaultMessage = customMessage;
    } else if (itemCount !== undefined && itemCount > 0) {
        defaultMessage = (
            <>
                Are you sure you want to delete{' '}
                <span className="font-semibold text-foreground">{itemCount} {itemType.toLowerCase()}{itemCount > 1 ? 's' : ''}</span>?
            </>
        );
    } else if (itemName) {
        defaultMessage = (
            <>
                Are you sure you want to delete{' '}
                <span className="font-semibold text-foreground">"{itemName}"</span>?
            </>
        );
    } else {
        defaultMessage = `Are you sure you want to delete this ${itemType.toLowerCase()}?`;
    }

    return (
        <Dialog open={isOpen} onOpenChange={onOpenChange}>
            <DialogContent className={cn("bg-sunken border-border text-foreground max-w-md p-6", dialogClassName)}>
                <DialogHeader className="pb-2">
                    <DialogTitle className="text-xl text-foreground flex items-center gap-2.5">
                        {showWarningIcon && (
                            <div className={cn("p-2 rounded-full", softDelete ? "bg-amber-500/10" : "bg-red-500/10")}>
                                <AlertTriangle className={cn("h-5 w-5", softDelete ? "text-amber-600 dark:text-amber-400" : "text-red-600 dark:text-red-400")} />
                            </div>
                        )}
                        {titleText}
                    </DialogTitle>
                    <DialogDescription className="text-[15px] text-foreground/80 leading-relaxed pt-4">
                        {defaultMessage}
                    </DialogDescription>
                </DialogHeader>

                <div className="py-2 pb-4">
                    <p className="text-sm text-muted-foreground dark:text-zinc-500 leading-relaxed">
                        {subTextContent}
                    </p>
                </div>

                <div className="flex justify-between pt-4">
                    <Button
                        type="button"
                        variant="outline"
                        onClick={() => onOpenChange(false)}
                        className="h-10 bg-transparent text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] border border-border hover:border-muted-foreground/40 dark:hover:border-zinc-700 rounded-md"
                    >
                        Cancel
                    </Button>
                    <Button
                        type="button"
                        onClick={handleConfirm}
                        className={cn(
                            "h-10 text-white shadow-sm font-medium min-w-[100px] rounded-md shadow-[0_2.5px_0_0_#991b1b] hover:shadow-[0_1px_0_0_#991b1b] hover:translate-y-[1.5px] active:shadow-none active:translate-y-[2.5px] transition-all duration-100",
                            softDelete
                                ? "bg-amber-600 hover:bg-amber-700"
                                : "bg-red-600 hover:bg-red-700"
                        )}
                    >
                        {confirmText}
                    </Button>
                </div>
            </DialogContent>
        </Dialog>
    );
}
