// A bench account's follow-up in the web chat (2026-11-12), as GET /v1/agents/{id}/conversations/owner reads it back: a
// long turn whose saved calls are its newest 50 (utils.tool_call_log keeps a turn's last calls), each result cut at 500
// characters as the turn's audit keeps it, ending on the two plan links it made (their answers in the connection
// view's order, the link first: connect.service.connection_view). Before both, the turn's first 50 calls were kept and
// a connection's link sat past 500 characters, so no card drew.

export const PLAN_LINK_TOKENS = { claude: "claude-plan-link-0000000000000000000000000000000000000000000000", chatgpt: "chatgpt-plan-link-000000000000000000000000000000000000000000000" };

export const PLAN_LINKS_HISTORY: Record<string, unknown>[] = [
    {
        "role": "user",
        "text": "Could this run on my Claude or ChatGPT plan instead?",
        "created_at": "2026-11-12T08:51:00.000000+00:00"
    },
    {
        "role": "assistant",
        "text": "Yes: sign in with whichever plan you have in the card below, and I'll run on it from then on. It costs you less, on a subscription you already pay for.",
        "created_at": "2026-11-12T08:53:00.000000+00:00",
        "tool_calls": [
            {
                "tool": "noclick__search",
                "arguments": {
                    "query": "connect a Claude or ChatGPT plan to an agent (0)",
                    "kind": "guide"
                },
                "result": "{\"success\": true, \"results\": [{\"id\": \"guide:connections#model-providers\", \"kind\": \"guide\", \"title\": \"Connections: Model providers\", \"snippet\": \"A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude o",
                "is_error": false,
                "created_at": "2026-11-12T08:52:01.000000+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "operation": "connections_create",
                    "detail": "full"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"connections_create\", \"method\": \"POST\", \"path\": \"/v1/connections\", \"risk\": \"write\", \"summary\": \"Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that c",
                "is_error": false,
                "created_at": "2026-11-12T08:52:02.000000+00:00"
            },
            {
                "tool": "noclick__fetch",
                "arguments": {
                    "id": "guide:connections#when-a-plan-fits"
                },
                "result": "{\"success\": true, \"status\": \"built\", \"id\": \"guide:connections#when-a-plan-fits\", \"kind\": \"guide\", \"text\": \"### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. \"}",
                "is_error": false,
                "created_at": "2026-11-12T08:52:03.000000+00:00"
            },
            {
                "tool": "noclick__search",
                "arguments": {
                    "query": "connect a Claude or ChatGPT plan to an agent (3)",
                    "kind": "guide"
                },
                "result": "{\"success\": true, \"results\": [{\"id\": \"guide:connections#model-providers\", \"kind\": \"guide\", \"title\": \"Connections: Model providers\", \"snippet\": \"A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude o",
                "is_error": false,
                "created_at": "2026-11-12T08:52:04.000000+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "operation": "connections_create",
                    "detail": "full"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"connections_create\", \"method\": \"POST\", \"path\": \"/v1/connections\", \"risk\": \"write\", \"summary\": \"Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that c",
                "is_error": false,
                "created_at": "2026-11-12T08:52:05.000000+00:00"
            },
            {
                "tool": "noclick__fetch",
                "arguments": {
                    "id": "guide:connections#when-a-plan-fits"
                },
                "result": "{\"success\": true, \"status\": \"built\", \"id\": \"guide:connections#when-a-plan-fits\", \"kind\": \"guide\", \"text\": \"### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. \"}",
                "is_error": false,
                "created_at": "2026-11-12T08:52:06.000000+00:00"
            },
            {
                "tool": "noclick__search",
                "arguments": {
                    "query": "connect a Claude or ChatGPT plan to an agent (6)",
                    "kind": "guide"
                },
                "result": "{\"success\": true, \"results\": [{\"id\": \"guide:connections#model-providers\", \"kind\": \"guide\", \"title\": \"Connections: Model providers\", \"snippet\": \"A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude o",
                "is_error": false,
                "created_at": "2026-11-12T08:52:07.000000+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "operation": "connections_create",
                    "detail": "full"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"connections_create\", \"method\": \"POST\", \"path\": \"/v1/connections\", \"risk\": \"write\", \"summary\": \"Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that c",
                "is_error": false,
                "created_at": "2026-11-12T08:52:08.000000+00:00"
            },
            {
                "tool": "noclick__fetch",
                "arguments": {
                    "id": "guide:connections#when-a-plan-fits"
                },
                "result": "{\"success\": true, \"status\": \"built\", \"id\": \"guide:connections#when-a-plan-fits\", \"kind\": \"guide\", \"text\": \"### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. \"}",
                "is_error": false,
                "created_at": "2026-11-12T08:52:09.000000+00:00"
            },
            {
                "tool": "noclick__search",
                "arguments": {
                    "query": "connect a Claude or ChatGPT plan to an agent (9)",
                    "kind": "guide"
                },
                "result": "{\"success\": true, \"results\": [{\"id\": \"guide:connections#model-providers\", \"kind\": \"guide\", \"title\": \"Connections: Model providers\", \"snippet\": \"A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude o",
                "is_error": false,
                "created_at": "2026-11-12T08:52:10.000000+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "operation": "connections_create",
                    "detail": "full"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"connections_create\", \"method\": \"POST\", \"path\": \"/v1/connections\", \"risk\": \"write\", \"summary\": \"Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that c",
                "is_error": false,
                "created_at": "2026-11-12T08:52:11.000000+00:00"
            },
            {
                "tool": "noclick__fetch",
                "arguments": {
                    "id": "guide:connections#when-a-plan-fits"
                },
                "result": "{\"success\": true, \"status\": \"built\", \"id\": \"guide:connections#when-a-plan-fits\", \"kind\": \"guide\", \"text\": \"### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. \"}",
                "is_error": false,
                "created_at": "2026-11-12T08:52:12.000000+00:00"
            },
            {
                "tool": "noclick__search",
                "arguments": {
                    "query": "connect a Claude or ChatGPT plan to an agent (12)",
                    "kind": "guide"
                },
                "result": "{\"success\": true, \"results\": [{\"id\": \"guide:connections#model-providers\", \"kind\": \"guide\", \"title\": \"Connections: Model providers\", \"snippet\": \"A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude o",
                "is_error": false,
                "created_at": "2026-11-12T08:52:13.000000+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "operation": "connections_create",
                    "detail": "full"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"connections_create\", \"method\": \"POST\", \"path\": \"/v1/connections\", \"risk\": \"write\", \"summary\": \"Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that c",
                "is_error": false,
                "created_at": "2026-11-12T08:52:14.000000+00:00"
            },
            {
                "tool": "noclick__fetch",
                "arguments": {
                    "id": "guide:connections#when-a-plan-fits"
                },
                "result": "{\"success\": true, \"status\": \"built\", \"id\": \"guide:connections#when-a-plan-fits\", \"kind\": \"guide\", \"text\": \"### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. \"}",
                "is_error": false,
                "created_at": "2026-11-12T08:52:15.000000+00:00"
            },
            {
                "tool": "noclick__search",
                "arguments": {
                    "query": "connect a Claude or ChatGPT plan to an agent (15)",
                    "kind": "guide"
                },
                "result": "{\"success\": true, \"results\": [{\"id\": \"guide:connections#model-providers\", \"kind\": \"guide\", \"title\": \"Connections: Model providers\", \"snippet\": \"A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude o",
                "is_error": false,
                "created_at": "2026-11-12T08:52:16.000000+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "operation": "connections_create",
                    "detail": "full"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"connections_create\", \"method\": \"POST\", \"path\": \"/v1/connections\", \"risk\": \"write\", \"summary\": \"Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that c",
                "is_error": false,
                "created_at": "2026-11-12T08:52:17.000000+00:00"
            },
            {
                "tool": "noclick__fetch",
                "arguments": {
                    "id": "guide:connections#when-a-plan-fits"
                },
                "result": "{\"success\": true, \"status\": \"built\", \"id\": \"guide:connections#when-a-plan-fits\", \"kind\": \"guide\", \"text\": \"### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. \"}",
                "is_error": false,
                "created_at": "2026-11-12T08:52:18.000000+00:00"
            },
            {
                "tool": "noclick__search",
                "arguments": {
                    "query": "connect a Claude or ChatGPT plan to an agent (18)",
                    "kind": "guide"
                },
                "result": "{\"success\": true, \"results\": [{\"id\": \"guide:connections#model-providers\", \"kind\": \"guide\", \"title\": \"Connections: Model providers\", \"snippet\": \"A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude o",
                "is_error": false,
                "created_at": "2026-11-12T08:52:19.000000+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "operation": "connections_create",
                    "detail": "full"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"connections_create\", \"method\": \"POST\", \"path\": \"/v1/connections\", \"risk\": \"write\", \"summary\": \"Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that c",
                "is_error": false,
                "created_at": "2026-11-12T08:52:20.000000+00:00"
            },
            {
                "tool": "noclick__fetch",
                "arguments": {
                    "id": "guide:connections#when-a-plan-fits"
                },
                "result": "{\"success\": true, \"status\": \"built\", \"id\": \"guide:connections#when-a-plan-fits\", \"kind\": \"guide\", \"text\": \"### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. \"}",
                "is_error": false,
                "created_at": "2026-11-12T08:52:21.000000+00:00"
            },
            {
                "tool": "noclick__search",
                "arguments": {
                    "query": "connect a Claude or ChatGPT plan to an agent (21)",
                    "kind": "guide"
                },
                "result": "{\"success\": true, \"results\": [{\"id\": \"guide:connections#model-providers\", \"kind\": \"guide\", \"title\": \"Connections: Model providers\", \"snippet\": \"A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude o",
                "is_error": false,
                "created_at": "2026-11-12T08:52:22.000000+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "operation": "connections_create",
                    "detail": "full"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"connections_create\", \"method\": \"POST\", \"path\": \"/v1/connections\", \"risk\": \"write\", \"summary\": \"Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that c",
                "is_error": false,
                "created_at": "2026-11-12T08:52:23.000000+00:00"
            },
            {
                "tool": "noclick__fetch",
                "arguments": {
                    "id": "guide:connections#when-a-plan-fits"
                },
                "result": "{\"success\": true, \"status\": \"built\", \"id\": \"guide:connections#when-a-plan-fits\", \"kind\": \"guide\", \"text\": \"### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. \"}",
                "is_error": false,
                "created_at": "2026-11-12T08:52:24.000000+00:00"
            },
            {
                "tool": "noclick__search",
                "arguments": {
                    "query": "connect a Claude or ChatGPT plan to an agent (24)",
                    "kind": "guide"
                },
                "result": "{\"success\": true, \"results\": [{\"id\": \"guide:connections#model-providers\", \"kind\": \"guide\", \"title\": \"Connections: Model providers\", \"snippet\": \"A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude o",
                "is_error": false,
                "created_at": "2026-11-12T08:52:25.000000+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "operation": "connections_create",
                    "detail": "full"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"connections_create\", \"method\": \"POST\", \"path\": \"/v1/connections\", \"risk\": \"write\", \"summary\": \"Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that c",
                "is_error": false,
                "created_at": "2026-11-12T08:52:26.000000+00:00"
            },
            {
                "tool": "noclick__fetch",
                "arguments": {
                    "id": "guide:connections#when-a-plan-fits"
                },
                "result": "{\"success\": true, \"status\": \"built\", \"id\": \"guide:connections#when-a-plan-fits\", \"kind\": \"guide\", \"text\": \"### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. \"}",
                "is_error": false,
                "created_at": "2026-11-12T08:52:27.000000+00:00"
            },
            {
                "tool": "noclick__search",
                "arguments": {
                    "query": "connect a Claude or ChatGPT plan to an agent (27)",
                    "kind": "guide"
                },
                "result": "{\"success\": true, \"results\": [{\"id\": \"guide:connections#model-providers\", \"kind\": \"guide\", \"title\": \"Connections: Model providers\", \"snippet\": \"A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude o",
                "is_error": false,
                "created_at": "2026-11-12T08:52:28.000000+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "operation": "connections_create",
                    "detail": "full"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"connections_create\", \"method\": \"POST\", \"path\": \"/v1/connections\", \"risk\": \"write\", \"summary\": \"Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that c",
                "is_error": false,
                "created_at": "2026-11-12T08:52:29.000000+00:00"
            },
            {
                "tool": "noclick__fetch",
                "arguments": {
                    "id": "guide:connections#when-a-plan-fits"
                },
                "result": "{\"success\": true, \"status\": \"built\", \"id\": \"guide:connections#when-a-plan-fits\", \"kind\": \"guide\", \"text\": \"### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. \"}",
                "is_error": false,
                "created_at": "2026-11-12T08:52:30.000000+00:00"
            },
            {
                "tool": "noclick__search",
                "arguments": {
                    "query": "connect a Claude or ChatGPT plan to an agent (30)",
                    "kind": "guide"
                },
                "result": "{\"success\": true, \"results\": [{\"id\": \"guide:connections#model-providers\", \"kind\": \"guide\", \"title\": \"Connections: Model providers\", \"snippet\": \"A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude o",
                "is_error": false,
                "created_at": "2026-11-12T08:52:31.000000+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "operation": "connections_create",
                    "detail": "full"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"connections_create\", \"method\": \"POST\", \"path\": \"/v1/connections\", \"risk\": \"write\", \"summary\": \"Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that c",
                "is_error": false,
                "created_at": "2026-11-12T08:52:32.000000+00:00"
            },
            {
                "tool": "noclick__fetch",
                "arguments": {
                    "id": "guide:connections#when-a-plan-fits"
                },
                "result": "{\"success\": true, \"status\": \"built\", \"id\": \"guide:connections#when-a-plan-fits\", \"kind\": \"guide\", \"text\": \"### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. \"}",
                "is_error": false,
                "created_at": "2026-11-12T08:52:33.000000+00:00"
            },
            {
                "tool": "noclick__search",
                "arguments": {
                    "query": "connect a Claude or ChatGPT plan to an agent (33)",
                    "kind": "guide"
                },
                "result": "{\"success\": true, \"results\": [{\"id\": \"guide:connections#model-providers\", \"kind\": \"guide\", \"title\": \"Connections: Model providers\", \"snippet\": \"A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude o",
                "is_error": false,
                "created_at": "2026-11-12T08:52:34.000000+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "operation": "connections_create",
                    "detail": "full"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"connections_create\", \"method\": \"POST\", \"path\": \"/v1/connections\", \"risk\": \"write\", \"summary\": \"Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that c",
                "is_error": false,
                "created_at": "2026-11-12T08:52:35.000000+00:00"
            },
            {
                "tool": "noclick__fetch",
                "arguments": {
                    "id": "guide:connections#when-a-plan-fits"
                },
                "result": "{\"success\": true, \"status\": \"built\", \"id\": \"guide:connections#when-a-plan-fits\", \"kind\": \"guide\", \"text\": \"### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. \"}",
                "is_error": false,
                "created_at": "2026-11-12T08:52:36.000000+00:00"
            },
            {
                "tool": "noclick__search",
                "arguments": {
                    "query": "connect a Claude or ChatGPT plan to an agent (36)",
                    "kind": "guide"
                },
                "result": "{\"success\": true, \"results\": [{\"id\": \"guide:connections#model-providers\", \"kind\": \"guide\", \"title\": \"Connections: Model providers\", \"snippet\": \"A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude o",
                "is_error": false,
                "created_at": "2026-11-12T08:52:37.000000+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "operation": "connections_create",
                    "detail": "full"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"connections_create\", \"method\": \"POST\", \"path\": \"/v1/connections\", \"risk\": \"write\", \"summary\": \"Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that c",
                "is_error": false,
                "created_at": "2026-11-12T08:52:38.000000+00:00"
            },
            {
                "tool": "noclick__fetch",
                "arguments": {
                    "id": "guide:connections#when-a-plan-fits"
                },
                "result": "{\"success\": true, \"status\": \"built\", \"id\": \"guide:connections#when-a-plan-fits\", \"kind\": \"guide\", \"text\": \"### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. \"}",
                "is_error": false,
                "created_at": "2026-11-12T08:52:39.000000+00:00"
            },
            {
                "tool": "noclick__search",
                "arguments": {
                    "query": "connect a Claude or ChatGPT plan to an agent (39)",
                    "kind": "guide"
                },
                "result": "{\"success\": true, \"results\": [{\"id\": \"guide:connections#model-providers\", \"kind\": \"guide\", \"title\": \"Connections: Model providers\", \"snippet\": \"A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude o",
                "is_error": false,
                "created_at": "2026-11-12T08:52:40.000000+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "operation": "connections_create",
                    "detail": "full"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"connections_create\", \"method\": \"POST\", \"path\": \"/v1/connections\", \"risk\": \"write\", \"summary\": \"Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that c",
                "is_error": false,
                "created_at": "2026-11-12T08:52:41.000000+00:00"
            },
            {
                "tool": "noclick__fetch",
                "arguments": {
                    "id": "guide:connections#when-a-plan-fits"
                },
                "result": "{\"success\": true, \"status\": \"built\", \"id\": \"guide:connections#when-a-plan-fits\", \"kind\": \"guide\", \"text\": \"### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. \"}",
                "is_error": false,
                "created_at": "2026-11-12T08:52:42.000000+00:00"
            },
            {
                "tool": "noclick__search",
                "arguments": {
                    "query": "connect a Claude or ChatGPT plan to an agent (42)",
                    "kind": "guide"
                },
                "result": "{\"success\": true, \"results\": [{\"id\": \"guide:connections#model-providers\", \"kind\": \"guide\", \"title\": \"Connections: Model providers\", \"snippet\": \"A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude o",
                "is_error": false,
                "created_at": "2026-11-12T08:52:43.000000+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "operation": "connections_create",
                    "detail": "full"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"connections_create\", \"method\": \"POST\", \"path\": \"/v1/connections\", \"risk\": \"write\", \"summary\": \"Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that c",
                "is_error": false,
                "created_at": "2026-11-12T08:52:44.000000+00:00"
            },
            {
                "tool": "noclick__fetch",
                "arguments": {
                    "id": "guide:connections#when-a-plan-fits"
                },
                "result": "{\"success\": true, \"status\": \"built\", \"id\": \"guide:connections#when-a-plan-fits\", \"kind\": \"guide\", \"text\": \"### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. \"}",
                "is_error": false,
                "created_at": "2026-11-12T08:52:45.000000+00:00"
            },
            {
                "tool": "noclick__search",
                "arguments": {
                    "query": "connect a Claude or ChatGPT plan to an agent (45)",
                    "kind": "guide"
                },
                "result": "{\"success\": true, \"results\": [{\"id\": \"guide:connections#model-providers\", \"kind\": \"guide\", \"title\": \"Connections: Model providers\", \"snippet\": \"A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude or ChatGPT plan. A model provider's connection holds what an agent on a coding harness thinks with: an API key, or a Claude o",
                "is_error": false,
                "created_at": "2026-11-12T08:52:46.000000+00:00"
            },
            {
                "tool": "noclick__api_describe",
                "arguments": {
                    "operation": "connections_create",
                    "detail": "full"
                },
                "result": "{\"success\": true, \"operation\": {\"name\": \"connections_create\", \"method\": \"POST\", \"path\": \"/v1/connections\", \"risk\": \"write\", \"summary\": \"Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that credential at once; without, it is pending and carries a `connect_link` for a person to finish. Create Connection. With `data` the connection holds that c",
                "is_error": false,
                "created_at": "2026-11-12T08:52:47.000000+00:00"
            },
            {
                "tool": "noclick__fetch",
                "arguments": {
                    "id": "guide:connections#when-a-plan-fits"
                },
                "result": "{\"success\": true, \"status\": \"built\", \"id\": \"guide:connections#when-a-plan-fits\", \"kind\": \"guide\", \"text\": \"### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. ### When a plan fits\\n\\nA Claude or ChatGPT plan is one person's own subscription. \"}",
                "is_error": false,
                "created_at": "2026-11-12T08:52:48.000000+00:00"
            },
            {
                "tool": "noclick__api_call",
                "arguments": {
                    "operation": "connections_create",
                    "arguments": {
                        "name": "claude-plan",
                        "integration": "anthropic",
                        "reason": "Run on your Claude plan: it costs you less.",
                        "use_for": {
                            "agent": "agent:coordinator",
                            "harness": "claude_code"
                        }
                    }
                },
                "result": "{\"operation_id\": \"79c38d3e-889b-48ea-a360-ca058a2da098\", \"status\": \"awaiting_human\", \"success\": true, \"response\": {\"object\": \"connection\", \"id\": \"557957fa-1b15-4dee-8599-55303ad55f06\", \"name\": \"claude-plan\", \"connect_link\": {\"url\": \"https://www.noclick.com/credential/provide/claude-plan-link-0000000000000000000000000000000000000000000000\", \"credential_type\": \"agent_anthropic\", \"use_for\": {\"agent_id\": \"88c7ea48-f00a-49b1-80f2-2fdee9a2c22c\", \"harness\": \"claude_code\"}, \"id\": \"397c32dd-2dfd-4f6e-8a",
                "is_error": false,
                "created_at": "2026-11-12T08:52:49.000000+00:00"
            },
            {
                "tool": "noclick__api_call",
                "arguments": {
                    "operation": "connections_create",
                    "arguments": {
                        "name": "chatgpt-plan",
                        "integration": "openai",
                        "reason": "Run on your ChatGPT plan: it costs you less.",
                        "use_for": {
                            "agent": "agent:coordinator",
                            "harness": "codex"
                        }
                    }
                },
                "result": "{\"operation_id\": \"ea1311eb-79f7-456f-bf3c-52f1db0b8d70\", \"status\": \"awaiting_human\", \"success\": true, \"response\": {\"object\": \"connection\", \"id\": \"5fe4da73-8f14-4398-b43e-2aebea5427ca\", \"name\": \"chatgpt-plan\", \"connect_link\": {\"url\": \"https://www.noclick.com/credential/provide/chatgpt-plan-link-000000000000000000000000000000000000000000000\", \"credential_type\": \"agent_openai\", \"use_for\": {\"agent_id\": \"88c7ea48-f00a-49b1-80f2-2fdee9a2c22c\", \"harness\": \"codex\"}, \"id\": \"f19a321f-7764-4370-bdd8-5a2c1",
                "is_error": false,
                "created_at": "2026-11-12T08:52:50.000000+00:00"
            }
        ]
    }
];
