import { describe, expect, it } from 'vitest';
import { normalizeYoutubeTarget } from './remark-youtube';

describe('normalizeYoutubeTarget', () => {
    it('accepts raw ids, the explicit prefix, and trusted YouTube URLs', () => {
        expect(normalizeYoutubeTarget('AbCdEfGhI12')).toBe('AbCdEfGhI12');
        expect(normalizeYoutubeTarget('youtube:AbCdEfGhI12?t=43')).toBe(
            'AbCdEfGhI12?t=43'
        );
        expect(
            normalizeYoutubeTarget(
                'https://www.youtube.com/watch?v=AbCdEfGhI12'
            )
        ).toBe('AbCdEfGhI12');
        expect(normalizeYoutubeTarget('youtu.be/AbCdEfGhI12')).toBe(
            'AbCdEfGhI12'
        );
    });

    it('rejects lookalike hosts and unsupported URL shapes', () => {
        expect(
            normalizeYoutubeTarget(
                'https://youtube.com.example.test/watch?v=AbCdEfGhI12'
            )
        ).toBeNull();
        expect(
            normalizeYoutubeTarget('https://example.test/youtu.be/AbCdEfGhI12')
        ).toBeNull();
        expect(
            normalizeYoutubeTarget(
                'javascript://youtube.com/watch?v=AbCdEfGhI12'
            )
        ).toBeNull();
    });
});
