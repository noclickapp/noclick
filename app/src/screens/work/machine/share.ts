// What NoClick uses of a computer of yours (the API's `agent_share`), as Add your computer and its page offer it.

/** The parts a person picks from, least first: the slider's stops, left to right. */
export const SHARES: readonly { value: number; label: string }[] = [
    { value: 0.25, label: 'A quarter' },
    { value: 0.5, label: 'Half' },
    { value: 0.75, label: 'Three quarters' },
    { value: 1, label: 'All of it' },
];

/** A quarter stays yours unless you say otherwise (the API's `own.AGENT_SHARE`). */
export const DEFAULT_SHARE = 0.75;

/** A part's name; one set through the API between stops reads as a percentage. */
export const shareLabel = (share: number) =>
    SHARES.find((s) => s.value === share)?.label ??
    `${Math.round(share * 100)}%`;

/** The stop one step from `share` the way `dir` goes (a part between stops steps to its neighbour), or null past
 *  either end. */
export function stepFrom(share: number, dir: 1 | -1): number | null {
    const next =
        dir > 0
            ? SHARES.find((s) => s.value > share)
            : [...SHARES].reverse().find((s) => s.value < share);
    return next ? next.value : null;
}

const amount = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1));

/** A computer's CPUs and memory split between NoClick and you, as a person reads it: "6 CPUs · 24 GB", and what you
 *  keep, read after "You keep". A Mac's VM is all NoClick's, the rest of the Mac yours. `counting`: on the way to
 *  `share`, in whole numbers as a counter shows them. */
export function splitOf(
    cpu: number,
    memoryGb: number,
    share: number,
    vm: boolean,
    counting = false
): { noclick: string; you: string } {
    const n = (x: number) => (counting ? String(Math.round(x)) : amount(x));
    const of = (part: number) => {
        const cpus = n(cpu * part);
        return `${cpus} ${cpus === '1' ? 'CPU' : 'CPUs'} · ${n(memoryGb * part)} GB`;
    };
    if (vm) return { noclick: of(1), you: 'the rest of the Mac' };
    const you = 1 - share;
    const none =
        you <= 1e-6 ||
        (counting &&
            Math.round(cpu * you) === 0 &&
            Math.round(memoryGb * you) === 0);
    return { noclick: of(share), you: none ? 'nothing' : of(you) };
}
