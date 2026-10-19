// Making a folder for automations: a name and, if it helps, a line on what goes in it.

import { useState } from 'react';
import { FolderPlus } from 'lucide-react';
import { ShellDialog } from '~/components/shell/ShellDialog';
import { BUTTON_GHOST, BUTTON_PRIMARY } from '~/components/shell/buttons';
import { FIELD, FIELD_LABEL } from '~/components/shell/fields';
import { cn } from '~/lib/utils';
import { submitOnModEnter } from './EditItemPopup';

interface CreateFolderPopupProps {
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
    onCreateFolder: (data: { name: string; description: string }) => void;
    isCreating?: boolean;
    parentFolderName?: string | null;
}

export function CreateFolderPopup({ isOpen, onOpenChange, onCreateFolder, isCreating, parentFolderName }: CreateFolderPopupProps) {
    const [folderName, setFolderName] = useState('');
    const [folderDescription, setFolderDescription] = useState('');

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        if (folderName.trim()) {
            onCreateFolder({
                name: folderName.trim(),
                description: folderDescription.trim(),
            });
        }
    };

    const handleOpenChange = (open: boolean) => {
        onOpenChange(open);
        if (!open) {
            setFolderName('');
            setFolderDescription('');
        }
    };

    return (
        <ShellDialog
            open={isOpen}
            onOpenChange={handleOpenChange}
            mark={<FolderPlus className="h-5 w-5" strokeWidth={1.75} />}
            title={parentFolderName ? 'New subfolder' : 'New folder'}
            description={parentFolderName ? `Inside ${parentFolderName}.` : 'Keep related automations together.'}
            onSubmit={handleSubmit}
            footer={
                <>
                    <button type="button" onClick={() => handleOpenChange(false)} disabled={isCreating} className={BUTTON_GHOST}>
                        Cancel
                    </button>
                    <button type="submit" disabled={!folderName.trim() || isCreating} className={BUTTON_PRIMARY}>
                        {isCreating ? 'Creating…' : 'Create folder'}
                    </button>
                </>
            }
        >
            <div className="space-y-4 pt-2">
                <label className="block">
                    <span className={FIELD_LABEL}>Name</span>
                    {/* eslint-disable-next-line jsx-a11y/no-autofocus -- the dialog opens to type a name */}
                    <input type="text" required autoFocus value={folderName} onChange={(e) => setFolderName(e.target.value)} className={FIELD} placeholder="Client work" />
                </label>
                <label className="block">
                    <span className={FIELD_LABEL}>
                        Description <span className="font-normal text-muted-foreground">(optional)</span>
                    </span>
                    <textarea
                        rows={3}
                        value={folderDescription}
                        onChange={(e) => setFolderDescription(e.target.value)}
                        className={cn(FIELD, 'h-auto resize-none py-2.5 leading-relaxed')}
                        placeholder="What goes in it"
                        onKeyDown={submitOnModEnter}
                    />
                </label>
            </div>
        </ShellDialog>
    );
}
