// The theme picker: system, light or dark, as three icon buttons in one pill. The account menu and the themed
// marketing pages' footer share it.
import { useEffect, useState } from 'react';
import { Monitor, Moon, Sun } from 'lucide-react';
import { useTheme } from '~/hooks/useTheme';
import { cn } from '~/lib/utils';

const THEME_OPTIONS = [
    { value: 'system', icon: Monitor, label: 'System theme' },
    { value: 'light', icon: Sun, label: 'Light theme' },
    { value: 'dark', icon: Moon, label: 'Dark theme' },
] as const;

export function ThemeSwitch({ className }: { className?: string }) {
    const [theme, setTheme] = useTheme();
    // The stored choice is only known in the browser, so the server-rendered pill marks nothing.
    const [mounted, setMounted] = useState(false);
    useEffect(() => setMounted(true), []);

    return (
        <div className={cn('flex items-center gap-0.5 rounded-full border border-border bg-accent p-0.5 dark:bg-secondary/60', className)}>
            {THEME_OPTIONS.map(({ value, icon: Icon, label }) => {
                const picked = mounted && theme === value;
                return (
                    <button
                        key={value}
                        type="button"
                        onClick={(e) => {
                            e.stopPropagation();
                            setTheme(value);
                        }}
                        aria-label={label}
                        aria-pressed={picked}
                        className={cn(
                            'rounded-full p-1 transition-colors',
                            picked
                                ? 'bg-card text-foreground shadow-sm dark:bg-muted-foreground/30 dark:shadow-none'
                                : 'text-muted-foreground hover:text-foreground dark:text-white/60'
                        )}
                    >
                        <Icon className="h-3.5 w-3.5" />
                    </button>
                );
            })}
        </div>
    );
}
