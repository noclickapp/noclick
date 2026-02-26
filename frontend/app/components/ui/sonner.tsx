// Sonner toast component for displaying dismissible notifications.
// Positioned at bottom-right with proper theming support.

import { Toaster as Sonner } from "sonner";

type ToasterProps = React.ComponentProps<typeof Sonner>;

const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      theme="dark"
      className="toaster group"
      position="bottom-right"
      toastOptions={{
        style: {
          backgroundColor: '#282725',
          borderColor: '#404040',
          color: 'white'
        },
        classNames: {
          toast:
            "group toast group-[.toaster]:text-white group-[.toaster]:shadow-lg",
          error:
            "group-[.toaster]:!bg-red-950 group-[.toaster]:!border-red-800 group-[.toaster]:!text-red-200",
          description: "group-[.toast]:text-gray-300",
          actionButton:
            "group-[.toast]:bg-white group-[.toast]:text-black",
          cancelButton:
            "group-[.toast]:bg-gray-700 group-[.toast]:text-gray-300",
        },
      }}
      {...props}
    />
  );
};

export { Toaster };