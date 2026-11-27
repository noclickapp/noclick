// Every sign-in and connect window the app opens is opened here, inside the click that asks for it. A window opened
// after an await (the server naming the sign-in page, a start call, a lookup) is a pop-up nobody asked for by the time
// it opens, and browsers block it: Safari after about a second, Chrome and Firefox after five. So the window opens now,
// blank where its address isn't known yet, and the flow points it there, posts into it, or closes it once it knows.
// Nothing else calls `window.open(` for a sign-in.

export interface SignInWindowOptions {
    /** Where it opens, when the click already knows; left out, it opens blank for `go` or `post` to fill. */
    url?: string;
    /** Its name, which a later attempt finds the same window by. A new tab when left out. */
    name?: string;
    /** A popup of this size, centred on this window, instead of a tab. A popup keeps its opener, which its callback
     *  page posts the result to; a tab drops it, so another site's page can't reach this one. */
    popup?: { width: number; height: number };
}

export interface SignInWindow {
    /** The window, or null where the browser refused it. */
    readonly window: Window | null;
    /** Points it at the sign-in page. False when there's nothing to point: refused, or closed by the person. */
    go: (url: string) => boolean;
    /** Submits the fields to `action` in it as a POST, so a secret rides the body rather than the URL. */
    post: (action: string, fields: Record<string, string | undefined>) => void;
    close: () => void;
}

const openWindow = (url: string, name: string, features?: string) =>
    features ? window.open(url, name, features) : window.open(url, name);

// A window a click opened for a sign-in it can only name after an await (an embedded app asking for an account): the
// next sign-in window opened takes it instead of opening its own.
let held: Window | null = null;

/** Opens a sign-in or connect window now, inside the click. Every flow opens its window through this. */
export function openTabForLater(options: SignInWindowOptions = {}): SignInWindow {
    const { url = 'about:blank', name = '_blank', popup } = options;
    const taken = held && !held.closed ? held : null;
    held = null;
    let opened: Window | null;
    if (taken) {
        opened = taken;
        if (name !== '_blank') opened.name = name;
        if (!popup) opened.opener = null;
        if (url !== 'about:blank') opened.location.href = url;
    } else {
        const features = popup && popupFeatures(popup.width, popup.height);
        opened = openWindow(url, name, features);
        if (opened && !popup) opened.opener = null;
    }
    const usable = () => !!opened && !opened.closed;
    return {
        window: opened,
        go: (to) => {
            if (!usable()) return false;
            opened!.location.href = to;
            return true;
        },
        post: (action, fields) => {
            if (!opened) return;
            // A form targets a window by its name, so a window opened without one gets one of its own.
            if (!opened.name) opened.name = `sign-in-${Date.now()}-${Math.random().toString(36).slice(2)}`;
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = action;
            form.target = opened.name;
            form.hidden = true;
            for (const [field, value] of Object.entries(fields)) {
                if (value === undefined) continue;
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = field;
                input.value = value;
                form.appendChild(input);
            }
            document.body.appendChild(form);
            try {
                form.submit();
            } catch (error) {
                opened.close();
                throw error;
            } finally {
                form.remove();
            }
        },
        close: () => {
            if (usable()) opened!.close();
        },
    };
}

/** Calls `onClosed` once the person has closed a sign-in window: it reads closed and they're back on this page (it
 *  regains focus or comes back into view, or they click or type in it). A sign-in page that sets
 *  Cross-Origin-Opener-Policy cuts its window off from this page, which from then on reads it as closed while the
 *  person is still signing in there, so a closed reading alone ends nothing. Returns what stops the watch. */
export function whenClosed(signIn: Window, onClosed: () => void): () => void {
    // Whether the person is on this page. Opening the window took them away from it.
    let here = false;
    const check = () => {
        let closed: boolean;
        try {
            closed = signIn.closed;
        } catch {
            closed = true;
        }
        if (!here || !closed) return;
        stop();
        onClosed();
    };
    const back = () => {
        here = true;
        check();
    };
    const away = () => {
        here = false;
    };
    const seen = () => (document.visibilityState === 'visible' ? back() : away());
    const poll = setInterval(check, 500);
    window.addEventListener('focus', back);
    window.addEventListener('blur', away);
    window.addEventListener('pointerdown', back, true);
    window.addEventListener('keydown', back, true);
    document.addEventListener('visibilitychange', seen);
    function stop() {
        clearInterval(poll);
        window.removeEventListener('focus', back);
        window.removeEventListener('blur', away);
        window.removeEventListener('pointerdown', back, true);
        window.removeEventListener('keydown', back, true);
        document.removeEventListener('visibilitychange', seen);
    }
    return stop;
}

/** For a click whose sign-in is only known after an await (an embedded app asking for an account): opens a sign-in
 *  popup now, while the click counts, for the next sign-in window to take. The returned release closes it if nothing
 *  took it. */
export function holdSignInWindow(): () => void {
    const { window: popup } = openTabForLater({ popup: { width: 500, height: 700 } });
    held = popup;
    return () => {
        if (held !== popup) return;
        held = null;
        if (popup && !popup.closed) popup.close();
    };
}

/** Puts a device-code sign-in's code on the clipboard once its start names it, true when it's there. Called in the
 *  click, before the sign-in tab opens: Safari takes a write only while the click counts, and Chrome only while this
 *  page has focus, which the new tab takes. So the write starts now, holding the code to come. */
export function copyWhenKnown(text: Promise<string | null | undefined>): Promise<boolean> {
    const known = text.then((value) => {
        if (!value) throw new Error('No code to copy');
        return value;
    });
    // A start that names no code copies nothing; its own caller says why.
    known.catch(() => undefined);
    const clipboard = typeof navigator === 'undefined' ? undefined : navigator.clipboard;
    if (!clipboard) return Promise.resolve(false);
    try {
        let writing: Promise<unknown>;
        if (typeof ClipboardItem !== 'undefined' && clipboard.write) {
            const blob = known.then((value) => new Blob([value], { type: 'text/plain' }));
            blob.catch(() => undefined);
            writing = clipboard.write([new ClipboardItem({ 'text/plain': blob })]);
        } else {
            writing = known.then((value) => clipboard.writeText(value));
        }
        return writing.then(
            () => true,
            () => false
        );
    } catch {
        return Promise.resolve(false);
    }
}

function popupFeatures(width: number, height: number): string {
    const left = window.screenX + (window.outerWidth - width) / 2;
    const top = window.screenY + (window.outerHeight - height) / 2;
    return `width=${width},height=${height},left=${left},top=${top},popup=yes`;
}

interface OAuthPostPopupOptions {
    action: string;
    name: string;
    fields: Record<string, string | undefined>;
    width?: number;
    height?: number;
}

/** Open an OAuth popup and submit sensitive setup values in a POST body. */
export function openOAuthPostPopup({ action, name, fields, width = 500, height = 700 }: OAuthPostPopupOptions): Window | null {
    const signIn = openTabForLater({
        name: `${name}-${Date.now()}-${Math.random().toString(36).slice(2)}`,
        popup: { width, height },
    });
    if (!signIn.window) return null;
    signIn.post(action, fields);
    return signIn.window;
}
