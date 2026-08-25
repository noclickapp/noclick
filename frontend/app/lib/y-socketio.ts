import * as Y from 'yjs';
import * as encoding from 'lib0/encoding';
import * as decoding from 'lib0/decoding';
import * as syncProtocol from 'y-protocols/sync';
import { ObservableV2 } from 'lib0/observable';
import { Socket } from 'socket.io-client';
import { sendEvent, YjsSyncRequest } from '~/lib/socket-sender';
import { onSocketEvent } from '~/lib/socket-receiver';
import type { ServerToClientEvents, ClientToServerEvents } from '~/types/socket-events.generated';

/**
 * Reference-compatible message types (similar to y-websocket):
 */
const messageSync = 0;

export class SocketIOProvider extends ObservableV2<Record<string, never>> {
    private doc: Y.Doc;
    private connected: boolean;
    private isListening: boolean = false; // Track if we're listening to doc updates
    private readonly docUpdateHandler: (
        update: Uint8Array,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        origin: any
    ) => void;

    private socket: Socket<ServerToClientEvents, ClientToServerEvents>;

    /**
     * Keep track of whether the doc is fully synced (step 2 completed).
     */
    private _synced: boolean;

    /**
     * Store unsubscribe functions for cleanup
     */
    private unsubscribeFns: (() => void)[] = [];

    // Bound handler refs so destroy() can remove ONLY our listeners via
    // socket.off(event, listener). Calling socket.off(event) with no second
    // arg removes every listener registered for that event — including the
    // SocketReceiver's own connection-state listeners — which left the
    // connection indicator stuck on "connecting" until the next user action
    // triggered a re-derive.
    private readonly onSocketConnect = () => {
        this.connected = true;
        this.sendSyncStep1();
    };
    private readonly onSocketDisconnect = () => {
        this.connected = false;
    };

    /**
     * You can define additional properties / intervals here if you
     * want to perform heartbeats, re-connect logic, etc.
     */

    constructor(doc: Y.Doc, socket: Socket<ServerToClientEvents, ClientToServerEvents> | null) {
        super();
        this.doc = doc;
        this.connected = false;
        this._synced = false;
        if (!socket) {
            throw new Error('Socket is required for SocketIOProvider');
        }
        this.socket = socket;

        // This handler is called whenever the doc changes
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        this.docUpdateHandler = (update: Uint8Array, origin: any) => {
            // Only send doc updates if the change didn't originate from here
            if (origin !== this) {
                // Wrap Yjs update in a sync protocol message (step 2 or update)
                const encoder = encoding.createEncoder();
                encoding.writeVarUint(encoder, messageSync);
                syncProtocol.writeUpdate(encoder, update);

                /**
                 * Send the newly encoded update message to the server (and thus to others).
                 */
                const update_message = encoding.toUint8Array(encoder);
                this.sendMessage(update_message);
            }
        };

        // Start listening to relevant socket events
        this.setupSocketListeners();
    }

    /**
     * Subscribe to socket events using the centralized receiver
     */
    private setupSocketListeners() {
        // IMPORTANT: Check if socket is already connected before adding listeners
        // This prevents a race condition where the provider is created after the socket
        // has already connected, causing the 'connect' event to never fire
        if (this.socket.connected) {
            this.connected = true;
        }

        // Note: 'connect' and 'disconnect' are not in our ServerToClientEvents
        // They're handled by the underlying socket, so we'll keep direct socket access for these
        this.socket.on('connect', this.onSocketConnect);
        this.socket.on('disconnect', this.onSocketDisconnect);

        // Use centralized receiver for yjs:sync events
        const unsubscribeYjsSync = onSocketEvent('yjs:sync', (data: number[]) => {
            // Data comes as number[] from the server
            const uint8Data = new Uint8Array(data);
            this.handleMessage(uint8Data);
        });

        this.unsubscribeFns.push(unsubscribeYjsSync);
    }

    /**
     * Handler for ANY incoming driver-level message that relates to Yjs.
     * It closely follows the structure shown in the y-websocket reference.
     */
    private handleMessage(message: Uint8Array) {
        if (message.length === 0) return;
        const decoder = decoding.createDecoder(message);
        const messageType = decoding.readVarUint(decoder);

        switch (messageType) {
            case messageSync: {
                /**
                 * Sync Step 1 or Step 2 (or Yjs Update). Once readSyncMessage
                 * processes the content, if there's a response, we collect
                 * that in "encoder" and send it back.
                 */
                const encoder = encoding.createEncoder();
                syncProtocol.readSyncMessage(decoder, encoder, this.doc, this);

                /**
                 * If readSyncMessage generates a reply (Sync Step 2 in response to Step 1,
                 * or a state vector, etc.), we send it.
                 */
                if (encoding.length(encoder) > 0) {
                    const sync_step_2_message = new Uint8Array([
                        0,
                        ...encoding.toUint8Array(encoder),
                    ]);
                    this.sendMessage(sync_step_2_message);
                }
                /**
                 * If we've just completed Step 2 for the first time, we mark ourselves synced.
                 * In y-websocket, we check if the message was specifically "sync step 2" to do so.
                 * For brevity here, you can set this._synced = true once you consider sync final.
                 */
                this._synced = true;
                break;
            }

            default:
                console.error('Unknown message type:', messageType);
        }
    }

    /**
     * Send a raw message through the socket, used heavily by handleMessage above.
     */
    private sendMessage(encodedMessage: Uint8Array) {
        // Only send if connected to prevent queuing messages during disconnection
        if (!this.connected || !this.socket.connected) {
            console.warn('[SocketIOProvider] Skipping sendMessage - not connected');
            return;
        }
        sendEvent(YjsSyncRequest.create(encodedMessage));
    }

    /**
     * Send an initial sync step 1 on (re)connection, so other peers can send us step 2.
     */
    private sendSyncStep1() {
        const encoder = encoding.createEncoder();
        encoding.writeVarUint(encoder, messageSync);
        syncProtocol.writeSyncStep1(encoder, this.doc);
        const sync_step_1_message = encoding.toUint8Array(encoder);
        this.sendMessage(sync_step_1_message);
    }

    /**
     * Hook up doc to our update handler when connecting.
     */
    connect() {
        // Prevent duplicate listeners
        if (this.isListening) {
            console.warn('[SocketIOProvider] Already listening to doc updates');
            return;
        }

        this.doc.on('update', this.docUpdateHandler);
        this.isListening = true;

        // Only send sync if socket is actually connected
        if (this.socket.connected) {
            this.sendSyncStep1();
        }
        // Otherwise, the 'connect' event handler will send sync step 1
    }

    /**
     * Remove the doc listener and consider ourselves disconnected.
     */
    disconnect() {
        if (this.isListening) {
            this.doc.off('update', this.docUpdateHandler);
            this.isListening = false;
        }
        this.connected = false;
        this._synced = false;
        // Optionally set awareness to null states, etc.
    }

    destroy() {
        this.disconnect();
        // Pass the specific listener refs so only OUR handlers are removed.
        // The bare-event form (socket.off('connect')) would also drop the
        // SocketReceiver's connection-tracking listeners and break the
        // connection indicator on every provider tear-down.
        this.socket.off('connect', this.onSocketConnect);
        this.socket.off('disconnect', this.onSocketDisconnect);

        // Clean up centralized receiver subscriptions
        this.unsubscribeFns.forEach(fn => fn());
        this.unsubscribeFns = [];

        super.destroy();
    }

    /**
     * For reference, in y-websocket we have a "synced" property that fires events.
     * You can replicate that style if you want:
     */
    get synced() {
        return this._synced;
    }
}
