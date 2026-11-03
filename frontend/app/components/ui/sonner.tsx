// Sonner toast component for displaying dismissible notifications.
// Positioned at bottom-right with proper theming support.

import { Toaster as Sonner } from 'sonner';

type ToasterProps = React.ComponentProps<typeof Sonner>;

// A toast's buttons sit on a row of their own under its text, at the right: beside the text they
// left empty space above and below them. The text's basis leaves room for the icon but not a button.
const BUTTON = 'group-[.toast]:!h-7 group-[.toast]:!rounded-full group-[.toast]:!px-3 group-[.toast]:!text-[13px]';

const Toaster = ({ ...props }: ToasterProps) => {
    return (
        <Sonner
            className="toaster group"
            position="bottom-right"
            toastOptions={{
                classNames: {
                    toast: 'group toast group-[.toaster]:bg-card group-[.toaster]:border-border group-[.toaster]:text-foreground group-[.toaster]:shadow-lg has-[[data-button]]:flex-wrap has-[[data-button]]:!gap-y-3 has-[[data-description]]:!items-start',
                    content: 'group-has-[[data-button]]:flex-[1_1_calc(100%-2rem)]',
                    // Beside a title with a description under it, the icon sits on the title's line.
                    icon: 'group-has-[[data-description]]:mt-[2px]',
                    // Colours here are marked important: sonner styles its toasts as its light
                    // theme (#3f3f3f text, dark buttons) and those rules win over plain classes,
                    // so on the dark card a description and the buttons read as near-black.
                    // Error toasts get a red-tinted description that holds on the red-950 background.
                    description:
                        'group-[.toast]:!text-muted-foreground group-data-[type=error]:!text-red-800 dark:group-data-[type=error]:!text-red-200/95',
                    error: 'group-[.toaster]:!bg-red-100 group-[.toaster]:!border-red-300 group-[.toaster]:!text-red-900 dark:group-[.toaster]:!bg-red-950/80 dark:group-[.toaster]:!border-red-800/60 dark:group-[.toaster]:!text-red-100 group-[.toaster]:backdrop-blur-sm',
                    actionButton: `${BUTTON} group-[.toast]:!bg-primary group-[.toast]:!text-primary-foreground group-has-[[data-cancel]]:!ml-2`,
                    cancelButton: `${BUTTON} group-[.toast]:!bg-secondary group-[.toast]:!text-secondary-foreground`,
                },
            }}
            {...props}
        />
    );
};

export { Toaster };
