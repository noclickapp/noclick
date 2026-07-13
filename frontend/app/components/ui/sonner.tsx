// Sonner toast component for displaying dismissible notifications.
// Positioned at bottom-right with proper theming support.

import { Toaster as Sonner } from "sonner";

type ToasterProps = React.ComponentProps<typeof Sonner>;

const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      className="toaster group"
      position="bottom-right"
      toastOptions={{
        classNames: {
          toast:
            "group toast group-[.toaster]:bg-card group-[.toaster]:border-border group-[.toaster]:text-foreground group-[.toaster]:shadow-lg",
          description: "group-[.toast]:text-muted-foreground",
          error:
            "group-[.toaster]:!bg-red-100 group-[.toaster]:!border-red-300 group-[.toaster]:!text-red-900 dark:group-[.toaster]:!bg-red-950/80 dark:group-[.toaster]:!border-red-800/60 dark:group-[.toaster]:!text-red-100 group-[.toaster]:backdrop-blur-sm",
          actionButton:
            "group-[.toast]:bg-primary group-[.toast]:text-primary-foreground",
          cancelButton:
            "group-[.toast]:bg-muted dark:group-[.toast]:bg-gray-700 group-[.toast]:text-muted-foreground dark:group-[.toast]:text-gray-300",
        },
      }}
      {...props}
    />
  );
};

export { Toaster };
