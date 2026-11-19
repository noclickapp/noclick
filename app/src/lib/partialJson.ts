// Reads JSON that may have been cut off part-way, as tool-call previews are (the wire and the transcript keep a
// bounded prefix). Everything that arrived whole is returned; a value the cut went through is dropped rather than
// guessed at, so a truncated string never passes for a real one (half a URL is worse than none). Objects and arrays
// the cut went through keep the entries they finished.

interface Parsed {
    value: unknown;
    /** False when the input ended inside this value. */
    whole: boolean;
}

const CUT: Parsed = { value: undefined, whole: false };

class Reader {
    i = 0;
    constructor(readonly src: string) {}

    skip() {
        while (this.i < this.src.length && /\s/.test(this.src[this.i])) this.i++;
    }

    value(): Parsed | null {
        this.skip();
        if (this.i >= this.src.length) return CUT;
        const c = this.src[this.i];
        if (c === '{') return this.object();
        if (c === '[') return this.array();
        if (c === '"') return this.string();
        if (c === 't') return this.literal('true', true);
        if (c === 'f') return this.literal('false', false);
        if (c === 'n') return this.literal('null', null);
        if (c === '-' || (c >= '0' && c <= '9')) return this.number();
        return null;
    }

    literal(word: string, value: unknown): Parsed | null {
        const got = this.src.slice(this.i, this.i + word.length);
        if (got === word) {
            this.i += word.length;
            return { value, whole: true };
        }
        return word.startsWith(got) && this.i + got.length === this.src.length ? CUT : null;
    }

    number(): Parsed | null {
        const m = /^-?\d+(\.\d+)?([eE][+-]?\d+)?/.exec(this.src.slice(this.i));
        if (!m) return this.i + 1 >= this.src.length ? CUT : null;
        this.i += m[0].length;
        // A number that runs to the end may have lost digits.
        return this.i >= this.src.length ? CUT : { value: Number(m[0]), whole: true };
    }

    string(): Parsed | null {
        let j = this.i + 1;
        while (j < this.src.length) {
            const c = this.src[j];
            if (c === '\\') j += 2;
            else if (c === '"') {
                const raw = this.src.slice(this.i, j + 1);
                this.i = j + 1;
                try {
                    return { value: JSON.parse(raw) as string, whole: true };
                } catch {
                    return null;
                }
            } else j++;
        }
        this.i = this.src.length;
        return CUT;
    }

    array(): Parsed | null {
        this.i++;
        const out: unknown[] = [];
        for (;;) {
            this.skip();
            if (this.i >= this.src.length) return { value: out, whole: false };
            if (this.src[this.i] === ']') {
                this.i++;
                return { value: out, whole: true };
            }
            const item = this.value();
            if (item === null) return null;
            if (!item.whole) {
                if (item.value !== undefined) out.push(item.value);
                return { value: out, whole: false };
            }
            out.push(item.value);
            this.skip();
            if (this.src[this.i] === ',') this.i++;
            else if (this.i < this.src.length && this.src[this.i] !== ']') return null;
        }
    }

    object(): Parsed | null {
        this.i++;
        const out: Record<string, unknown> = {};
        for (;;) {
            this.skip();
            if (this.i >= this.src.length) return { value: out, whole: false };
            if (this.src[this.i] === '}') {
                this.i++;
                return { value: out, whole: true };
            }
            if (this.src[this.i] !== '"') return null;
            const key = this.string();
            if (key === null) return null;
            if (!key.whole) return { value: out, whole: false };
            this.skip();
            if (this.i >= this.src.length) return { value: out, whole: false };
            if (this.src[this.i] !== ':') return null;
            this.i++;
            const item = this.value();
            if (item === null) return null;
            if (!item.whole) {
                // A cut container keeps what it finished; a cut scalar is dropped.
                if (item.value !== undefined) out[key.value as string] = item.value;
                return { value: out, whole: false };
            }
            out[key.value as string] = item.value;
            this.skip();
            if (this.src[this.i] === ',') this.i++;
            else if (this.i < this.src.length && this.src[this.i] !== '}') return null;
        }
    }
}

/** The JSON value `src` starts with, keeping only what arrived whole; undefined when it isn't JSON at all. */
export function parsePartialJson(src: string): unknown {
    const parsed = new Reader(src).value();
    return parsed?.value;
}
