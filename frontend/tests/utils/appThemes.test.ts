// Transform smoke: importing the themed-frame modules catches syntax/type-level
// import errors through vitest's esbuild pipeline.
import { describe, it, expect } from 'vitest';
import { resolveAppTheme, APP_THEMES } from '~/components/design/rehearsal/appThemes';
import { InboundMessage, OutboundMessage } from '~/components/design/rehearsal/native';
import { BespokeInbound } from '~/components/design/rehearsal/bespokeFrames';

describe('appThemes', () => {
    it('the themed frame modules import cleanly', () => {
        expect(typeof InboundMessage).toBe('function');
        expect(typeof OutboundMessage).toBe('function');
        expect(typeof BespokeInbound).toBe('function');
    });
    it('resolves direct slugs and aliases', () => {
        expect(resolveAppTheme('whatsapp')?.shape).toBe('bubble');
        expect(resolveAppTheme('github_rest')?.name).toBe('GitHub');
        expect(resolveAppTheme('cal_com')?.shape).toBe('booking');
        expect(resolveAppTheme('monday')?.shape).toBe('monday');
        expect(resolveAppTheme('unknown-app')).toBeUndefined();
    });
    it('every theme carries a full palette', () => {
        for (const [slug, t] of Object.entries(APP_THEMES)) {
            for (const k of ['surface', 'accent', 'ink', 'sub', 'border', 'author'] as const) {
                expect(t[k], `${slug}.${k}`).toBeTruthy();
            }
            if (t.shape === 'bubble') {
                expect(t.bubbleIn, `${slug}.bubbleIn`).toBeTruthy();
                expect(t.bubbleOut, `${slug}.bubbleOut`).toBeTruthy();
            }
        }
    });
});
