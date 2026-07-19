// The app's "+ Create new" credential entry-point button — one markup shared
// by NodeCredentials' sections and the public provide/bridge method sections,
// so the affordance can't drift between surfaces.
import { Plus } from 'lucide-react';

export function CredentialCreateEntryButton({
  label,
  onClick,
  disabled = false,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 bg-muted/50 dark:bg-zinc-900/50 hover:bg-muted dark:hover:bg-zinc-900 border border-border hover:border-foreground/20 rounded-lg transition-all disabled:cursor-not-allowed disabled:opacity-60"
    >
      <Plus className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}
