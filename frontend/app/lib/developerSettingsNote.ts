// One line a deployment may add under Settings → Developer's heading (e.g. a
// pointer to where other kinds of keys are managed). The engine registers
// none, so the open edition renders nothing extra.
import type { ComponentType } from 'react';

let note: ComponentType | null = null;

export function registerDeveloperSettingsNote(Note: ComponentType): void {
    note = Note;
}

export function getDeveloperSettingsNote(): ComponentType | null {
    return note;
}
