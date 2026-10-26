// A file's type as a glyph, apart from the thumbnails so a chat's file card draws it without loading them.
import { Archive, Code2, File, FileText, Film, Image as ImageIcon, Music, Table2 } from 'lucide-react';
import type { FileKind } from '~/components/dashboard/types';
import { cn } from '~/lib/utils';

const GLYPHS: Record<FileKind, typeof File> = {
    image: ImageIcon,
    video: Film,
    audio: Music,
    doc: FileText,
    data: Table2,
    code: Code2,
    archive: Archive,
    other: File,
};

export function FileGlyph({ kind, className }: { kind: FileKind; className?: string }) {
    const Glyph = GLYPHS[kind];
    return <Glyph className={cn('h-4 w-4 shrink-0 text-foreground/65 dark:text-foreground/50', className)} strokeWidth={1.75} />;
}
