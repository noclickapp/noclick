// A step's settings a read held back (its secrets): kept unless something is typed in their place, and shown as such.

export const WITHHELD_PLACEHOLDER = 'Saved, hidden. Type to replace it.';

/** The rows of a list setting (a request's headers, query or form fields) whose value a read held back, by index:
 *  `withheld` names them `headers[0].value`. */
export function withheldRows(withheld: readonly string[] | undefined, key: string): number[] {
    const rows: number[] = [];
    for (const path of withheld ?? []) {
        const match = /^(.+)\[(\d+)\]\.value$/.exec(path);
        if (match && match[1] === key) rows.push(Number(match[2]));
    }
    return rows;
}
