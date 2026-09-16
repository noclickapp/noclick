# NoClick for Claude Code

Connect Claude Code to NoClick's hosted MCP server. Claude can build, configure,
run, and inspect automations without leaving your coding session.

## Install

Until the plugin is available in the Claude community directory, install it
directly from the NoClick repository:

```text
/plugin marketplace add noclickapp/noclick
/plugin install noclick@noclick
```

After installation, open `/mcp`, select the NoClick server, and authenticate.
NoClick uses OAuth 2.1 with PKCE, so Claude Code opens a browser once and saves
the resulting token locally.

Keep the Claude Code session running while you approve access in the browser.
The session hosts a temporary local callback server that completes the OAuth
hand-off.

## What Claude can do

- Create, update, duplicate, and delete workflows
- Add, configure, connect, and remove workflow nodes
- Search NoClick's integration and operation catalog
- Request credentials and resolve dynamic configuration fields
- Run workflows and individual nodes, then inspect their outputs
- Manage workflow resources and share or publish workflows

The tools act on the NoClick account you authorize. Actions that modify or run
workflows use the same access controls as the NoClick app.

## Try it

```text
List my NoClick workflows.
```

```text
Build a workflow that watches a Slack channel, summarizes new questions, and
adds them to a Google Sheet.
```

```text
Run my customer-support workflow and explain any failed nodes.
```

## Configuration

The plugin connects only to NoClick's production MCP endpoint:

```json
{
  "mcpServers": {
    "noclick": {
      "type": "http",
      "url": "https://api.noclick.io/mcp"
    }
  }
}
```

For manual setup, troubleshooting, and other MCP clients, see the
[NoClick MCP setup guide](https://docs.noclick.com/mcp/setup).

## Links

- [NoClick](https://noclick.com)
- [Documentation](https://docs.noclick.com)
- [Source code](https://github.com/noclickapp/noclick)
- [Privacy policy](https://www.noclick.com/privacy)
- [Terms](https://www.noclick.com/terms)

## License

AGPL-3.0-only. See the repository's [LICENSE](../../LICENSE).
