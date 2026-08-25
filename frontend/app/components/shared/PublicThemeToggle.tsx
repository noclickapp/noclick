// Subtle fixed light/dark toggle for themed PUBLIC pages (builder input
// bridge, credential provide). The pages are fully tokenized and listed in
// THEMED_PATH_RE; an unset preference still renders dark like the rest of
// the app.
import { useEffect, useState } from 'react';
import { Moon, Sun } from 'lucide-react';
import { resolveTheme, setTheme } from '~/lib/theme';
import { useTheme } from '~/hooks/useTheme';

export function PublicThemeToggle() {
  const [theme] = useTheme();
  // Read resolved theme client-side only; SSR renders the dark glyph.
  const [resolved, setResolved] = useState<'light' | 'dark'>('dark');
  useEffect(() => { setResolved(resolveTheme()); }, [theme]);
  return (
    <button
      type="button"
      aria-label={resolved === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      onClick={() => setTheme(resolved === 'dark' ? 'light' : 'dark')}
      data-testid="public-theme-toggle"
      className="fixed top-4 right-4 rounded-lg p-2 text-muted-foreground/60 dark:text-zinc-600 transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
    >
      {resolved === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </button>
  );
}
