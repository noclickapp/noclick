// Where a deployment's developer console lives. When one is registered, Settings → Developer opens it instead of
// making keys itself; the engine registers none, so the open edition keeps its own key list.
let consoleHref: string | null = null;

export function registerDeveloperConsole(href: string): void {
    consoleHref = href;
}

export function getDeveloperConsoleHref(): string | null {
    return consoleHref;
}
