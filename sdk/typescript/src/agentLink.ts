/**
 * AgentLink: an agent step's public chat page, as its visitor talks through it. The link is the capability, so it
 * takes no key: a public page talks to the agent with it alone.
 */

import { NoClick } from "./client.ts";
import { asList, asObject, str } from "./object.ts";
import type { JsonObject } from "./object.ts";
import { Room, pageOrigin, roomTokenOf } from "./room.ts";
import type { RoomJoinOptions, RoomToken } from "./room.ts";

/** The header naming the visitor: the id their browser keeps, never in a URL. */
const VISITOR_HEADER = "NoClick-Visitor";

/** A visitor's thread with the agent: its conversation's id and its messages, oldest first. */
export interface AgentLinkThread {
  conversation: string;
  messages: JsonObject[];
}

/**
 * An agent step's public chat page (`/a/{id}`), as one visitor talks through it. Anyone holding the link talks to the
 * agent, billed to the workflow's owner, who turns it off or rotates it from the step's share link. A visitor is named
 * by an id their browser keeps (a UUID), and each of their threads by a `chat` key; they read their own threads alone.
 *
 *     const link = new AgentLink(linkId, { visitor: localStorage.visitorId });
 *     const room = await link.join();
 *     room.on("event", (event) => console.log(event.event, event.data)); // chat:message, agent:state
 *     await link.send("Do you ship to Canada?");
 *     const { messages } = await link.thread();
 */
export class AgentLink {
  readonly id: string;
  readonly visitor: string;
  readonly #client: NoClick;

  /** `baseUrl`: the API's (`NOCLICK_API_URL`, then `https://api.noclick.com`); `fetch`: a custom one. */
  constructor(id: string, options: { visitor: string; baseUrl?: string; fetch?: typeof fetch }) {
    this.id = id;
    this.visitor = options.visitor;
    this.#client = new NoClick({
      apiKey: "", baseUrl: options.baseUrl, fetch: options.fetch, headers: { [VISITOR_HEADER]: options.visitor },
    });
  }

  #path(suffix = "messages"): string {
    return `/v1/public/agent_links/${encodeURIComponent(this.id)}/${suffix}`;
  }

  /**
   * Say something to the agent in the visitor's thread `chat` (`main` by default; a new key starts a new thread). It
   * resolves once the agent's turn is under way; read its reply back with `thread()`. Rejects with `Conflict`
   * (`details.reason` `busy`) while the thread's last message is still being handed to the agent, `NotAvailable`
   * when the agent can't take a turn, and `NotFound` once the link is off.
   */
  async send(text: string, options: { chat?: string } = {}): Promise<{ conversation: string }> {
    const raw = asObject(await this.#client.request("POST", this.#path(), {
      json: { text, chat: options.chat ?? "main" }, user: null, anonymous: true,
    }));
    return { conversation: str(raw.conversation) ?? "" };
  }

  /**
   * A single-use token for the room of the visitor's thread `chat` (`main` by default), where its turns' frames
   * (`chat:message`, `agent:state`) arrive as they happen. View-only. `join` asks for one itself.
   */
  async roomToken(options: { chat?: string; origin?: string } = {}): Promise<RoomToken> {
    const origin = options.origin ?? pageOrigin();
    return roomTokenOf(asObject(await this.#client.request("POST", this.#path("room"), {
      json: { chat: options.chat ?? "main", ...(origin ? { origin } : {}) }, user: null, anonymous: true,
    })));
  }

  /**
   * Joins the room of the visitor's thread `chat` (`main` by default): its turns stream there as they happen, as
   * `event`s named `chat:message` and `agent:state`. It reconnects by itself, resuming after the last frame it gave.
   */
  async join(options: { chat?: string } & Pick<RoomJoinOptions, "signal" | "onStatus" | "WebSocket"> = {}): Promise<Room> {
    const { chat, ...rest } = options;
    return Room.join(`agent_link:${this.id}`, {
      ...rest, token: async () => this.roomToken({ chat }),
    });
  }

  /** The visitor's thread `chat` (`main` by default), as the page shows it. */
  async thread(options: { chat?: string } = {}): Promise<AgentLinkThread> {
    const raw = asObject(await this.#client.request("GET", this.#path(), {
      query: { chat: options.chat ?? "main" }, user: null, anonymous: true,
    }));
    return { conversation: str(raw.conversation) ?? "", messages: asList(raw.messages).map(asObject) };
  }
}
