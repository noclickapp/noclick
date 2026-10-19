/**
 * Generic delete confirmation popup component.
 * Used for confirming deletion of apps, databases, columns, rows, and other items.
 *
 * This component provides a consistent delete confirmation experience across the application
 * with optional warning icon and item name highlighting.
 */

import { Trash2 } from 'lucide-react';
import { ShellDialog } from '~/components/shell/ShellDialog';
import { BUTTON_DANGER, BUTTON_GHOST } from '~/components/shell/buttons';

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
    const noun = itemType.toLowerCase();
    const titleText = title ?? (softDelete ? 'Move to Trash?' : `Delete ${noun}?`);
    const confirmText = confirmLabel ?? (softDelete ? 'Move to Trash' : 'Delete');
    const subTextContent = subText ?? (softDelete ? 'You can restore it from Trash for 30 days.' : 'This can’t be undone.');
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
                <span className="font-medium text-foreground">{itemCount} {noun}{itemCount > 1 ? 's' : ''}</span>?
            </>
        );
    } else if (itemName) {
        defaultMessage = (
            <>
                Are you sure you want to delete{' '}
                <span className="font-medium text-foreground">“{itemName}”</span>?
            </>
        );
    } else if (softDelete) {
        defaultMessage = `This ${noun} moves to Trash.`;
    } else {
        defaultMessage = `Are you sure you want to delete this ${noun}?`;
    }

    return (
        <ShellDialog
            open={isOpen}
            onOpenChange={onOpenChange}
            mark={showWarningIcon ? <Trash2 className="h-5 w-5" strokeWidth={1.75} /> : undefined}
            tone={softDelete ? 'neutral' : 'danger'}
            title={titleText}
            className={dialogClassName}
            footer={
                <>
                    <button type="button" onClick={() => onOpenChange(false)} className={BUTTON_GHOST}>
                        Cancel
                    </button>
                    <button type="button" onClick={handleConfirm} className={BUTTON_DANGER}>
                        {confirmText}
                    </button>
                </>
            }
        >
            <p className="text-[14px] leading-relaxed text-foreground/85">{defaultMessage}</p>
            {subTextContent && <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">{subTextContent}</p>}
        </ShellDialog>
    );
}
