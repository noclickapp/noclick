// Which player a Markdown embed (`![caption](url)`) gets. A file NoClick made or recorded is linked by a URL ending in
// its filename, which names its kind: the same rule the phone channels follow to send it as native media.
const VIDEO = /\.(mp4|mov|webm)$/i;
const AUDIO = /\.(mp3|m4a|aac|ogg|amr)$/i;

export type EmbedKind = 'image' | 'audio' | 'video';

export function embedKindOf(url: string): EmbedKind {
    const path = url.split(/[?#]/)[0];
    return VIDEO.test(path) ? 'video' : AUDIO.test(path) ? 'audio' : 'image';
}
