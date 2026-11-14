// Every launch-screen link points at a PNG in public/startup whose pixels match the screen its media query names:
// iOS silently skips an image of the wrong size and shows white instead.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { APPLE_STARTUP_IMAGES } from '~/lib/appleStartupImages';

const PUBLIC = join(__dirname, '../../public');

/** A PNG's width and height, from its IHDR chunk. */
function pngSize(path: string): [number, number] {
    const bytes = readFileSync(path);
    expect(bytes.subarray(1, 4).toString('latin1'), `${path} is a PNG`).toBe('PNG');
    return [bytes.readUInt32BE(16), bytes.readUInt32BE(20)];
}

describe('APPLE_STARTUP_IMAGES', () => {
    it('gives each iPhone screen an image of exactly its pixels', () => {
        expect(APPLE_STARTUP_IMAGES.length).toBeGreaterThan(0);
        const medias = new Set<string>();
        for (const link of APPLE_STARTUP_IMAGES) {
            expect(link.rel).toBe('apple-touch-startup-image');
            const media = String(link.media);
            const [, width, height, ratio] = media.match(/device-width: (\d+)px\) and \(device-height: (\d+)px\) and \(-webkit-device-pixel-ratio: (\d+)\)/)!.map(Number);
            expect(pngSize(join(PUBLIC, String(link.href)))).toEqual([width * ratio, height * ratio]);
            medias.add(media);
        }
        expect(medias.size, 'two images for one screen').toBe(APPLE_STARTUP_IMAGES.length);
    });

    it('serves the precomposed touch icon iOS asks for at the root', () => {
        expect(pngSize(join(PUBLIC, 'apple-touch-icon-precomposed.png'))).toEqual([180, 180]);
    });
});
