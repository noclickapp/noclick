import { useState } from 'react';

/** True in the render where any of `keys` differs from the last render's, never in the first: what belonged to the
 *  last item is put down while the next one renders (`if (useChanged(item.id)) setRemoving(null);`). Never in an
 *  effect: React runs those after the page is drawn, a task later when a navigation or a read drew it, and a reset
 *  there undid whatever a click in between had set. React's "adjusting some state when a prop changes". */
export function useChanged(...keys: unknown[]): boolean {
    const [seen, setSeen] = useState(keys);
    if (seen.length === keys.length && seen.every((key, i) => Object.is(key, keys[i]))) return false;
    setSeen(keys);
    return true;
}
