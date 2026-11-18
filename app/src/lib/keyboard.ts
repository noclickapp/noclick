// Shared keyboard helpers. `isTextEntryTarget` centralizes the "is the user
// currently typing in a field" check so bare-key shortcuts (e.g. "/" opens chat,
// "[" toggles the folder sidebar) don't hijack characters in inputs.

/**
 * The pressed key, lowercased. A keydown Chrome dispatches for an autofill pick
 * carries no `key`, so reading `e.key.toLowerCase()` throws in every listener.
 */
export function pressedKey(e: { key?: string }): string {
    return (e.key ?? '').toLowerCase();
}

/** True when the event target is a text-entry field (input/textarea/contenteditable). */
export function isTextEntryTarget(target: EventTarget | null): boolean {
    if (!(target instanceof HTMLElement)) return false;
    return (
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.isContentEditable
    );
}
