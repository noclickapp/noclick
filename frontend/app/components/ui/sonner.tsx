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
                    // Colours here are marked important: sonner styles its toasts as its light
                    // theme (#3f3f3f text, dark buttons) and those rules win over plain classes,
                    // so on the dark card a description and the buttons read as near-black.
                    // Error toasts get a red-tinted description that holds on the red-950 background.
                    description:
                        'group-[.toast]:!text-muted-foreground group-data-[type=error]:!text-red-800 dark:group-data-[type=error]:!text-red-200/95',
                    error: 'group-[.toaster]:!bg-red-100 group-[.toaster]:!border-red-300 group-[.toaster]:!text-red-900 dark:group-[.toaster]:!bg-red-950/80 dark:group-[.toaster]:!border-red-800/60 dark:group-[.toaster]:!text-red-100 group-[.toaster]:backdrop-blur-sm',
                    actionButton:
                        'group-[.toast]:!rounded-full group-[.toast]:!bg-primary group-[.toast]:!text-primary-foreground',
                    cancelButton:
                        'group-[.toast]:!rounded-full group-[.toast]:!bg-secondary group-[.toast]:!text-secondary-foreground',
                },
            }}
            {...props}
        />
    );
};

export { Toaster };
