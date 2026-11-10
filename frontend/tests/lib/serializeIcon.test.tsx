import { describe, expect, it } from 'vitest';
import { serializeIcon } from '~/lib/serializeIcon.server';
import { TwoChatNode } from '~/components/workflow/nodes/integrations/2chat';

describe('serialized node icons', () => {
    it('drop the image preload hint and load the image as it comes into view', () => {
        const html = serializeIcon(TwoChatNode.Icon);
        expect(html).not.toContain('<link');
        expect(html).toMatch(/^<img loading="lazy" decoding="async" src="\/icons\/2chat.svg"/);
    });

    it('leave inline svg and an image that already says how it loads alone', () => {
        expect(serializeIcon(() => <svg viewBox="0 0 1 1"><path d="M0 0" /></svg>)).toBe('<svg viewBox="0 0 1 1"><path d="M0 0"></path></svg>');
        expect(serializeIcon(() => <img src="/icons/x.svg" alt="" loading="eager" />)).toBe('<img src="/icons/x.svg" alt="" loading="eager"/>');
    });
});
