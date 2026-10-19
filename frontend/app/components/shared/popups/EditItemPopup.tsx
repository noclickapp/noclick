/**
 * Generic edit item popup component.
 * Used for editing apps, databases, and other items with name/description.
 *
 * This component provides a consistent editing experience across the application,
 * with change detection, validation, and delete functionality.
 */

import { useState, useEffect, type KeyboardEvent } from 'react';
import type { LucideIcon } from 'lucide-react';
import { ShellDialog } from '~/components/shell/ShellDialog';
import { BUTTON_GHOST, BUTTON_PRIMARY } from '~/components/shell/buttons';
import { FIELD, FIELD_LABEL } from '~/components/shell/fields';
import { cn } from '~/lib/utils';

/** ⌘↵ in a dialog's textarea submits its form, as Enter does in its fields. */
export function submitOnModEnter(e: KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        e.currentTarget.closest('form')?.requestSubmit();
    }
}

interface EditableItem {
    id: string;
    name: string;
    description?: string;
}

interface EditItemPopupProps<T extends EditableItem> {
    /** The item being edited */
    item: T | null;
    /** Type of item (e.g., "App", "Database") - used in UI labels */
    itemType: string;
    /** Icon component to display in header */
    Icon: LucideIcon;
    /** Whether the dialog is open */
    isOpen: boolean;
    /** Callback to handle dialog open/close state */
    onOpenChange: (open: boolean) => void;
    /** Callback when item is updated */
    onUpdate: (itemId: string, updates: { name?: string; description?: string }) => void;
    /** Callback when item deletion is requested */
    onDelete: (itemId: string) => void;
    /**
     * When false, the item isn't owned by the current user: name/description are
     * read-only, Save is hidden, and the destructive action reads "Remove" (it
     * drops the user's own access via share:leave rather than deleting). Defaults
     * to true. Lets the same popup serve shared items without offering edits that
     * the backend would reject.
     */
    canEdit?: boolean;
}

export function EditItemPopup<T extends EditableItem>({
    item,
    itemType,
    Icon,
    isOpen,
    onOpenChange,
    onUpdate,
    onDelete,
    canEdit = true,
}: EditItemPopupProps<T>) {
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [originalName, setOriginalName] = useState('');
    const [originalDescription, setOriginalDescription] = useState('');

    // Populate form when item changes
    useEffect(() => {
        if (item) {
            const itemName = item.name || '';
            const itemDescription = item.description || '';
            setName(itemName);
            setDescription(itemDescription);
            setOriginalName(itemName);
            setOriginalDescription(itemDescription);
        } else {
            // Reset form when no item is selected
            setName('');
            setDescription('');
            setOriginalName('');
            setOriginalDescription('');
        }
    }, [item]);

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        if (item && name.trim()) {
            onUpdate(item.id, {
                name: name.trim(),
                description: description.trim() || ''
            });
        }
    };

    // Check if changes have been made
    const hasChanges = name.trim() !== originalName || description.trim() !== originalDescription;

    const noun = itemType.toLowerCase();

    return (
        <ShellDialog
            open={isOpen}
            onOpenChange={onOpenChange}
            mark={<Icon className="h-5 w-5" strokeWidth={1.75} />}
            title={canEdit ? `Edit ${noun}` : itemType}
            description={canEdit ? 'Its name and what it’s for.' : `It’s shared with you, so only its owner can change it. You can remove it from your list.`}
            onSubmit={handleSubmit}
            footer={
                <>
                    <button
                        type="button"
                        onClick={() => item && onDelete(item.id)}
                        className={cn(BUTTON_GHOST, 'mr-auto -ml-3 text-red-600 hover:bg-red-500/10 hover:text-red-600 dark:text-red-400 dark:hover:text-red-400')}
                    >
                        {canEdit ? 'Delete' : 'Remove'} {noun}
                    </button>
                    <button type="button" onClick={() => onOpenChange(false)} className={BUTTON_GHOST}>
                        {canEdit ? 'Cancel' : 'Close'}
                    </button>
                    {canEdit && (
                        <button type="submit" disabled={!name.trim() || !hasChanges} className={BUTTON_PRIMARY}>
                            Save
                        </button>
                    )}
                </>
            }
        >
            <div className="space-y-4 pt-2">
                <label className="block">
                    <span className={FIELD_LABEL}>Name</span>
                    <input
                        type="text"
                        required
                        // eslint-disable-next-line jsx-a11y/no-autofocus -- the dialog opens to rename
                        autoFocus={canEdit}
                        disabled={!canEdit}
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        className={cn(FIELD, 'disabled:cursor-not-allowed')}
                        placeholder={`Name the ${noun}`}
                    />
                </label>
                <label className="block">
                    <span className={FIELD_LABEL}>Description</span>
                    <textarea
                        rows={3}
                        disabled={!canEdit}
                        value={description}
                        onChange={(e) => setDescription(e.target.value)}
                        className={cn(FIELD, 'h-auto resize-none py-2.5 leading-relaxed disabled:cursor-not-allowed')}
                        placeholder="What it does"
                        onKeyDown={submitOnModEnter}
                    />
                </label>
            </div>
        </ShellDialog>
    );
}
