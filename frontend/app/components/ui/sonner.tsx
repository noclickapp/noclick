// Sonner toast component for displaying dismissible notifications.
// Positioned at bottom-right with proper theming support.

import { Toaster as Sonner } from 'sonner';

type ToasterProps = React.ComponentProps<typeof Sonner>;

const Toaster = ({ ...props }: ToasterProps) => {
    return (
        <Sonner
            className="toaster group"
            position="bottom-right"
            toastOptions={{
                classNames: {
                    toast: 'group toast group-[.toaster]:bg-card group-[.toaster]:border-border group-[.toaster]:text-foreground group-[.toaster]:shadow-lg',
                    // Error toasts get a red-tinted description: the default muted gray
                    // is unreadable on the red-950 dark error background (title survives
                    // via the error class's !text-red-100, the description didn't).
                    description:
                        'group-[.toast]:text-muted-foreground group-data-[type=error]:!text-red-800 dark:group-data-[type=error]:!text-red-200/95',
                    error: 'group-[.toaster]:!bg-red-100 group-[.toaster]:!border-red-300 group-[.toaster]:!text-red-900 dark:group-[.toaster]:!bg-red-950/80 dark:group-[.toaster]:!border-red-800/60 dark:group-[.toaster]:!text-red-100 group-[.toaster]:backdrop-blur-sm',
                    actionButton:
                        'group-[.toast]:bg-primary group-[.toast]:text-primary-foreground',
                    cancelButton:
                        'group-[.toast]:bg-muted dark:group-[.toast]:bg-gray-700 group-[.toast]:text-muted-foreground dark:group-[.toast]:text-gray-300',
                },
            }}
            {...props}
        />
    );
};

export { Toaster };
