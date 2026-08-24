// Autocomplete dropdown for @-mentioning workspace files in the chat composer.
// Presentation-only: it renders an already-filtered file list and reports hover
// / selection; all keyboard navigation lives in AgentChatComposer's onKeyDown so
// it can preempt the Enter-to-send handler (a child listener can't reliably do
// that). Added for the workspace @-mention feature.

import { File as FileIcon } from 'lucide-react';
import { cn } from '~/lib/utils';

export interface MentionMenuFile {
  /** Volume-relative path, e.g. "seo/report.md". */
  path: string;
}

export function MentionMenu({
  files,
  activeIndex,
  onSelect,
  onHover,
}: {
  files: MentionMenuFile[];
  activeIndex: number;
  onSelect: (index: number) => void;
  onHover: (index: number) => void;
}) {
  if (files.length === 0) return null;
  return (
    <div
      className="absolute bottom-full left-3 z-50 mb-1 max-h-56 w-[min(24rem,calc(100%-1.5rem))] overflow-y-auto rounded-lg border border-border bg-popover p-1 shadow-xl scrollbar-subtle"
      data-testid="mention-menu"
    >
      {files.map((file, i) => (
        <button
          key={file.path}
          type="button"
          // Keep focus in the textarea: a mousedown here must not blur the input
          // before the click selects the file.
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => onSelect(i)}
          onMouseEnter={() => onHover(i)}
          className={cn(
            'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm',
            i === activeIndex ? 'bg-accent text-foreground' : 'text-foreground/80',
          )}
          data-testid="mention-menu-item"
        >
          <FileIcon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <span className="truncate font-mono text-xs">{file.path}</span>
        </button>
      ))}
    </div>
  );
}
