import { nc } from '~/lib/nc';

export default async function () {
    nc.assert.includes(
        window.location.pathname,
        '/auth/login',
        'Open the login route before running this test'
    );

    const video = (await nc.wait.forElement(
        'video[aria-label="Slowly rotating black hole visualization"]'
    )) as HTMLVideoElement;
    const sources = Array.from(video.querySelectorAll('source')).map((source) =>
        source.getAttribute('src')
    );

    nc.assert.deepEqual(
        sources,
        ['/video/blackhole-v2-16s.av1.mp4', '/video/blackhole-v2-16s.mp4'],
        'Login should offer the compressed AV1 asset with an H.264 fallback'
    );
    nc.assert.truthy(video.autoplay, 'Black-hole video should autoplay');
    nc.assert.truthy(video.loop, 'Black-hole video should loop');
    nc.assert.truthy(video.muted, 'Black-hole video should remain muted');
    nc.assert.equal(
        video.getAttribute('poster'),
        '/video/blackhole-v2-16s-first-frame.webp',
        'Black-hole video should use its exact first frame while loading'
    );
    nc.assert.equal(
        video.preload,
        'metadata',
        'Black-hole video should avoid eager full preloading'
    );

    await nc.wait.until(
        () => video.readyState >= HTMLMediaElement.HAVE_METADATA,
        5_000
    );

    nc.assert.equal(
        video.videoWidth,
        1470,
        'Black-hole video should retain its source width'
    );
    nc.assert.equal(
        video.videoHeight,
        630,
        'Black-hole video should retain its source height'
    );
    nc.assert.truthy(
        video.duration > 16 && video.duration < 16.1,
        'Black-hole loop should use the approved 16-second render'
    );
    nc.assert.falsy(
        video.error,
        'Black-hole video should decode without errors'
    );

    const videoStyle = getComputedStyle(video);
    nc.assert.truthy(
        videoStyle.transform !== 'none',
        'Black-hole composition should be angled'
    );
    nc.assert.truthy(
        Number.parseFloat(videoStyle.height) <= video.videoHeight,
        'Black-hole composition should not be upscaled beyond its source height'
    );
    nc.assert.truthy(
        video.getBoundingClientRect().width <= window.innerWidth * 0.91,
        'Black-hole composition should remain a controlled fraction of the viewport width'
    );
    nc.assert.truthy(
        video.getBoundingClientRect().right > window.innerWidth,
        'Black-hole composition should extend off-canvas'
    );
    nc.assert.truthy(
        video.parentElement!.getBoundingClientRect().width /
            window.innerWidth <=
            0.46,
        'Standard auth cosmic panel should use 45% of the page'
    );

    return {
        currentSrc: video.currentSrc,
        duration: video.duration,
        dimensions: `${video.videoWidth}x${video.videoHeight}`,
        readyState: video.readyState,
    };
}
