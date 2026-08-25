/**
 * Generic edit item popup component.
 * Used for editing apps, databases, and other items with name/description.
 *
 * This component provides a consistent editing experience across the application,
 * with change detection, validation, and delete functionality.
 */

import { useState, useEffect } from 'react';
import type { LucideIcon } from 'lucide-react';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from '~/components/ui/dialog';
import { Button } from '~/components/ui/button';

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

    return (
        <Dialog open={isOpen} onOpenChange={onOpenChange}>
            <DialogContent className="bg-sunken border-border text-foreground max-w-md p-6">
                <DialogHeader className="pb-4">
                    <DialogTitle className="text-xl text-foreground flex items-center gap-2">
                        <Icon className="h-5 w-5" />
                        {canEdit ? `Edit ${itemType}` : itemType}
                    </DialogTitle>
                    <div className="text-sm text-muted-foreground pt-1.5">
                        {canEdit
                            ? `Update your ${itemType.toLowerCase()} details and settings`
                            : `You don't own this ${itemType.toLowerCase()}. Only the owner can edit it, but you can remove it from your list.`}
                    </div>
                </DialogHeader>

                <form onSubmit={handleSubmit}>
                    <div className="space-y-6">
                        <div className="space-y-3">
                            <label className="text-sm font-medium text-foreground/80">
                                {itemType} Name
                            </label>
                            <div className="bg-card/90 backdrop-blur-sm rounded-full transition-all duration-200 border border-input dark:border-zinc-700/60 focus-within:border-muted-foreground/40 dark:focus-within:border-zinc-600/80">
                                <input
                                    type="text"
                                    required
                                    autoFocus={canEdit}
                                    disabled={!canEdit}
                                    value={name}
                                    onChange={(e) => setName(e.target.value)}
                                    className="bg-transparent text-foreground px-4 py-2.5 outline-none w-full text-sm placeholder:text-[hsl(var(--placeholder))] disabled:cursor-not-allowed disabled:text-muted-foreground"
                                    placeholder={`My awesome ${itemType.toLowerCase()}`}
                                />
                            </div>
                        </div>

                        <div className="space-y-3">
                            <label className="text-sm font-medium text-foreground/80">
                                Description
                            </label>
                            <div className="bg-card/90 backdrop-blur-sm rounded-lg transition-all duration-200 border border-input dark:border-zinc-700/60 focus-within:border-muted-foreground/40 dark:focus-within:border-zinc-600/80">
                                <textarea
                                    rows={4}
                                    disabled={!canEdit}
                                    value={description}
                                    onChange={(e) => setDescription(e.target.value)}
                                    className="bg-transparent text-foreground px-4 py-2.5 outline-none w-full text-sm placeholder:text-[hsl(var(--placeholder))] resize-none disabled:cursor-not-allowed disabled:text-muted-foreground"
                                    placeholder={`Tell us about your ${itemType.toLowerCase()}...`}
                                    onKeyDown={(e) => {
                                        if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                                            e.preventDefault();
                                            const form = e.currentTarget.closest('form');
                                            if (form) {
                                                form.requestSubmit();
                                            }
                                        }
                                    }}
                                />
                            </div>
                        </div>
                    </div>

                    <div className="flex justify-between pt-6">
                        <Button
                            type="button"
                            variant="destructive"
                            onClick={() => item && onDelete(item.id)}
                            className="h-10 bg-red-900 hover:bg-red-800 rounded-md shadow-[0_2.5px_0_0_#991b1b] hover:shadow-[0_1px_0_0_#991b1b] hover:translate-y-[1.5px] active:shadow-none active:translate-y-[2.5px] transition-all duration-100"
                        >
                            {canEdit ? 'Delete' : 'Remove'} {itemType}
                        </Button>
                        <div className="flex gap-2">
                            <Button
                                type="button"
                                variant="outline"
                                onClick={() => onOpenChange(false)}
                                className="h-10 bg-transparent text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] border border-border hover:border-muted-foreground/40 dark:hover:border-zinc-700 rounded-md"
                            >
                                {canEdit ? 'Cancel' : 'Close'}
                            </Button>
                            {canEdit && (
                                <Button
                                    type="submit"
                                    disabled={!name.trim() || !hasChanges}
                                    className="h-10 bg-primary hover:bg-primary text-primary-foreground font-medium rounded-md border-0 shadow-[0_2.5px_0_0_hsl(var(--primary)/0.6)] hover:shadow-[0_1px_0_0_hsl(var(--primary)/0.6)] hover:translate-y-[1.5px] active:shadow-none active:translate-y-[2.5px] transition-all duration-100 disabled:opacity-40 min-w-[120px]"
                                >
                                    Save Changes
                                </Button>
                            )}
                        </div>
                    </div>
                </form>
            </DialogContent>
        </Dialog>
    );
}
