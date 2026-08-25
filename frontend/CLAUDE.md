## File Creation Guidelines
- Whenever you create a new file, always add a brief 2-3 sentence comment on top of the file explaining what it does and why it was added (context)

## Development Guidelines
- DO NOT try to run `npm run dev` as most of the time the user would have a running session already

## Persistent Storage
We have two separate hooks for two storing data in components for a longer period of time:
1. useCachedValtioState - For persistent data we want to cache (name, description, screenshots, etc.). This data will be cached in Redis as well as local IndexedDB.
2. useValtioState - For volatile data that should only live in session (status, port, url) and is stored in the local valtio store so that on component re-renders we preserve state.