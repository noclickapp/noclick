// The numbered steps a key is connected in (KeySteps), and their last one: the form's own button, which the form draws
// with its number in the steps' column when it sits in them, so the steps end on Connect.
import { createContext, useContext, type ReactNode } from 'react';

// The list numbers its items for a screen reader.
const NUMBER =
    'grid h-6 w-6 shrink-0 place-items-center rounded-full text-[12px] font-medium tabular-nums text-foreground ring-1 ring-inset ring-foreground/20';

export function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
    return (
        <li className="flex gap-3.5">
            <span aria-hidden className={`mt-px ${NUMBER}`}>
                {n}
            </span>
            <div className="min-w-0 flex-1">
                <h3 className="mb-2 text-[14.5px] font-medium leading-6 text-foreground">{title}</h3>
                {children}
            </div>
        </li>
    );
}

/** The number the form's button takes when the form is a step's body. */
export const FinalStep = createContext<number | null>(null);

/** The form's button row, numbered as the last step where the form is a step's body: pulled back by the step's gutter
 *  (its number and the gap after it) so the number sits under the others. */
export function FinalStepRow({ children }: { children: ReactNode }) {
    const n = useContext(FinalStep);
    if (n === null) return <>{children}</>;
    return (
        <div className="-ml-[38px] flex items-center gap-3.5 pt-1">
            <span aria-hidden className={NUMBER}>
                {n}
            </span>
            <div className="min-w-0 flex-1">{children}</div>
        </div>
    );
}
