// Shared keyboard helpers. `isTextEntryTarget` centralizes the "is the user
// currently typing in a field" check so bare-key shortcuts (e.g. "/" opens chat,
// "[" toggles the folder sidebar) don't hijack characters in inputs. Extracted
// from the copies previously inlined in Dashboard and the command palette.

/** True when the event target is a text-entry field (input/textarea/contenteditable). */
export function isTextEntryTarget(target: EventTarget | null): boolean {
    if (!(target instanceof HTMLElement)) return false;
    return (
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.isContentEditable
    );
}

/** True when one of our dialogs is open, so bare-key shortcuts stand down. */
export function isModalOpen(): boolean {
    return document.querySelector('[role="dialog"]') !== null;
}
