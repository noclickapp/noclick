# Your own additions

Put what your copy of the app adds here, and leave the app's own files alone: pulling a newer version then changes
nothing of yours. Every `.ts` or `.tsx` file directly in this folder runs once, before any page renders (the root
route imports them all), and nothing else in the app imports from here.

What a file here mostly does is fill a **slot**: a named place in a screen that the app leaves for whoever runs it
(`src/slots.ts`). Each screen lists its slots beside itself, with what stands in each one when nobody fills it:
the console's are in `src/screens/console/slots.ts`.

## An example: your terms under the console's buttons

The console leaves a place under the buttons that make a key or copy the setup prompt (`console.terms`), empty
by default. This puts a line there. Save it as `src/custom/terms.tsx`:

```tsx
import { fill } from '@/slots';
import { TERMS } from '@/screens/console/slots';

function Terms({ action, className }: { action: string; className?: string }) {
    return (
        <p className={className}>
            By {action}, you accept <a href="https://example.com/terms">our terms</a>.
        </p>
    );
}

fill(TERMS, Terms);
```

The slot's type says what a fill must be (here a component taking `action`), so a fill of the wrong shape doesn't
compile. A later fill of the same slot replaces an earlier one.

Files here are part of the app: `pnpm typecheck` checks them, and `test/secrets.test.ts` holds them to the same
rules as every other module (they can't read the environment or the app's key).
