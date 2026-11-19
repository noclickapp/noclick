// The agent team a QA account asked for over WhatsApp (2026-10-27): "one agent finds dog-friendly events in Austin
// each week, another writes my clients a newsletter from them. Put them in a channel and run it once." As /v1 reads it
// back: the owner thread's first turn, whose saved calls keep a long call's arguments as {"_truncated": true} and
// every result cut at 500 characters (the two agents made, a refused try at adding the owner to the channel, the
// channel made with its schedule); the agents, the channel and its schedule; and the channel's messages, where the
// coordinator's own posts are the account's.

export const TEAM_COORDINATOR_ID = "8099ec65-61dd-429d-97d2-d3768292e5db";

export const TEAM_HISTORY: Record<string, unknown>[] = [
    {
        "role": "user",
        "text": "I run Paws & Pace, a dog walking business in Austin. I want a team: one agent finds dog-friendly events in Austin each week, another writes my clients a newsletter from them. Put them in a channel and run it once.",
        "created_at": "2026-10-27T09:15:30.488514+00:00",
        "via": "whatsapp"
    },
    {
        "role": "assistant",
        "text": "I’m setting up the weekly Austin dog-events and newsletter team, then I’ll run it once.\n\nI’m creating the two agents with a source-checked research handoff and a draft-only newsletter, then I’ll put them in a weekly channel and kick off this week’s run.\n\nThe team and Monday schedule are in place. I’m starting the first research handoff now and will check the channel for the newsletter draft.\n\nThe channel is active, but the first handoff hasn’t produced the event brief yet. I’m checking the researcher’s run and continuing the requested one-off run.\n\nThe two agents are in the *Paws & Pace Austin Events* channel, and I started the one-off run. The event brief and newsletter draft haven’t appeared yet. I set the weekly schedule to Mondays at 8 AM Central as a default; the channel currently includes the agents, but I couldn’t add you as a member.\n\nIs Monday at 8 AM Central the schedule you want?",
        "created_at": "2026-10-27T09:18:11.239721+00:00",
        "tool_calls": [
            {
                "tool": "noclick__search",
                "arguments": {
                    "limit": 10,
                    "query": "create agents collaborate in channel schedule workflow run once"
                },
                "result": "{\"success\": true, \"results\": [{\"id\": \"guide:channels#schedules\", \"kind\": \"guide\", \"title\": \"Channels: Schedules\", \"url\": \"https://noclick.com/docs/guide/channels#schedules\", \"snippet\": \"A `noclick.Cron` on a channel posts its `message` into the room on each tick, as your account, as `room.post(...)` does without `as_`. It wakes the agents it mentions (every agent with `mode=\\\"all\\\"`), and it restarts a halted channel and its\", \"status\": \"built\"}, {\"id\": \"guide:workflows\", \"kind\": \"guide\", \"title",
                "is_error": false,
                "created_at": "2026-10-27T09:15:35.145266+00:00"
            },
            {
                "tool": "noclick__search",
                "arguments": {
                    "limit": 10,
                    "query": "workflow create schedule agent team newsletter events"
                },
                "result": "{\"success\": true, \"results\": [{\"id\": \"example:newsletter-that-runs-itself\", \"kind\": \"example\", \"title\": \"A newsletter that runs itself\", \"url\": \"https://noclick.com/docs/examples/newsletter-that-runs-itself\", \"snippet\": \"A weekly newsletter written by three agents in one room, approved by a person, published on its own site and domain, and emailed to the readers who signed up there.\", \"status\": \"built\"}, {\"id\": \"event:schedule.paused\", \"kind\": \"event\", \"title\": \"schedule.paused\", \"url\": null, \"s",
                "is_error": false,
                "created_at": "2026-10-27T09:15:35.174353+00:00"
            },
            {
                "tool": "noclick__search",
                "arguments": {
                    "limit": 10,
                    "query": "connected channels list channel create send message"
                },
                "result": "{\"success\": true, \"results\": [{\"id\": \"api:channels_create\", \"kind\": \"api\", \"title\": \"channels_create\", \"url\": null, \"snippet\": \"Create Channel\", \"status\": \"built\"}, {\"id\": \"ref:Channel.create\", \"kind\": \"reference\", \"title\": \"Channel.create\", \"url\": \"https://noclick.com/docs/reference/python/Channel#Channel.create\", \"snippet\": \"Open a channel. Members are `noclick.Agent`s, a `User` (or `\\\"user\\\"`: the user the channel is created for) and A2A URLs; `topic` is one line on what it's for. `mode=\\\"men",
                "is_error": false,
                "created_at": "2026-10-27T09:15:35.194380+00:00"
            },
            {
                "tool": "noclick__search",
                "arguments": {
                    "kind": "api",
                    "limit": 10,
                    "query": "agent create instructions tools agents list"
                },
                "result": "{\"success\": true, \"results\": [{\"id\": \"api:tool_calls_list\", \"kind\": \"api\", \"title\": \"tool_calls_list\", \"url\": null, \"snippet\": \"List Tool Calls\", \"status\": \"built\"}, {\"id\": \"api:agents_create\", \"kind\": \"api\", \"title\": \"agents_create\", \"url\": null, \"snippet\": \"Create Agent\", \"status\": \"built\"}, {\"id\": \"api:operations_tool_calls_list\", \"kind\": \"api\", \"title\": \"operations_tool_calls_list\", \"url\": null, \"snippet\": \"Operation Tool Calls. An agent turn's tool calls, oldest first (empty for other kinds",
                "is_error": false,
                "created_at": "2026-10-27T09:15:39.845178+00:00"
            },
            {
                "tool": "noclick__fetch",
                "arguments": {
                    "id": "guide:channels#find-channels",
                    "detail": "full"
                },
                "result": "{\"success\": true, \"status\": \"built\", \"id\": \"guide:channels#find-channels\", \"kind\": \"guide\", \"title\": \"Channels: Find channels\", \"url\": \"https://noclick.com/docs/guide/channels#find-channels\", \"text\": \"## Find channels\\n\\n```python\\nnoclick.Channel.list(status=\\\"open\\\")\\nroom = noclick.Channel.get(channel_id)\\nroom.close()\\n```\\n\\n```ts\\nimport { Channel } from \\\"noclick\\\";\\n\\nawait Channel.list({ status: \\\"open\\\" });\\nconst room = await Channel.get(channelId);\\nawait room.close();\\n```\\n\\nA user",
                "is_error": false,
                "created_at": "2026-10-27T09:15:39.871905+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "detail": "full",
                    "operation": "channels_messages_create"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"channels_messages_create\", \"method\": \"POST\", \"path\": \"/v1/channels/{channel_id}/messages\", \"risk\": \"outbound\", \"summary\": \"Post Message\", \"input_schema\": {\"type\": \"object\", \"properties\": {\"channel_id\": {\"type\": \"string\"}, \"text\": {\"type\": \"string\", \"description\": \"Markdown; may be empty when the message carries files.\", \"default\": \"\"}, \"as\": {\"anyOf\": [{\"properties\": {\"agent_id\": {\"anyOf\": [{\"type\": \"string\"}, {\"type\": \"null\"}]}, \"user\": {\"anyOf\": [{\"type",
                "is_error": false,
                "created_at": "2026-10-27T09:15:39.901409+00:00"
            },
            {
                "tool": "noclick__fetch",
                "arguments": {
                    "id": "guide:channels#schedules",
                    "detail": "full"
                },
                "result": "{\"success\": true, \"status\": \"built\", \"id\": \"guide:channels#schedules\", \"kind\": \"guide\", \"title\": \"Channels: Schedules\", \"url\": \"https://noclick.com/docs/guide/channels#schedules\", \"text\": \"## Schedules\\n\\nA `noclick.Cron` on a channel posts its `message` into the room on each tick, as your account, as `room.post(...)` does without `as_`. It wakes the agents it mentions (every agent with `mode=\\\"all\\\"`), and it restarts a halted channel and its turn count, as a person's post does. That's how a te",
                "is_error": false,
                "created_at": "2026-10-27T09:15:39.924161+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "detail": "full",
                    "operation": "channels_triggers_create"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"channels_triggers_create\", \"method\": \"POST\", \"path\": \"/v1/channels/{channel_id}/triggers\", \"risk\": \"write\", \"summary\": \"Add Channel Trigger. `{kind: \\\"cron\\\", cron, tz?, message}`: posts `message` on the schedule, waking whom a person's post would.\", \"input_schema\": {\"type\": \"object\", \"properties\": {\"channel_id\": {\"type\": \"string\"}, \"kind\": {\"type\": \"string\", \"description\": \"webhook, event, cron, platform or queue.\"}, \"type\": {\"anyOf\": [{\"type\": \"string\"}",
                "is_error": false,
                "created_at": "2026-10-27T09:15:39.945915+00:00"
            },
            {
                "tool": "noclick__fetch",
                "arguments": {
                    "id": "example:newsletter-that-runs-itself",
                    "detail": "full"
                },
                "result": "{\"success\": true, \"status\": \"built\", \"id\": \"example:newsletter-that-runs-itself\", \"kind\": \"example\", \"title\": \"A newsletter that runs itself\", \"url\": \"https://noclick.com/docs/examples/newsletter-that-runs-itself\", \"text\": \"Every Monday at six, a researcher agent finds the week's climate tech news, a writer agent turns\\nit into an issue, and an editor agent checks every number against its source and sends the draft\\nback until it's right. They work in one [channel](/docs/guide/channels), where e",
                "is_error": false,
                "created_at": "2026-10-27T09:15:39.991920+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "detail": "full",
                    "operation": "channels_create"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"channels_create\", \"method\": \"POST\", \"path\": \"/v1/channels\", \"risk\": \"write\", \"summary\": \"Create Channel\", \"input_schema\": {\"type\": \"object\", \"properties\": {\"name\": {\"type\": \"string\", \"maxLength\": 100, \"minLength\": 1}, \"topic\": {\"type\": \"string\", \"maxLength\": 250, \"description\": \"One line on what the channel is for.\", \"default\": \"\"}, \"members\": {\"items\": {\"properties\": {\"agent_id\": {\"anyOf\": [{\"type\": \"string\"}, {\"type\": \"null\"}]}, \"user\": {\"anyOf\": [{\"typ",
                "is_error": false,
                "created_at": "2026-10-27T09:15:40.027857+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "detail": "full",
                    "operation": "agents_create"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"agents_create\", \"method\": \"POST\", \"path\": \"/v1/agents\", \"risk\": \"write\", \"summary\": \"Create Agent\", \"input_schema\": {\"type\": \"object\", \"properties\": {\"name\": {\"type\": \"string\", \"maxLength\": 100, \"minLength\": 1}, \"instructions\": {\"type\": \"string\", \"maxLength\": 32000, \"minLength\": 1}, \"model\": {\"anyOf\": [{\"type\": \"string\"}, {\"type\": \"null\"}], \"description\": \"In the harness's own format (GET /v1/harnesses/{harness}/models); omitted, the harness's default.\"},",
                "is_error": false,
                "created_at": "2026-10-27T09:15:43.841264+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "detail": "full",
                    "operation": "agents_messages_create"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"agents_messages_create\", \"method\": \"POST\", \"path\": \"/v1/agents/{agent_id}/messages\", \"risk\": \"outbound\", \"summary\": \"Send Message. `stream=1` answers with the turn as server-sent events (`text`, `tool_call`, `tool_result`, `file`, `approval`, `operation`, then `done` with the reply) instead of its operation. An agent built in the app answers with its `workflow.agent_message` operation, never a stream. A message behind a turn the agent took on its own (a w",
                "is_error": false,
                "created_at": "2026-10-27T09:15:43.869839+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "detail": "full",
                    "operation": "channels_messages_list"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"channels_messages_list\", \"method\": \"GET\", \"path\": \"/v1/channels/{channel_id}/messages\", \"risk\": \"read\", \"summary\": \"List Messages. Oldest first: the messages after `after` (`wait_s` waits for one), the `limit` just before `before`, or the `newest`. Paging back, `next_cursor` is the next `before`.\", \"input_schema\": {\"type\": \"object\", \"properties\": {\"channel_id\": {\"type\": \"string\"}, \"after\": {\"anyOf\": [{\"type\": \"string\"}, {\"type\": \"null\"}]}, \"before\": {\"any",
                "is_error": false,
                "created_at": "2026-10-27T09:15:43.909814+00:00"
            },
            {
                "tool": "noclick__search",
                "arguments": {
                    "kind": "guide",
                    "limit": 5,
                    "query": "agents tools search fetch web research tool names"
                },
                "result": "{\"success\": true, \"results\": [{\"id\": \"guide:toolkits\", \"kind\": \"guide\", \"title\": \"Toolkits\", \"url\": \"https://noclick.com/docs/guide/toolkits\", \"snippet\": \"Give your own LLM calls tools that run in your users' connected accounts, plus web search, page fetching and a code sandbox.\", \"status\": \"built\"}, {\"id\": \"guide:mcp#give-your-hosted-agents-the-same-tools\", \"kind\": \"guide\", \"title\": \"The NoClick MCP server: Give your hosted agents the same tools\", \"url\": \"https://noclick.com/docs/guide/mcp#give",
                "is_error": false,
                "created_at": "2026-10-27T09:15:43.931590+00:00"
            },
            {
                "tool": "noclick__api_call",
                "arguments": {
                    "_truncated": true
                },
                "result": "{\"success\": true, \"response\": {\"object\": \"agent\", \"id\": \"f8d54dbc-6ef6-4d0a-93ae-050ab38c93cd\", \"origin\": \"api\", \"name\": \"Paws Pace Newsletter Writer\", \"workflow_id\": \"82767ea8-e347-4a9e-8c71-97cb7525e597\", \"model\": \"openrouter/~openai/gpt-luna-latest\", \"harness\": \"sdk\", \"model_connection\": null, \"instructions\": \"You write client newsletter drafts for Paws & Pace, a dog walking business in Austin. When the Austin Dog Events Researcher posts a sourced events brief and mentions you, write a warm, ",
                "is_error": false,
                "created_at": "2026-10-27T09:15:53.634401+00:00"
            },
            {
                "tool": "noclick__api_call",
                "arguments": {
                    "_truncated": true
                },
                "result": "{\"success\": true, \"response\": {\"object\": \"agent\", \"id\": \"d34a0e47-f24f-483a-8610-da7d03828513\", \"origin\": \"api\", \"name\": \"Austin Dog Events Researcher\", \"workflow_id\": \"bb7ee3d1-bfa3-44a1-a1cd-57401e5e4ac2\", \"model\": \"openrouter/~openai/gpt-luna-latest\", \"harness\": \"sdk\", \"model_connection\": null, \"instructions\": \"You research dog-friendly events in Austin, Texas for Paws & Pace, a dog walking business. When asked for this week's events, search the web for events happening in the coming week in ",
                "is_error": false,
                "created_at": "2026-10-27T09:15:53.662840+00:00"
            },
            {
                "tool": "noclick__api_call",
                "arguments": {
                    "_truncated": true
                },
                "result": "Only a user's channel has a user member.",
                "is_error": true,
                "created_at": "2026-10-27T09:15:59.443351+00:00"
            },
            {
                "tool": "noclick__api_call",
                "arguments": {
                    "_truncated": true
                },
                "result": "{\"success\": true, \"response\": {\"object\": \"channel\", \"id\": \"8554d409-867f-466e-a7f1-a71adcf0311d\", \"name\": \"Paws & Pace Austin Events\", \"topic\": \"Weekly Austin dog-friendly event research and client newsletter drafts for Sam to review.\", \"mode\": \"mentions\", \"status\": \"open\", \"halt_reason\": null, \"max_agent_turns\": 12, \"max_mention_hops\": 6, \"budget_usd\": 5.0, \"spent_usd\": 0.0, \"agent_turns_since_human\": 0, \"user_id\": null, \"workspace_id\": null, \"members\": [{\"object\": \"channel_member\", \"id\": \"0a6d",
                "is_error": false,
                "created_at": "2026-10-27T09:16:05.409461+00:00"
            },
            {
                "tool": "noclick__api_call",
                "arguments": {
                    "arguments": {
                        "text": "@Austin Dog Events Researcher Find and verify dog-friendly events in Austin for the coming week, then hand your sourced brief to @Paws Pace Newsletter Writer for a client newsletter draft. Post the draft here for Sam to review; do not send it to clients.",
                        "channel_id": "8554d409-867f-466e-a7f1-a71adcf0311d"
                    },
                    "operation": "channels_messages_create"
                },
                "result": "{\"success\": true, \"text\": \"<untrusted-c210fb47 source=\\\"channels_messages_create\\\">\\n{\\\"object\\\":\\\"channel_message\\\",\\\"id\\\":\\\"3b477780-8924-4efe-a83b-cf9442b1914a\\\",\\\"channel_id\\\":\\\"8554d409-867f-466e-a7f1-a71adcf0311d\\\",\\\"author\\\":{\\\"type\\\":\\\"account\\\",\\\"id\\\":null,\\\"name\\\":\\\"owner\\\"},\\\"text\\\":\\\"@Austin Dog Events Researcher Find and verify dog-friendly events in Austin for the coming week, then hand your sourced brief to @Paws Pace Newsletter Writer for a client newsletter draft. Post the draft",
                "is_error": false,
                "created_at": "2026-10-27T09:16:09.423549+00:00"
            },
            {
                "tool": "noclick__api_call",
                "arguments": {
                    "arguments": {
                        "limit": 20,
                        "newest": true,
                        "wait_s": 20,
                        "channel_id": "8554d409-867f-466e-a7f1-a71adcf0311d"
                    },
                    "operation": "channels_messages_list"
                },
                "result": "wait_s waits for new messages: pass it with after.",
                "is_error": true,
                "created_at": "2026-10-27T09:16:11.713772+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "detail": "full",
                    "operation": "channels_messages_list"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"channels_messages_list\", \"method\": \"GET\", \"path\": \"/v1/channels/{channel_id}/messages\", \"risk\": \"read\", \"summary\": \"List Messages. Oldest first: the messages after `after` (`wait_s` waits for one), the `limit` just before `before`, or the `newest`. Paging back, `next_cursor` is the next `before`.\", \"input_schema\": {\"type\": \"object\", \"properties\": {\"channel_id\": {\"type\": \"string\"}, \"after\": {\"anyOf\": [{\"type\": \"string\"}, {\"type\": \"null\"}]}, \"before\": {\"any",
                "is_error": false,
                "created_at": "2026-10-27T09:16:13.614197+00:00"
            },
            {
                "tool": "noclick__api_call",
                "arguments": {
                    "arguments": {
                        "limit": 20,
                        "newest": true,
                        "channel_id": "8554d409-867f-466e-a7f1-a71adcf0311d"
                    },
                    "operation": "channels_messages_list"
                },
                "result": "{\"success\": true, \"text\": \"<untrusted-5a55ee5d source=\\\"channels_messages_list\\\">\\n{\\\"object\\\":\\\"list\\\",\\\"data\\\":[{\\\"object\\\":\\\"channel_message\\\",\\\"id\\\":\\\"3b477780-8924-4efe-a83b-cf9442b1914a\\\",\\\"channel_id\\\":\\\"8554d409-867f-466e-a7f1-a71adcf0311d\\\",\\\"author\\\":{\\\"type\\\":\\\"account\\\",\\\"id\\\":null,\\\"name\\\":\\\"owner\\\"},\\\"text\\\":\\\"@Austin Dog Events Researcher Find and verify dog-friendly events in Austin for the coming week, then hand your sourced brief to @Paws Pace Newsletter Writer for a client new",
                "is_error": false,
                "created_at": "2026-10-27T09:16:15.878284+00:00"
            },
            {
                "tool": "noclick__api_call",
                "arguments": {
                    "arguments": {
                        "after": "354fe4d8-b3e4-49cf-be8b-e1b3cf37be5b",
                        "limit": 20,
                        "wait_s": 50,
                        "channel_id": "8554d409-867f-466e-a7f1-a71adcf0311d"
                    },
                    "operation": "channels_messages_list"
                },
                "result": "{\"success\": true, \"text\": \"<untrusted-e311fd1c source=\\\"channels_messages_list\\\">\\n{\\\"object\\\":\\\"list\\\",\\\"data\\\":[],\\\"next_cursor\\\":null}\\n</untrusted-e311fd1c>\", \"next\": null}",
                "is_error": false,
                "created_at": "2026-10-27T09:17:09.581085+00:00"
            },
            {
                "tool": "noclick__api_call",
                "arguments": {
                    "arguments": {
                        "status": "live",
                        "agent_id": "d34a0e47-f24f-483a-8610-da7d03828513"
                    },
                    "operation": "agents_jobs_list"
                },
                "result": "{\"success\": true, \"response\": {\"object\": \"list\", \"data\": [], \"next_cursor\": null}, \"next\": null}",
                "is_error": false,
                "created_at": "2026-10-27T09:17:14.068086+00:00"
            },
            {
                "tool": "noclick__api_call",
                "arguments": {
                    "arguments": {
                        "limit": 20,
                        "newest": true,
                        "channel_id": "8554d409-867f-466e-a7f1-a71adcf0311d"
                    },
                    "operation": "channels_messages_list"
                },
                "result": "{\"success\": true, \"text\": \"<untrusted-7aff5d35 source=\\\"channels_messages_list\\\">\\n{\\\"object\\\":\\\"list\\\",\\\"data\\\":[{\\\"object\\\":\\\"channel_message\\\",\\\"id\\\":\\\"3b477780-8924-4efe-a83b-cf9442b1914a\\\",\\\"channel_id\\\":\\\"8554d409-867f-466e-a7f1-a71adcf0311d\\\",\\\"author\\\":{\\\"type\\\":\\\"account\\\",\\\"id\\\":null,\\\"name\\\":\\\"owner\\\"},\\\"text\\\":\\\"@Austin Dog Events Researcher Find and verify dog-friendly events in Austin for the coming week, then hand your sourced brief to @Paws Pace Newsletter Writer for a client new",
                "is_error": false,
                "created_at": "2026-10-27T09:17:15.943118+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "detail": "full",
                    "operation": "agents_jobs_list"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"agents_jobs_list\", \"method\": \"GET\", \"path\": \"/v1/agents/{agent_id}/jobs\", \"risk\": \"read\", \"summary\": \"List Jobs. The jobs it started, newest first: `status` (a comma list, `live` for every unfinished one), `kind`, `agent_id` (the agent doing the work) and `conversation` (its own conversation that started them).\", \"input_schema\": {\"type\": \"object\", \"properties\": {\"agent_id\": {\"anyOf\": [{\"type\": \"string\"}, {\"type\": \"null\"}]}, \"status\": {\"anyOf\": [{\"type\": \"",
                "is_error": false,
                "created_at": "2026-10-27T09:17:21.241902+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "detail": "full",
                    "operation": "channels_get"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"channels_get\", \"method\": \"GET\", \"path\": \"/v1/channels/{channel_id}\", \"risk\": \"read\", \"summary\": \"Get Channel\", \"input_schema\": {\"type\": \"object\", \"properties\": {\"channel_id\": {\"type\": \"string\"}}, \"required\": [\"channel_id\"]}}, \"next\": \"Call it with api_call.\"}",
                "is_error": false,
                "created_at": "2026-10-27T09:17:21.278272+00:00"
            },
            {
                "tool": "noclick__fetch",
                "arguments": {
                    "id": "agent:d34a0e47-f24f-483a-8610-da7d03828513",
                    "detail": "full"
                },
                "result": "{\"success\": true, \"ref\": \"agent:d34a0e47-f24f-483a-8610-da7d03828513\", \"id\": \"d34a0e47-f24f-483a-8610-da7d03828513\", \"object\": {\"object\": \"agent\", \"id\": \"d34a0e47-f24f-483a-8610-da7d03828513\", \"origin\": \"api\", \"name\": \"Austin Dog Events Researcher\", \"workflow_id\": \"bb7ee3d1-bfa3-44a1-a1cd-57401e5e4ac2\", \"model\": \"openrouter/~openai/gpt-luna-latest\", \"harness\": \"sdk\", \"model_connection\": null, \"instructions\": \"You research dog-friendly events in Austin, Texas for Paws & Pace, a dog walking busine",
                "is_error": false,
                "created_at": "2026-10-27T09:17:21.355720+00:00"
            },
            {
                "tool": "noclick__api_call",
                "arguments": {
                    "arguments": {
                        "limit": 25,
                        "newest": true,
                        "channel_id": "8554d409-867f-466e-a7f1-a71adcf0311d"
                    },
                    "operation": "channels_messages_list"
                },
                "result": "{\"success\": true, \"text\": \"<untrusted-4905ee4d source=\\\"channels_messages_list\\\">\\n{\\\"object\\\":\\\"list\\\",\\\"data\\\":[{\\\"object\\\":\\\"channel_message\\\",\\\"id\\\":\\\"3b477780-8924-4efe-a83b-cf9442b1914a\\\",\\\"channel_id\\\":\\\"8554d409-867f-466e-a7f1-a71adcf0311d\\\",\\\"author\\\":{\\\"type\\\":\\\"account\\\",\\\"id\\\":null,\\\"name\\\":\\\"owner\\\"},\\\"text\\\":\\\"@Austin Dog Events Researcher Find and verify dog-friendly events in Austin for the coming week, then hand your sourced brief to @Paws Pace Newsletter Writer for a client new",
                "is_error": false,
                "created_at": "2026-10-27T09:17:21.403260+00:00"
            },
            {
                "tool": "noclick__api_call",
                "arguments": {
                    "arguments": {
                        "limit": 20,
                        "status": "live",
                        "agent_id": "f8d54dbc-6ef6-4d0a-93ae-050ab38c93cd"
                    },
                    "operation": "agents_jobs_list"
                },
                "result": "{\"success\": true, \"response\": {\"object\": \"list\", \"data\": [], \"next_cursor\": null}, \"next\": null}",
                "is_error": false,
                "created_at": "2026-10-27T09:17:49.250343+00:00"
            },
            {
                "tool": "noclick__api_call",
                "arguments": {
                    "arguments": {
                        "limit": 20,
                        "status": "live",
                        "agent_id": "d34a0e47-f24f-483a-8610-da7d03828513"
                    },
                    "operation": "agents_jobs_list"
                },
                "result": "{\"success\": true, \"response\": {\"object\": \"list\", \"data\": [], \"next_cursor\": null}, \"next\": null}",
                "is_error": false,
                "created_at": "2026-10-27T09:17:49.282958+00:00"
            },
            {
                "tool": "noclick__api_call",
                "arguments": {
                    "arguments": {
                        "channel_id": "8554d409-867f-466e-a7f1-a71adcf0311d"
                    },
                    "operation": "channels_get"
                },
                "result": "{\"success\": true, \"response\": {\"object\": \"channel\", \"id\": \"8554d409-867f-466e-a7f1-a71adcf0311d\", \"name\": \"Paws & Pace Austin Events\", \"topic\": \"Weekly Austin dog-friendly event research and client newsletter drafts for Sam to review.\", \"mode\": \"mentions\", \"status\": \"open\", \"halt_reason\": null, \"max_agent_turns\": 12, \"max_mention_hops\": 6, \"budget_usd\": 5.0, \"spent_usd\": 0.000273675, \"agent_turns_since_human\": 2, \"user_id\": null, \"workspace_id\": null, \"members\": [{\"object\": \"channel_member\", \"id",
                "is_error": false,
                "created_at": "2026-10-27T09:17:49.332901+00:00"
            },
            {
                "tool": "wake_me",
                "arguments": {
                    "note": "Check the first run in Paws & Pace Austin Events channel 8554d409-867f-466e-a7f1-a71adcf0311d. Read messages after initial request 3b477780-8924-4efe-a83b-cf9442b1914a for researcher brief/newsletter draft; if still absent, report run has not completed yet and do not claim success. Ask Sam whether Monday 8 AM America/Chicago is the desired schedule and whether channel access needs changing.",
                    "after_minutes": 10
                },
                "result": "{\"success\": true, \"wakeup_id\": \"2ad2164d-66b8-4633-a624-c92dbc1a497e\", \"note\": \"Check the first run in Paws & Pace Austin Events channel 8554d409-867f-466e-a7f1-a71adcf0311d. Read messages after initial request 3b477780-8924-4efe-a83b-cf9442b1914a for researcher brief/newsletter draft; if still absent, report run has not completed yet and do not claim success. Ask Sam whether Monday 8 AM America/Chicago is the desired schedule and whether channel access needs changing.\", \"status\": \"pending\", \"du",
                "is_error": false,
                "created_at": "2026-10-27T09:17:53.543386+00:00"
            },
            {
                "tool": "wake_me",
                "arguments": {
                    "at": "09:00",
                    "note": "Check the first run in Paws & Pace Austin Events channel 8554d409-867f-466e-a7f1-a71adcf0311d. Read messages after initial request 3b477780-8924-4efe-a83b-cf9442b1914a for researcher brief/newsletter draft; if still absent, report run has not completed yet and ask Sam whether Monday 8 AM America/Chicago is the desired schedule and whether channel access needs changing.",
                    "wakeup_id": "2ad2164d-66b8-4633-a624-c92dbc1a497e"
                },
                "result": "{\"success\": true, \"wakeup_id\": \"2ad2164d-66b8-4633-a624-c92dbc1a497e\", \"note\": \"Check the first run in Paws & Pace Austin Events channel 8554d409-867f-466e-a7f1-a71adcf0311d. Read messages after initial request 3b477780-8924-4efe-a83b-cf9442b1914a for researcher brief/newsletter draft; if still absent, report run has not completed yet and ask Sam whether Monday 8 AM America/Chicago is the desired schedule and whether channel access needs changing.\", \"status\": \"pending\", \"due_at\": \"2026-10-27T09:",
                "is_error": false,
                "created_at": "2026-10-27T09:17:58.970253+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "query": "add owner as a member to channel"
                },
                "result": "{\"success\": true, \"operations\": [{\"name\": \"channels_members_create\", \"summary\": \"Add Member\", \"status\": \"built\", \"risk\": \"write\"}, {\"name\": \"channels_members_delete\", \"summary\": \"Remove Member\", \"status\": \"built\", \"risk\": \"destructive\"}, {\"name\": \"workspaces_members_create\", \"summary\": \"Add Member\", \"status\": \"built\", \"risk\": \"write\"}, {\"name\": \"workspaces_members_delete\", \"summary\": \"Remove Member. From the workspace and every one of its channels.\", \"status\": \"built\", \"risk\": \"destructive\"}, {\"",
                "is_error": false,
                "created_at": "2026-10-27T09:17:58.998120+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "detail": "full",
                    "operation": "channels_members_create"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"channels_members_create\", \"method\": \"POST\", \"path\": \"/v1/channels/{channel_id}/members\", \"risk\": \"write\", \"summary\": \"Add Member\", \"input_schema\": {\"type\": \"object\", \"properties\": {\"channel_id\": {\"type\": \"string\"}, \"agent_id\": {\"anyOf\": [{\"type\": \"string\"}, {\"type\": \"null\"}]}, \"user\": {\"anyOf\": [{\"type\": \"boolean\"}, {\"type\": \"null\"}]}, \"user_id\": {\"anyOf\": [{\"type\": \"string\"}, {\"type\": \"null\"}]}, \"a2a_url\": {\"anyOf\": [{\"type\": \"string\", \"maxLength\": 2048}",
                "is_error": false,
                "created_at": "2026-10-27T09:18:03.064971+00:00"
            },
            {
                "tool": "noclick__api_call",
                "arguments": {
                    "arguments": {
                        "user": true,
                        "channel_id": "8554d409-867f-466e-a7f1-a71adcf0311d"
                    },
                    "operation": "channels_members_create"
                },
                "result": "Only a user's channel has a user member.",
                "is_error": true,
                "created_at": "2026-10-27T09:18:05.196362+00:00"
            }
        ],
        "reasoning": [
            {
                "text": "Considering multiagent setup",
                "created_at": "2026-10-27T09:15:32.474396+00:00"
            },
            {
                "text": "Determining email integration",
                "created_at": "2026-10-27T09:15:46.844092+00:00"
            },
            {
                "text": "Setting budget and creating agents",
                "created_at": "2026-10-27T09:15:48.658741+00:00"
            },
            {
                "text": "Scheduling channel creation",
                "created_at": "2026-10-27T09:15:57.112779+00:00"
            },
            {
                "text": "Considering asynchronous updates",
                "created_at": "2026-10-27T09:16:17.998802+00:00"
            },
            {
                "text": "Evaluating job status",
                "created_at": "2026-10-27T09:17:12.483324+00:00"
            },
            {
                "text": "Investigating channel tools",
                "created_at": "2026-10-27T09:17:19.719209+00:00"
            }
        ]
    }
];

export const TEAM_AGENTS: Record<string, unknown>[] = [
    {
        "object": "agent",
        "id": "d34a0e47-f24f-483a-8610-da7d03828513",
        "origin": "api",
        "name": "Austin Dog Events Researcher",
        "workflow_id": "bb7ee3d1-bfa3-44a1-a1cd-57401e5e4ac2",
        "model": "openrouter/~openai/gpt-luna-latest",
        "harness": "sdk",
        "model_connection": null,
        "instructions": "You research dog-friendly events in Austin, Texas for Paws & Pace, a dog walking business. When asked for this week's events, search the web for events happening in the coming week in Austin and nearby Austin-area neighborhoods. Prioritize official event, venue, park, or organizer pages; verify date, time, location, dog admission/rules, and registration details from sources. Do not assume an event is dog-friendly unless a source supports it. Share a concise brief in the channel with 4–8 useful events when available. For each include event name, date/time, location, what dogs are allowed/required, price or registration if known, and source URL(s). Clearly mark missing or uncertain details; omit unsupported claims. End by mentioning @Paws Pace Newsletter Writer and ask it to draft a client newsletter only from the sourced events. Do not send messages to clients or claim Paws & Pace is attending/sponsoring anything.",
        "tools": [
            "search",
            "fetch"
        ],
        "can_request": [],
        "user_id": null,
        "parent_id": null,
        "ttl_s": null,
        "expires_at": null,
        "budget_usd_per_month": 5.0,
        "region": null,
        "timezone": "America/Chicago",
        "secret_ids": [],
        "volumes": {},
        "memory_id": "72c1799b-7712-4674-834b-00d83fc05e70",
        "memories": [],
        "repos": [],
        "shell": true,
        "network": true,
        "machine_id": null,
        "browser_profile_id": null,
        "card_id": null,
        "turn_limits": {
            "usd": 1.0,
            "minutes": 10
        },
        "used_by": [],
        "created_at": "2026-10-27T09:15:53.547125+00:00",
        "status": "idle",
        "last_active_at": "2026-10-27T09:31:29.761881+00:00",
        "running_turns": 0,
        "child_count": 0,
        "job_id": null,
        "paused": false,
        "trigger_kinds": [],
        "grants": [],
        "added_in_app": []
    },
    {
        "object": "agent",
        "id": "f8d54dbc-6ef6-4d0a-93ae-050ab38c93cd",
        "origin": "api",
        "name": "Paws Pace Newsletter Writer",
        "workflow_id": "82767ea8-e347-4a9e-8c71-97cb7525e597",
        "model": "openrouter/~openai/gpt-luna-latest",
        "harness": "sdk",
        "model_connection": null,
        "instructions": "You write client newsletter drafts for Paws & Pace, a dog walking business in Austin. When the Austin Dog Events Researcher posts a sourced events brief and mentions you, write a warm, useful, concise newsletter in the business's first-person plural voice (we/our). Use only event facts and links present in the researcher's sourced brief; preserve dates, dog rules, and uncertainty accurately. Include a subject line, brief friendly intro, a scannable set of event highlights with links, and a short sign-off. Never invent business details, promises, prices, client names, or claims that Paws & Pace is attending/sponsoring an event. Post the newsletter as a DRAFT in the channel for Sam to review; never email or otherwise send it to clients.",
        "tools": [],
        "can_request": [],
        "user_id": null,
        "parent_id": null,
        "ttl_s": null,
        "expires_at": null,
        "budget_usd_per_month": 5.0,
        "region": null,
        "timezone": "America/Chicago",
        "secret_ids": [],
        "volumes": {},
        "memory_id": "34bcc575-612b-44f2-9187-5a1a10062eb5",
        "memories": [],
        "repos": [],
        "shell": true,
        "network": true,
        "machine_id": null,
        "browser_profile_id": null,
        "card_id": null,
        "turn_limits": {
            "usd": 1.0,
            "minutes": 10
        },
        "used_by": [],
        "created_at": "2026-10-27T09:15:53.544097+00:00",
        "status": "idle",
        "last_active_at": "2026-10-27T09:31:16.455118+00:00",
        "running_turns": 0,
        "child_count": 0,
        "job_id": null,
        "paused": false,
        "trigger_kinds": [],
        "grants": [],
        "added_in_app": []
    }
];

export const TEAM_CHANNEL: Record<string, unknown> = {
    "object": "channel",
    "id": "8554d409-867f-466e-a7f1-a71adcf0311d",
    "name": "Paws & Pace Austin Events",
    "topic": "Weekly Austin dog-friendly event research and client newsletter drafts for Sam to review.",
    "mode": "mentions",
    "status": "open",
    "halt_reason": null,
    "max_agent_turns": 12,
    "max_mention_hops": 6,
    "budget_usd": 5.0,
    "spent_usd": 0.140942865,
    "agent_turns_since_human": 2,
    "user_id": null,
    "workspace_id": null,
    "members": [
        {
            "object": "channel_member",
            "id": "0a6df482-a6e8-486a-849e-498bec40517c",
            "type": "agent",
            "name": "Austin Dog Events Researcher",
            "agent_id": "d34a0e47-f24f-483a-8610-da7d03828513",
            "a2a_url": null,
            "a2a_header_names": null,
            "user_id": null,
            "workflow_id": null,
            "node_id": null,
            "workflow_name": null,
            "busy": false,
            "created_at": "2026-10-27T09:16:03.470251+00:00"
        },
        {
            "object": "channel_member",
            "id": "97578799-0fb8-403a-a73f-4a02a67c43dc",
            "type": "agent",
            "name": "Paws Pace Newsletter Writer",
            "agent_id": "f8d54dbc-6ef6-4d0a-93ae-050ab38c93cd",
            "a2a_url": null,
            "a2a_header_names": null,
            "user_id": null,
            "workflow_id": null,
            "node_id": null,
            "workflow_name": null,
            "busy": false,
            "created_at": "2026-10-27T09:16:03.490765+00:00"
        }
    ],
    "created_at": "2026-10-27T09:16:03.449055+00:00",
    "unread_count": 2
};

export const TEAM_CHANNEL_TRIGGERS: Record<string, unknown>[] = [
    {
        "object": "agent_trigger",
        "id": "28c37a6e-594e-4034-92fc-f973c3ee4b26",
        "agent_id": null,
        "channel_id": "8554d409-867f-466e-a7f1-a71adcf0311d",
        "kind": "cron",
        "spec": {
            "tz": "America/Chicago",
            "cron": "0 8 * * 1",
            "message": "@Austin Dog Events Researcher Find and verify dog-friendly events in Austin for the coming week, then hand off your sourced brief to @Paws Pace Newsletter Writer for a client newsletter draft. Post the draft in this channel for Sam to review; do not send it to clients."
        },
        "status": "active",
        "url": null,
        "next_run": "2026-11-02T14:00:00+00:00",
        "last_fired_at": null,
        "error": null,
        "created_at": "2026-10-27T09:16:03.846208+00:00"
    }
];

export const TEAM_CHANNEL_MESSAGES: Record<string, unknown>[] = [
    {
        "object": "channel_message",
        "id": "3b477780-8924-4efe-a83b-cf9442b1914a",
        "channel_id": "8554d409-867f-466e-a7f1-a71adcf0311d",
        "author": {
            "type": "account",
            "id": null,
            "name": "owner"
        },
        "text": "@Austin Dog Events Researcher Find and verify dog-friendly events in Austin for the coming week, then hand your sourced brief to @Paws Pace Newsletter Writer for a client newsletter draft. Post the draft here for Sam to review; do not send it to clients.",
        "mentions": [
            "Austin Dog Events Researcher",
            "Paws Pace Newsletter Writer"
        ],
        "created_at": "2026-10-27T09:16:09.213127+00:00",
        "subscription_id": null,
        "event": null,
        "attachments": [],
        "reactions": []
    },
    {
        "object": "channel_message",
        "id": "354fe4d8-b3e4-49cf-be8b-e1b3cf37be5b",
        "channel_id": "8554d409-867f-466e-a7f1-a71adcf0311d",
        "author": {
            "type": "agent",
            "id": "f8d54dbc-6ef6-4d0a-93ae-050ab38c93cd",
            "name": "Paws Pace Newsletter Writer"
        },
        "text": "@Austin Dog Events Researcher Please post the sourced events brief here and mention me once it’s ready. I’ll draft the newsletter for Sam to review using only the verified details and links.",
        "mentions": [
            "Austin Dog Events Researcher"
        ],
        "created_at": "2026-10-27T09:16:14.370145+00:00",
        "subscription_id": null,
        "event": null,
        "attachments": [],
        "reactions": []
    },
    {
        "object": "channel_message",
        "id": "bce70c76-d99e-4f2e-baed-172b65f43f24",
        "channel_id": "8554d409-867f-466e-a7f1-a71adcf0311d",
        "author": {
            "type": "agent",
            "id": "d34a0e47-f24f-483a-8610-da7d03828513",
            "name": "Austin Dog Events Researcher"
        },
        "text": "**Dog-friendly events | Austin & nearby | Tue, Oct 27–Tue, Nov 3, 2026**\n\n- **Tuesday Twilights: Dog-Friendly Night** — **Tue, Oct 27, 5–8 PM**; Lady Bird Johnson Wildflower Center, 4801 La Crosse Ave., Austin. Costume contest; dogs must be leashed (6 ft max, no retractables), stay on marked trails, and meet the venue’s vaccination and conduct rules. **Free for members; reservations encouraged; nonmember admission unclear.** [Official event](https://www.wildflower.org/event/tuesday-twilights-10-27-2026)\n\n- **Halloween Dog Pawrty & Costume Contest** — **Wed, Oct 28, 6–10 PM**; Meanwhile Brewing, 3901 Promontory Point Dr., Austin. Dog-focused event with vendors, rescue meet-and-greet, and costume contest at 8 PM. **Venue lists it as free; dog-specific entry rules not stated.** [Official venue listing](https://www.meanwhilebeer.com/events) · [Event details](https://www.prekindle.com/event/17733-halloween-dog-pawrty-and-costume-contest-austin)\n\n- **Bark ’n’ Boo 2026** — **Fri, Oct 30, 7–9 PM**; The Watering Bowl, 820 FM 1626, Austin. Event listing describes pups, costumes and prizes. **Dog participation is indicated, but specific dog rules, ticket price and registration requirements are unclear; check with organizer before going.** [Eventbrite listing](https://www.eventbrite.com/e/bark-n-boo-2026-tickets-2002309231813)\n\n- **Live Music: Todd Deatherage** — **Fri, Oct 30, 6–8 PM**; Vista Brewing, 13551 FM 150, Driftwood (near Austin). Official listing says free, all ages and dog-friendly; outdoor show is weather-dependent. [Official music listing](https://www.vistabrewingtx.com/weekly-live-music) · [Location](https://www.vistabrewingtx.com/)\n\n- **Hoppy Halloween Lunch with Deer Fellow** — **Sat, Oct 31, noon–4 PM; music 2–4 PM**; Vista Brewing, 13551 FM 150, Driftwood. Official calendar marks it dog-friendly; family Halloween lunch and live music. **Admission price and any additional dog rules not stated.** [Official calendar](https://www.vistabrewingtx.com/calendars)\n\n- **Texas Wienerfest** — **Sat, Oct 31, 10 AM–5 PM**; Sherwood Forest Faire, 1883 Old Hwy 20, McDade (about 35 miles east of Austin). Dogs allowed; non-dachshunds must be under 45 lb. Leash required except in designated areas; max 6 ft, no retractables; vaccination and supervision requirements apply. **Human ticket required; October final-sale price listed as $19.** [Organizer event page](https://www.zilkerbark.com/texas-wienerfest) · [FAQ/rules](https://www.zilkerbark.com/texas-wienerfest-faq) · [Venue address](https://www.sherwoodforestfaire.com/contact)\n\n- **Round Rock Pumpkin Festival & Pumpkin Patch** — **Sat, Oct 31, 10 AM–7 PM**; Old Settlers Park, 3300 E Palm Valley Blvd., Round Rock. Organizer calls it pet-friendly; dogs must be leashed and owners must clean up. **Admission listed as $12.** [Official event/pet rules](https://roundrockpumpkinfestival.com/) · [Hours](https://roundrockpumpkinfestival.com/hours-%26-specials) · [Admission](https://roundrockpumpkinfestival.com/attractions) · [Location](https://roundrockpumpkinfestival.com/location)\n\n- **Sunday Live Music: Stone Wheels** — **Sun, Nov 1, 2–4 PM**; Vista Brewing, 13551 FM 150, Driftwood. Official listing says dog-friendly; the brewery’s music page describes its shows as free and all-ages. [Official music listing](https://www.vistabrewingtx.com/weekly-live-music) · [Location](https://www.vistabrewingtx.com/)\n\n@Paws Pace Newsletter Writer — please draft a client newsletter using **only these sourced events**, retaining the stated uncertainties and dog rules; post the draft here for Sam’s review.",
        "mentions": [
            "Paws Pace Newsletter Writer"
        ],
        "created_at": "2026-10-27T09:18:44.825739+00:00",
        "subscription_id": null,
        "event": null,
        "attachments": [],
        "reactions": []
    },
    {
        "object": "channel_message",
        "id": "2a3b43a6-3e55-4c95-b3ae-92df2d6bae56",
        "channel_id": "8554d409-867f-466e-a7f1-a71adcf0311d",
        "author": {
            "type": "agent",
            "id": "f8d54dbc-6ef6-4d0a-93ae-050ab38c93cd",
            "name": "Paws Pace Newsletter Writer"
        },
        "text": "**DRAFT — for Sam’s review**\n\n**Subject:** Austin-area dog-friendly events: Oct 27–31\n\nHi everyone,\n\nWe’ve rounded up a few events for you and your pup this week. Check the event details before heading out, especially where dog rules or admission information aren’t specified.\n\n- **Tuesday Twilights: Dog-Friendly Night** — **Tue, Oct 27, 5–8 PM** at Lady Bird Johnson Wildflower Center. Costume contest. Dogs must be leashed on a leash no longer than 6 feet (no retractables), stay on marked trails, and follow the venue’s vaccination and conduct rules. Free for members; reservations encouraged. Nonmember admission is unclear. [Official event details](https://www.wildflower.org/event/tuesday-twilights-10-27-2026)\n- **Halloween Dog Pawrty & Costume Contest** — **Wed, Oct 28, 6–10 PM** at Meanwhile Brewing. The event includes vendors, a rescue meet-and-greet, and a costume contest at 8 PM. The venue lists it as free; dog-specific entry rules aren’t stated. [Venue listing](https://www.meanwhilebeer.com/events) · [Event details](https://www.prekindle.com/event/17733-halloween-dog-pawrty-and-costume-contest-austin)\n- **Live Music: Todd Deatherage** — **Fri, Oct 30, 6–8 PM** at Vista Brewing in Driftwood. The official listing says it’s free, all ages, and dog-friendly; the outdoor show is weather-dependent. [Music listing](https://www.vistabrewingtx.com/weekly-live-music) · [Location](https://www.vistabrewingtx.com/)\n- **Bark ’n’ Boo 2026** — **Fri, Oct 30, 7–9 PM** at The Watering Bowl. The listing mentions pups, costumes, and prizes, but specific dog rules, ticket price, and registration requirements are unclear—check with the organizer before going. [Event listing](https://www.eventbrite.com/e/bark-n-boo-2026-tickets-2002309231813)\n- **Hoppy Halloween Lunch with Deer Fellow** — **Sat, Oct 31, noon–4 PM; music 2–4 PM** at Vista Brewing in Driftwood. The official calendar marks it dog-friendly. Admission price and any additional dog rules aren’t stated. [Official calendar](https://www.vistabrewingtx.com/calendars)\n\nWe hope you and your pup have a lovely week!\n\nWarmly,  \n**Paws & Pace**",
        "mentions": [],
        "created_at": "2026-10-27T09:18:56.529798+00:00",
        "subscription_id": null,
        "event": null,
        "attachments": [],
        "reactions": []
    },
    {
        "object": "channel_message",
        "id": "70172951-c21e-4795-892c-a9224cc93d4c",
        "channel_id": "8554d409-867f-466e-a7f1-a71adcf0311d",
        "author": {
            "type": "agent",
            "id": "d34a0e47-f24f-483a-8610-da7d03828513",
            "name": "Austin Dog Events Researcher"
        },
        "text": "**Sourced dog-friendly events | Austin & nearby | Oct 27–Nov 3, 2026**\n\n- **Tuesday Twilights: Dog-Friendly Night** — Tue, Oct 27, 5–8 PM; Lady Bird Johnson Wildflower Center, 4801 La Crosse Ave., Austin. Dogs must stay leashed (6 ft max; no retractables) and on marked trails; vaccination, supervision and other venue rules apply. Free for members; reservations encouraged. Nonmember admission unclear. [Official event page](https://www.wildflower.org/event/tuesday-twilights-10-27-2026)\n- **Halloween Dog Pawrty & Costume Contest** — Wed, Oct 28, 6–10 PM; Meanwhile Brewing, 3901 Promontory Point Dr., Austin. Dog-focused event; costume contest at 8 PM. Venue lists it as free. Specific dog entry rules not stated. [Venue listing](https://www.meanwhilebeer.com/events) · [Event details](https://www.prekindle.com/event/17733-halloween-dog-pawrty-and-costume-contest-austin)\n- **Bark ’n’ Boo 2026** — Fri, Oct 30, 7–9 PM; The Watering Bowl, 820 FM 1626, Austin. Listing describes pups, costumes and prizes; dog rules, price and registration details are unclear. [Eventbrite listing](https://www.eventbrite.com/e/bark-n-boo-2026-tickets-2002309231813)\n- **Live Music: Todd Deatherage** — Fri, Oct 30, 6–8 PM; Vista Brewing, 13551 FM 150, Driftwood. Free, all-ages and dog-friendly; weather-dependent outdoor show. [Official listing](https://www.vistabrewingtx.com/weekly-live-music) · [Location](https://www.vistabrewingtx.com/)\n- **Hoppy Halloween Lunch & Deer Fellow** — Sat, Oct 31, noon–4 PM; live music 2–4 PM; Vista Brewing, Driftwood. Official calendar marks it dog-friendly. Admission price and specific dog rules not stated. [Official calendar](https://www.vistabrewingtx.com/calendars)\n- **Texas Wienerfest** — Sat, Oct 31, 10 AM–5 PM; Sherwood Forest Faire, 1883 Old Hwy 20, McDade. Dogs allowed; non-dachshunds under 45 lb. Leash required except in designated areas; max 6 ft, no retractables. Human ticket required; FAQ lists final-sale price as $19. [Organizer page](https://www.zilkerbark.com/texas-wienerfest) · [FAQ/rules](https://www.zilkerbark.com/texas-wienerfest-faq) · [Venue address](https://www.sherwoodforestfaire.com/contact)\n- **Round Rock Pumpkin Festival & Pumpkin Patch** — Sat, Oct 31, 10 AM–7 PM; Old Settlers Park, 3300 E Palm Valley Blvd., Round Rock. Pet-friendly; dogs must be leashed and owners clean up. Admission listed as $12. [Official event/pet rules](https://roundrockpumpkinfestival.com/) · [Hours](https://roundrockpumpkinfestival.com/hours-%26-specials) · [Admission](https://roundrockpumpkinfestival.com/attractions) · [Location](https://roundrockpumpkinfestival.com/location)\n- **Sunday Live Music: Stone Wheels** — Sun, Nov 1, 2–4 PM; Vista Brewing, Driftwood. Dog-friendly; brewery describes its music shows as free and all-ages. [Official listing](https://www.vistabrewingtx.com/weekly-live-music) · [Location](https://www.vistabrewingtx.com/)\n\n@Paws Pace Newsletter Writer — the sourced brief is ready. Please draft the newsletter using only these details and links, preserving the uncertainties, for Sam’s review.",
        "mentions": [
            "Paws Pace Newsletter Writer"
        ],
        "created_at": "2026-10-27T09:19:02.562860+00:00",
        "subscription_id": null,
        "event": null,
        "attachments": [],
        "reactions": []
    },
    {
        "object": "channel_message",
        "id": "15d8fd93-2dce-45e1-beff-39cac63ff503",
        "channel_id": "8554d409-867f-466e-a7f1-a71adcf0311d",
        "author": {
            "type": "agent",
            "id": "f8d54dbc-6ef6-4d0a-93ae-050ab38c93cd",
            "name": "Paws Pace Newsletter Writer"
        },
        "text": "**DRAFT — for Sam’s review**\n\n**Subject:** Dog-friendly Austin-area events, Oct 27–31\n\nHi everyone,\n\nWe’ve rounded up some events for you and your pup this week. A few listings don’t specify all dog rules or costs, so check the details before heading out.\n\n- **Tuesday Twilights: Dog-Friendly Night** — **Tue, Oct 27, 5–8 PM** at the Lady Bird Johnson Wildflower Center. Dogs must stay leashed (6-foot maximum, no retractables) and on marked trails; vaccination, supervision, and other venue rules apply. Free for members; reservations encouraged. Nonmember admission is unclear. [Official event page](https://www.wildflower.org/event/tuesday-twilights-10-27-2026)\n- **Halloween Dog Pawrty & Costume Contest** — **Wed, Oct 28, 6–10 PM** at Meanwhile Brewing, with the costume contest at 8 PM. The venue lists it as free; specific dog entry rules aren’t stated. [Venue listing](https://www.meanwhilebeer.com/events) · [Event details](https://www.prekindle.com/event/17733-halloween-dog-pawrty-and-costume-contest-austin)\n- **Live Music: Todd Deatherage** — **Fri, Oct 30, 6–8 PM** at Vista Brewing in Driftwood. The listing says it’s free, all-ages, and dog-friendly; the outdoor show is weather-dependent. [Official listing](https://www.vistabrewingtx.com/weekly-live-music) · [Location](https://www.vistabrewingtx.com/)\n- **Bark ’n’ Boo 2026** — **Fri, Oct 30, 7–9 PM** at The Watering Bowl. The listing describes pups, costumes, and prizes; dog rules, price, and registration details are unclear. [Eventbrite listing](https://www.eventbrite.com/e/bark-n-boo-2026-tickets-2002309231813)\n- **Texas Wienerfest** — **Sat, Oct 31, 10 AM–5 PM** at Sherwood Forest Faire in McDade. Dogs are allowed; non-dachshunds must be under 45 lb. Leashes are required except in designated areas, with a 6-foot maximum and no retractables. A human ticket is required; the FAQ lists the final-sale price as $19. The organizer URL in the brief was truncated, so we don’t\n\nI drafted a newsletter from the earlier brief and posted it here for Sam’s review. The updated brief adds Texas Wienerfest and may include more events, but its organizer link is cut off in the message I received. Nothing is running in the background; please share the complete brief/link if you’d like me to update the draft.\n\nI stopped here: this turn ran for 10 minutes, its time limit. Say \"continue\" and I'll pick it up.",
        "mentions": [],
        "created_at": "2026-10-27T09:30:08.031700+00:00",
        "subscription_id": null,
        "event": null,
        "attachments": [],
        "reactions": []
    },
    {
        "object": "channel_message",
        "id": "8f749913-b2ad-4354-b02b-d74e5d7b614c",
        "channel_id": "8554d409-867f-466e-a7f1-a71adcf0311d",
        "author": {
            "type": "account",
            "id": null,
            "name": "owner"
        },
        "text": "@Paws Pace Newsletter Writer Please continue and post a complete newsletter draft now using the full sourced brief in this channel, including all events and working source links. Keep uncertainties explicit and label it for Sam's review; do not send it to clients.",
        "mentions": [
            "Paws Pace Newsletter Writer"
        ],
        "created_at": "2026-10-27T09:30:58.059801+00:00",
        "subscription_id": null,
        "event": null,
        "attachments": [],
        "reactions": []
    },
    {
        "object": "channel_message",
        "id": "6462f22a-45c7-434e-aef5-52efb12d17f6",
        "channel_id": "8554d409-867f-466e-a7f1-a71adcf0311d",
        "author": {
            "type": "agent",
            "id": "f8d54dbc-6ef6-4d0a-93ae-050ab38c93cd",
            "name": "Paws Pace Newsletter Writer"
        },
        "text": "**DRAFT — for Sam’s review**\n\n**Subject:** Dog-friendly events around Austin: Oct 27–31\n\nHi everyone,\n\nWe’ve rounded up some dog-friendly events around Austin this week. Check each listing for the latest details, especially where rules or admission information are unclear.\n\n- **Tuesday Twilights: Dog-Friendly Night** — **Tue, Oct 27, 5–8 PM** at Lady Bird Johnson Wildflower Center, 4801 La Crosse Ave., Austin. Dogs must stay leashed (6 ft max; no retractables) and on marked trails. Vaccination, supervision, and other venue rules apply. Free for members; reservations encouraged. Nonmember admission is unclear. [Official event page](https://www.wildflower.org/event/tuesday-twilights-10-27-2026)\n- **Halloween Dog Pawrty & Costume Contest** — **Wed, Oct 28, 6–10 PM** at Meanwhile Brewing, 3901 Promontory Point Dr., Austin. Costume contest at 8 PM. The venue lists the event as free; specific dog entry rules aren’t stated. [Venue listing](https://www.meanwhilebeer.com/events) · [Event details](https://www.prekindle.com/event/17733-halloween-dog-pawrty-and-costume-contest-austin)\n- **Live Music: Todd Deatherage** — **Fri, Oct 30, 6–8 PM** at Vista Brewing, 13551 FM 150, Driftwood. Free, all ages, and dog-friendly; the outdoor show is weather-dependent. [Official listing](https://www.vistabrewingtx.com/weekly-live-music) · [Location](https://www.vistabrewingtx.com/)\n- **Bark ’n’ Boo 2026** — **Fri, Oct 30, 7–9 PM** at The Watering Bowl, 820 FM 1626, Austin. The listing describes pups, costumes, and prizes; dog rules, price, and registration details are unclear. [Eventbrite listing](https://www.eventbrite.com/e/bark-n-boo-2026-tickets-2002309231813)\n- **Texas Wienerfest** — **Sat, Oct 31, 10 AM–5 PM** at Sherwood Forest Faire, 1883 Old Hwy 20, McDade. Dogs are allowed; non-dachshunds must be under 45 lb. A leash is required except in designated areas (6 ft max; no retractables). A human ticket is required; the FAQ lists a final-sale price of $19. **The organizer link was truncated in the brief, so we can’t include a working source link yet.**\n- **Hoppy Halloween Lunch & Deer Fellow** — **Sat, Oct 31, noon–4 PM; live music 2–4 PM** at Vista Brewing in Driftwood. The official calendar marks it dog-friendly. Admission price and specific dog rules aren’t stated. [Official calendar](https://www.vistabrewingtx.com/calendars)\n\nWe hope you and your pup have a lovely week!\n\nWarmly,  \n**Paws & Pace**\n\n**Note for Sam:** The researcher’s message cuts off after the Texas Wienerfest organizer URL begins (“https://www.zilker…”) and ends with an ellipsis. It may omit additional events through Nov 3, so this draft covers only the six entries visible here and needs the complete brief/link before it can be considered complete.\n\n@Austin Dog Events Researcher Please repost the full brief, including the complete Texas Wienerfest link and any remaining events through Nov 3.",
        "mentions": [
            "Austin Dog Events Researcher"
        ],
        "created_at": "2026-10-27T09:31:16.610043+00:00",
        "subscription_id": null,
        "event": null,
        "attachments": [],
        "reactions": []
    },
    {
        "object": "channel_message",
        "id": "1c6aa99f-b376-4ecd-bbaf-c7c32534bb13",
        "channel_id": "8554d409-867f-466e-a7f1-a71adcf0311d",
        "author": {
            "type": "agent",
            "id": "d34a0e47-f24f-483a-8610-da7d03828513",
            "name": "Austin Dog Events Researcher"
        },
        "text": "**DRAFT — for Sam’s review only; not sent to clients**\n\n**Subject:** Dog-friendly events around Austin: Oct 27–Nov 1\n\nHi everyone,\n\nHere are some dog-friendly events around Austin this week. Please check the linked listings for updates, especially where dog rules, admission, or registration details are unclear.\n\n- **Tuesday Twilights: Dog-Friendly Night** — **Tue, Oct 27, 5–8 PM** at Lady Bird Johnson Wildflower Center, 4801 La Crosse Ave., Austin. Dogs must be leashed (6 ft max; no retractables) and stay on marked trails; vaccination and venue rules apply. Free for members; reservations encouraged. Nonmember admission is unclear. [Official event page](https://www.wildflower.org/event/tuesday-twilights-10-27-2026)\n- **Halloween Dog Pawrty & Costume Contest** — **Wed, Oct 28, 6–10 PM** at Meanwhile Brewing, 3901 Promontory Point Dr., Austin. Costume contest at 8 PM. The venue lists the event as free; specific dog-entry rules aren’t stated. [Venue listing](https://www.meanwhilebeer.com/events) · [Event details](https://www.prekindle.com/event/17733-halloween-dog-pawrty-and-costume-contest-austin)\n- **Live Music: Todd Deatherage** — **Fri, Oct 30, 6–8 PM** at Vista Brewing, 13551 FM 150, Driftwood. The official listing says free, all-ages, and dog-friendly; the outdoor show is weather-dependent. [Official listing](https://www.vistabrewingtx.com/weekly-live-music) · [Location](https://www.vistabrewingtx.com/)\n- **Bark ’n’ Boo 2026** — **Fri, Oct 30, 7–9 PM** at The Watering Bowl, 820 FM 1626, Austin. The listing describes pups, costumes, and prizes. Dog rules, ticket price, and registration details are unclear. [Eventbrite listing](https://www.eventbrite.com/e/bark-n-boo-2026-tickets-2002309231813)\n- **Hoppy Halloween Lunch with Deer Fellow** — **Sat, Oct 31, noon–4 PM; live music 2–4 PM** at Vista Brewing in Driftwood. The official calendar marks it dog-friendly. Admission price and additional dog rules aren’t stated. [Official calendar](https://www.vistabrewingtx.com/calendars) · [Location](https://www.vistabrewingtx.com/)\n- **Texas Wienerfest** — **Sat, Oct 31, 10 AM–5 PM** at Sherwood Forest Faire, 1883 Old Hwy 20, McDade. Dogs are allowed; non-dachshunds must be under 45 lb. Leashes are required except in designated areas (6 ft max; no retractables). A human ticket is required; the FAQ lists a $19 final-sale price. [Organizer event page](https://www.zilkerbark.com/texas-wienerfest) · [FAQ and dog rules](https://www.zilkerbark.com/texas-wienerfest-faq) · [Venue address](https://www.sherwoodforestfaire.com/contact)\n- **Round Rock Pumpkin Festival & Pumpkin Patch** — **Sat, Oct 31, 10 AM–7 PM** at Old Settlers Park, 3300 E Palm Valley Blvd., Round Rock. The organizer describes it as pet-friendly; dogs must be leashed and owners must clean up. Admission is listed at $12. [Official event and pet rules](https://roundrockpumpkinfestival.com/) · [Hours](https://roundrockpumpkinfestival.com/hours-%26-specials) · [Admission](https://roundrockpumpkinfestival.com/attractions) · [Location](https://roundrockpumpkinfestival.com/location)\n- **Sunday Live Music: Stone Wheels** — **Sun, Nov 1, 2–4 PM** at Vista Brewing in Driftwood. The official listing says dog-friendly; the brewery describes its music shows as free and all-ages. [Official listing](https://www.vistabrewingtx.com/weekly-live-music) · [Location](https://www.vistabrewingtx.com/)\n\nHave a fun week, and check event links for the latest details before heading out with your pup!",
        "mentions": [],
        "created_at": "2026-10-27T09:31:29.950392+00:00",
        "subscription_id": null,
        "event": null,
        "attachments": [],
        "reactions": []
    }
];

/** The schedule as it is once its post wakes only the agent it sets to work: the trigger names whom it wakes
 *  (`wakes`), and its message still names the agent that agent hands off to. On 10-27 it woke both. */
export const TEAM_CHANNEL_TRIGGERS_WAKING_ONE: Record<string, unknown>[] = TEAM_CHANNEL_TRIGGERS.map((t) => ({
    ...t,
    wakes: [TEAM_AGENTS.find((a) => a.name === 'Austin Dog Events Researcher')!.id],
}));

/** GET /v1 as the account reads it, for the paths the chat's agent and channel cards read; `triggers` the
 *  channel's schedules, `messages` its timeline (none, by default: as the turn left it). */
export function teamRead(path: string, triggers: Record<string, unknown>[] = TEAM_CHANNEL_TRIGGERS, messages: Record<string, unknown>[] = []): unknown {
    const agent = TEAM_AGENTS.find((a) => path.startsWith(`/v1/agents/${a.id}`));
    if (agent) return path.endsWith('/triggers') ? { object: 'list', data: [], next_cursor: null } : agent;
    if (path === '/v1/channels') return { object: 'list', data: [TEAM_CHANNEL], next_cursor: null };
    if (path === `/v1/channels/${TEAM_CHANNEL.id}`) return TEAM_CHANNEL;
    if (path === `/v1/channels/${TEAM_CHANNEL.id}/triggers`) return { object: 'list', data: triggers, next_cursor: null };
    if (path === `/v1/channels/${TEAM_CHANNEL.id}/messages`) return { object: 'list', data: messages, next_cursor: null };
    return undefined;
}
