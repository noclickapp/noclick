// The launch screen an iPhone shows when NoClick opens from the home screen: black with the mark, until the first
// page paints. Without one iOS shows white for as long as the document and its stylesheet take, and nothing inside
// the document can paint sooner (WebKit holds every paint while a head stylesheet is pending).
import type { HtmlLinkDescriptor } from 'react-router';

/** iPhone screens in CSS points and pixel ratio. Each image in public/startup is icon-512.png's mark, 64pt wide,
 *  centred on black: ffmpeg -i public/icon-512.png -vf "scale=S:S,pad=W:H:(ow-iw)/2:(oh-ih)/2:black,format=gray"
 *  public/startup/WxH.png, with S = 64 × ratio ÷ 0.7 (the mark fills 70% of the icon). */
const SCREENS: readonly (readonly [width: number, height: number, ratio: number])[] = [
    [440, 956, 3],
    [430, 932, 3],
    [428, 926, 3],
    [420, 912, 3],
    [414, 896, 3],
    [414, 896, 2],
    [402, 874, 3],
    [393, 852, 3],
    [390, 844, 3],
    [375, 812, 3],
    [375, 667, 2],
];

export const APPLE_STARTUP_IMAGES: HtmlLinkDescriptor[] = SCREENS.map(([width, height, ratio]) => ({
    rel: 'apple-touch-startup-image',
    media: `(device-width: ${width}px) and (device-height: ${height}px) and (-webkit-device-pixel-ratio: ${ratio}) and (orientation: portrait)`,
    href: `/startup/${width * ratio}x${height * ratio}.png`,
}));
