import { describe, expect, it } from 'vitest';
import { getDeveloperSettingsNote, registerDeveloperSettingsNote } from './developerSettingsNote';

describe('developer settings note', () => {
    it('is absent until a deployment registers one', () => {
        expect(getDeveloperSettingsNote()).toBeNull();
        const Note = () => null;
        registerDeveloperSettingsNote(Note);
        expect(getDeveloperSettingsNote()).toBe(Note);
    });
});
