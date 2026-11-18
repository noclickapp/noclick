// What a console acting as a key shows where something only the owner can do would be: why it isn't here.
import { cn } from '@/ui/utils';
import { ownerOnlyWhy, type OwnerOnly } from '../ownerOnly';

export function OwnerOnlyNote({ what, className }: { what: OwnerOnly; className?: string }) {
    return <p className={cn('m-0 text-[13px] leading-relaxed text-muted-foreground', className)}>{ownerOnlyWhy(what)}</p>;
}
