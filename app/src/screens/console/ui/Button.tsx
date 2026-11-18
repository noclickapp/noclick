// Console buttons, NoClick's pills: one primary per view, everything else soft
// or ghost; the destructive confirm is a red outline.
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { cn } from '@/ui/utils';

export type ButtonVariant = 'primary' | 'soft' | 'ghost' | 'danger';

const VARIANTS: Record<ButtonVariant, string> = {
    primary: 'bg-primary text-primary-foreground hover:bg-primary/90',
    soft: 'bg-foreground/[0.07] text-foreground hover:bg-foreground/[0.12]',
    ghost: 'text-foreground/70 hover:bg-foreground/[0.05] hover:text-foreground',
    danger: 'border border-red-600/40 text-red-600 hover:bg-red-500/10 dark:border-red-400/40 dark:text-red-400',
};

const SIZES = { sm: 'h-7 px-3 text-[12px]', md: 'h-8 px-3.5 text-[13px]', icon: 'h-7 w-7 justify-center' } as const;

export interface ConsoleButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
    variant?: ButtonVariant;
    size?: keyof typeof SIZES;
    icon?: ReactNode;
}

/** The button look for a link that navigates (a `<Link>` never wraps a `<button>`). */
export function consoleButtonClass(variant: ButtonVariant = 'soft', size: keyof typeof SIZES = 'md', className?: string): string {
    return cn(
        'inline-flex shrink-0 items-center gap-1.5 rounded-full font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50',
        VARIANTS[variant],
        SIZES[size],
        className
    );
}

export const ConsoleButton = forwardRef<HTMLButtonElement, ConsoleButtonProps>(function ConsoleButton(
    { variant = 'soft', size = 'md', icon, className, children, type = 'button', ...props },
    ref
) {
    return (
        <button ref={ref} type={type} className={consoleButtonClass(variant, size, className)} {...props}>
            {icon}
            {children}
        </button>
    );
});
