// A live browser through NoClick's viewer: the page's size and then a JPEG picture each time it changes, and, where a
// person drives it, their taps, drags, scrolls, typing and keys. It comes one of two ways. A browser read through the
// platform client is shown through the SDK's view (`browser.view`: a single-use token per socket, sent as its first
// message), watching it, or driving it while its reader holds it (`control`, once taken over). A browser shared by a
// link is shown through whatever connection its host makes for the link (`connect`). A thumbnail (`thumb`) is smaller
// and slower, and only watches.
//
// Every view of one browser at one size on the page shares one feed. It drives the browser while any of its views
// asks to (and watches otherwise), switching without a gap: the new socket opens beside the old, which closes once
// the new one shows the page. A browser handed back ends its driving socket, and the feed watches again. It is open
// only while the page is visible (a background tab watches nothing), it reconnects after a dropped connection, and it
// stops for good when the browser or the link does (closed, finished, expired), which is when `onEnded` runs.
import { useCallback, useEffect, useRef, useSyncExternalStore } from 'react';
import type { Browser, BrowserViewConnectOptions } from 'noclick';

/** The SDK view's close for a driving view whose browser was handed back, and for a token it wasn't given (0). */
const RELEASED = 4409;
const NOT_GIVEN = 0;

export type ViewState = 'connecting' | 'live' | 'ended';

export interface Viewport {
    width: number;
    height: number;
}

/** What a person does, in the page's CSS pixels. */
export type ViewInput =
    | { type: 'tap'; x: number; y: number }
    | { type: 'mouse'; action: 'down' | 'up' | 'move'; x: number; y: number }
    | { type: 'scroll'; x: number; y: number; dx: number; dy: number }
    | { type: 'text'; text: string }
    | { type: 'key'; key: string };

/** Opens a link's own connection to its browser: it tells `heard` what it shows, and takes input at full size. */
export type LinkConnector = (linkId: string, thumb: boolean, heard: Heard) => Connection;

/** Where a view's pictures come from: a browser read through the platform client, or a shared link's browser, through
 *  the connection its host opens for it. */
export type BrowserViewSource = { browser: Browser } | { linkId: string; connect: LinkConnector };

export interface BrowserView {
    state: ViewState;
    /** The latest picture, as an object URL. */
    picture: string | null;
    viewport: Viewport | null;
    send: (input: ViewInput) => void;
}

type Shown = Omit<BrowserView, 'send'>;

/** What a connection tells its feed. */
export interface Heard {
    viewport: (viewport: Viewport) => void;
    picture: (jpeg: Blob) => void;
    dropped: () => void;
    ended: (code: number) => void;
}

/** One connection of a feed. */
export interface Connection {
    control: boolean;
    send: (input: ViewInput) => void;
    close: () => void;
}

/** An SDK view's callbacks, telling `heard` what it shows (each picture a JPEG blob); a host's link connection over the
 *  SDK's view of the link passes them on too. */
export function viewOptionsFor(heard: Heard): BrowserViewConnectOptions {
    return {
        onViewport: heard.viewport,
        onPicture: (jpeg) => heard.picture(new Blob([jpeg as BlobPart], { type: 'image/jpeg' })),
        onState: (state) => state === 'connecting' && heard.dropped(),
        onEnd: ({ code }) => heard.ended(code),
    };
}

/** The SDK's view of a browser read through the platform client: it asks for a token for each socket itself. */
function browserConnection(browser: Browser, control: boolean, thumb: boolean, heard: Heard): Connection {
    const view = browser.view({ control, thumb: control ? false : thumb, ...viewOptionsFor(heard) });
    return { control, send: (input) => view.send(input), close: () => view.close() };
}

/** One browser's pictures at one size, for every view of it on the page. */
class Feed {
    shown: Shown = { state: 'connecting', picture: null, viewport: null };
    private readonly listeners = new Set<() => void>();
    private readonly endings = new Set<() => void>();
    /** Which views ask to drive it. */
    private readonly driving = new Set<symbol>();
    private current: Connection | null = null;
    /** A socket opening in the current one's place: it takes over once it shows the page. */
    private next: Connection | null = null;
    /** Handed back while a view still asked to drive it: it watches until no view asks. */
    private released = false;
    private stopped = false;

    constructor(
        private readonly source: BrowserViewSource,
        private readonly thumb: boolean,
        private readonly forget: () => void
    ) {
        document.addEventListener('visibilitychange', this.onVisibility);
    }

    /** A view of it, driving it (`control`) or watching: the first one opens its socket. */
    subscribe(listener: () => void, onEnded: () => void, view: symbol, control: boolean): () => void {
        this.listeners.add(listener);
        this.endings.add(onEnded);
        this.drive(view, control);
        this.open();
        return () => {
            this.listeners.delete(listener);
            this.endings.delete(onEnded);
            this.drive(view, false);
            if (!this.listeners.size) this.stop();
        };
    }

    /** A view asks to drive the browser (`on`), or only to watch it. */
    drive(view: symbol, on: boolean): void {
        if (on) this.driving.add(view);
        else this.driving.delete(view);
        if (!this.driving.size) this.released = false;
        this.switchIfWanted();
    }

    /** What a person does goes to the socket that drives the browser and shows its page: while it switches to one,
     *  nowhere (the picture on screen is the watching socket's). */
    send(input: ViewInput): void {
        if (this.current?.control) this.current.send(input);
    }

    /** Whether its sockets should drive the browser now. */
    private get wantsControl(): boolean {
        return 'browser' in this.source && !this.thumb && this.driving.size > 0 && !this.released;
    }

    private set(change: Partial<Shown>): void {
        this.shown = { ...this.shown, ...change };
        this.listeners.forEach((listener) => listener());
    }

    private connect(control: boolean): Connection {
        let connection: Connection | null = null;
        const isCurrent = () => connection !== null && connection === this.current;
        const heard: Heard = {
            viewport: (viewport) => {
                if (isCurrent()) this.set({ viewport });
            },
            picture: (jpeg) => {
                if (connection === this.next) {
                    // The new socket shows the page: it takes over, and the old one closes.
                    this.current?.close();
                    this.current = connection;
                    this.next = null;
                }
                if (!isCurrent()) return;
                const before = this.shown.picture;
                this.set({ state: 'live', picture: URL.createObjectURL(jpeg) });
                if (before) URL.revokeObjectURL(before);
            },
            dropped: () => {
                if (isCurrent()) this.set({ state: 'connecting' });
            },
            ended: (code) => this.ended(connection!, code),
        };
        connection =
            'browser' in this.source
                ? browserConnection(this.source.browser, control, this.thumb, heard)
                : this.source.connect(this.source.linkId, this.thumb, heard);
        return connection;
    }

    /** Open its socket, saying so (`connecting`) unless it goes on from what it shows (`keepShowing`). */
    private open(keepShowing = false): void {
        if (this.stopped || document.visibilityState === 'hidden' || this.current) return;
        if (!keepShowing) this.set({ state: 'connecting' });
        this.current = this.connect(this.wantsControl);
    }

    /** Open a socket of the kind the views ask for, beside the current one, if it isn't that kind. */
    private switchIfWanted(): void {
        // A link's socket is the one kind there is: it takes input at full size.
        if (this.stopped || !this.current || !('browser' in this.source)) return;
        const wanted = this.wantsControl;
        if (this.next) {
            if (this.next.control === wanted) return;
            this.next.close();
            this.next = null;
        }
        if (this.current.control !== wanted) this.next = this.connect(wanted);
    }

    private ended(connection: Connection, code: number): void {
        if (connection === this.next) {
            this.next = null;
            if (connection.control && (code === RELEASED || code === NOT_GIVEN)) this.released = true;
            else this.finish();
            return;
        }
        if (connection !== this.current) return;
        if (connection.control && (code === RELEASED || code === NOT_GIVEN)) {
            // Handed back (or no longer held when it asked): it watches again, from the picture it showed last.
            this.released = true;
            this.current = this.next && !this.next.control ? this.next : null;
            this.next = null;
            this.open(true);
            return;
        }
        this.finish();
    }

    private finish(): void {
        this.stop();
        this.set({ state: 'ended' });
        this.endings.forEach((ended) => ended());
    }

    private readonly onVisibility = (): void => {
        if (document.visibilityState === 'hidden') {
            this.next?.close();
            this.current?.close();
            this.next = this.current = null;
        } else if (this.listeners.size) {
            this.open();
        }
    };

    private stop(): void {
        if (this.stopped) return;
        this.stopped = true;
        this.forget();
        document.removeEventListener('visibilitychange', this.onVisibility);
        this.next?.close();
        this.current?.close();
        this.next = this.current = null;
        if (this.shown.picture) URL.revokeObjectURL(this.shown.picture);
    }
}

const FEEDS = new Map<string, Feed>();

function feedFor(source: BrowserViewSource, thumb: boolean): Feed {
    const key = `${'browser' in source ? `browser:${source.browser.id}` : `link:${source.linkId}`}:${thumb ? 'thumb' : 'full'}`;
    let feed = FEEDS.get(key);
    if (!feed) {
        feed = new Feed(source, thumb, () => FEEDS.delete(key));
        FEEDS.set(key, feed);
    }
    return feed;
}

const NOT_YET: Shown = { state: 'connecting', picture: null, viewport: null };

/** A browser live; `control`: this view drives it (a browser read through the platform client, while its reader
 *  holds it), else it watches. */
export function useBrowserView(
    source: BrowserViewSource,
    { onEnded, thumb = false, control = false }: { onEnded?: () => void; thumb?: boolean; control?: boolean } = {}
): BrowserView {
    const ended = useRef(onEnded);
    ended.current = onEnded;
    const feed = useRef<Feed | null>(null);
    const self = useRef(Symbol('view'));
    const driving = useRef(control);
    driving.current = control;
    const browser = 'browser' in source ? source.browser : null;
    const linkId = 'linkId' in source ? source.linkId : null;
    // The browser object changes with every read of it: the feed follows its id (any read of it asks for its tokens).
    const latest = useRef(source);
    latest.current = source;
    const subscribe = useCallback(
        (listener: () => void) => {
            const current = feedFor(latest.current, thumb);
            feed.current = current;
            const unsubscribe = current.subscribe(listener, () => ended.current?.(), self.current, driving.current);
            listener();
            return () => {
                unsubscribe();
                if (feed.current === current) feed.current = null;
            };
        },
        [browser?.id, linkId, thumb] // eslint-disable-line react-hooks/exhaustive-deps
    );
    const shown = useSyncExternalStore(subscribe, () => feed.current?.shown ?? NOT_YET, () => NOT_YET);
    useEffect(() => feed.current?.drive(self.current, control), [control]);
    const send = useCallback((input: ViewInput) => feed.current?.send(input), []);
    return { ...shown, send };
}
