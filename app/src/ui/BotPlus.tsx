/**
 * A robot's head with a plus at its upper right, laid out as lucide's UserPlus is so the two pair ("New agent" beside
 * "Invite people"). One path, so no two strokes overlap and a translucent colour never darkens where they meet.
 */
import { createLucideIcon } from 'lucide-react';

/** Head (11.5 wide, 9 tall, Bot's 4:3), antenna from its middle, ears at its middle, short centred eyes, then the plus. */
export const BOT_PLUS_PATH = [
    'M5 9h7.5a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2z',
    'M8.75 9V5.5H6.25',
    'M1.75 13.5H3M14.5 13.5h1.25',
    'M6.5 12.5v2M11 12.5v2',
    'M19.5 7.5v5M17 10h5',
].join('');

export const BotPlus = createLucideIcon('BotPlus', [['path', { d: BOT_PLUS_PATH, key: 'bot-plus' }]]);
