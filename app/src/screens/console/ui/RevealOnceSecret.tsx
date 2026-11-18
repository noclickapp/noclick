import type { ReactNode } from 'react';
import { ConsoleButton } from './Button';
import { ConsoleDialog } from './ConsoleDialog';

/**
 * A secret shown exactly once. Open while `secret` is set; there is no ✕,
 * Escape and outside clicks do nothing, and Done is the only exit: the parent
 * clears the secret in `onDone`, so it leaves the page with the dialog.
 */
export function RevealOnceSecret({
    secret,
    title,
    description = "This is the only time you'll see this key.",
    onDone,
    children,
}: {
    secret: string | null;
    title: ReactNode;
    description?: ReactNode;
    onDone: () => void;
    children: (secret: string) => ReactNode;
}) {
    return (
        <ConsoleDialog
            open={secret !== null}
            onOpenChange={() => undefined}
            dismissible={false}
            size="lg"
            title={title}
            description={description}
            footer={
                <ConsoleButton variant="primary" onClick={onDone}>
                    Done
                </ConsoleButton>
            }
        >
            {secret !== null && children(secret)}
        </ConsoleDialog>
    );
}
