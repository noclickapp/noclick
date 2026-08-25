// CreateFolderPopup component for creating new workflow folders
// Modeled on CreateAppPopup with name + description inputs in a Dialog

import { useState } from 'react';
import { FolderPlus } from 'lucide-react';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from '~/components/ui/dialog';
import { Button } from '~/components/ui/button';

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
        <Dialog open={isOpen} onOpenChange={handleOpenChange}>
            <DialogContent className="bg-sunken border-border text-foreground max-w-md p-6">
                <DialogHeader className="pb-1">
                    <DialogTitle className="text-xl text-foreground flex items-center gap-2">
                        <FolderPlus className="h-5 w-5" />
                        {parentFolderName ? 'Create Subfolder' : 'Create New Folder'}
                    </DialogTitle>
                    {parentFolderName && (
                        <div className="text-sm text-muted-foreground pt-0.5">
                            Inside <span className="text-foreground/80">{parentFolderName}</span>
                        </div>
                    )}
                </DialogHeader>

                <form onSubmit={handleSubmit}>
                    <div className="space-y-4">
                        <div className="space-y-3">
                            <label className="text-sm font-medium text-foreground/80">
                                Folder Name
                            </label>
                            <div className="bg-card/90 backdrop-blur-sm rounded-full transition-all duration-200 border border-input dark:border-zinc-700/60 focus-within:border-muted-foreground/40 dark:focus-within:border-zinc-600/80">
                                <input
                                    type="text"
                                    required
                                    autoFocus
                                    value={folderName}
                                    onChange={(e) => setFolderName(e.target.value)}
                                    className="bg-transparent text-foreground px-4 py-2.5 outline-none w-full text-sm placeholder:text-[hsl(var(--placeholder))]"
                                    placeholder="My folder"
                                />
                            </div>
                        </div>

                        <div className="space-y-3">
                            <label className="text-sm font-medium text-foreground/80">
                                Description <span className="text-muted-foreground/70 dark:text-zinc-600 font-normal">(optional)</span>
                            </label>
                            <div className="bg-card/90 backdrop-blur-sm rounded-lg transition-all duration-200 border border-input dark:border-zinc-700/60 focus-within:border-muted-foreground/40 dark:focus-within:border-zinc-600/80">
                                <textarea
                                    rows={3}
                                    value={folderDescription}
                                    onChange={(e) => setFolderDescription(e.target.value)}
                                    className="bg-transparent text-foreground px-4 py-2.5 outline-none w-full text-sm placeholder:text-[hsl(var(--placeholder))] resize-none"
                                    placeholder="What will this folder contain?"
                                    onKeyDown={(e) => {
                                        if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                                            e.preventDefault();
                                            const form = e.currentTarget.closest('form');
                                            if (form) form.requestSubmit();
                                        }
                                    }}
                                />
                            </div>
                        </div>
                    </div>

                    <div className="flex justify-between pt-8">
                        <Button
                            type="button"
                            variant="outline"
                            onClick={() => handleOpenChange(false)}
                            disabled={isCreating}
                            className="h-10 bg-transparent text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] border border-border hover:border-muted-foreground/40 dark:hover:border-zinc-700 rounded-md"
                        >
                            Cancel
                        </Button>
                        <Button
                            type="submit"
                            disabled={!folderName.trim() || isCreating}
                            className="h-10 bg-primary hover:bg-primary text-primary-foreground font-medium rounded-md border-0 shadow-[0_2.5px_0_0_hsl(var(--primary)/0.6)] hover:shadow-[0_1px_0_0_hsl(var(--primary)/0.6)] hover:translate-y-[1.5px] active:shadow-none active:translate-y-[2.5px] transition-all duration-100 disabled:opacity-40 min-w-[100px]"
                        >
                            {isCreating ? 'Creating...' : 'Create Folder'}
                        </Button>
                    </div>
                </form>
            </DialogContent>
        </Dialog>
    );
}
