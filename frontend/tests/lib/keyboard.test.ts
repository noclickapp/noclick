// @vitest-environment jsdom

import { describe, it, expect, afterEach } from 'vitest';
import { isModalOpen } from '~/lib/keyboard';

const html = (markup: string) => {
    document.body.innerHTML = markup;
};

afterEach(() => {
    document.body.innerHTML = '';
});

describe('isModalOpen', () => {
    it('is false on a bare page', () => {
        html('<div id="root"></div>');
        expect(isModalOpen()).toBe(false);
    });

    it('is true while one of our dialogs is open', () => {
        html('<div role="dialog" aria-label="Workflow settings"></div>');
        expect(isModalOpen()).toBe(true);
    });

});
