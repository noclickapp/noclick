// The console's dialog is the app's (`shell/ShellDialog`), with placeholders lifted for the console's surfaces.
import { ShellDialog, type ShellDialogProps } from '@/ui/ShellDialog';
import { cn } from '@/ui/utils';
import { READABLE_PLACEHOLDERS } from './tokens';

export { DIALOG_MARK, DIALOG_OVERLAY as OVERLAY } from '@/ui/ShellDialog';

export type ConsoleDialogProps = ShellDialogProps;

export function ConsoleDialog({ size = 'md', className, ...props }: ConsoleDialogProps) {
    return <ShellDialog size={size} className={cn(READABLE_PLACEHOLDERS, className)} {...props} />;
}
