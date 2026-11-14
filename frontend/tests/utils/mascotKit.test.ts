// The mascot kit: the same agent draws the same mascot every time, its role picks its props, each size keeps only
// the detail it can show, and nothing an agent carries (its id, its name) reaches the markup.
import { describe, expect, it } from 'vitest';
import { draw, generate, PROP_KEYS, PROPS, propsFor, STATES, tierOf, type MascotLook, type MascotState, type PropKey } from '~/components/shell/channels/mascot/kit';

const STATE_KEYS = Object.keys(STATES) as MascotState[];
/** `look` wearing `props`, each in its standard look and upright. */
const wearing = (look: MascotLook, props: PropKey[]): MascotLook => ({ ...look, props, pv: props.map(() => ({ tilt: 0, alt: false })) });

describe('the generator', () => {
    it('rolls the same look for the same seed, and another for another', () => {
        expect(generate('agt_7Q', ['headset'], 'sky')).toEqual(generate('agt_7Q', ['headset'], 'sky'));
        expect(draw(generate('agt_7Q', ['headset'], 'sky'), 'working', 48)).toBe(draw(generate('agt_7Q', ['headset'], 'sky'), 'working', 48));
        const looks = new Set(Array.from({ length: 40 }, (_, i) => draw(generate(`agt_${i}`, [], 'sky'), 'waiting', 48)));
        expect(looks.size).toBe(40);
    });

    it('keeps the head and face a seed rolls whatever props it wears, so a surface that knows no role draws the same agent', () => {
        const head = ({ body, scale, tilt, fdx, gap, rest, hw, hh, eye, oval, mw, fdy, ear, flip }: MascotLook) => ({ body, scale, tilt, fdx, gap, rest, hw, hh, eye, oval, mw, fdy, ear, flip });
        for (const seed of ['agt_a', 'agt_b', 'wf_1:node_2']) {
            expect(head(generate(seed, ['headset', 'calendar']))).toEqual(head(generate(seed, [])));
            expect(head(generate(seed, ['chefhat']))).toEqual(head(generate(seed, [])));
        }
    });

    it('wears the hue it is given, and at most two props', () => {
        expect(generate('agt_x', [], 'teal').hue).toBe('teal');
        expect(generate('agt_x', ['headset', 'calendar', 'mug']).props).toEqual(['headset', 'calendar']);
    });
});

describe('a role’s props', () => {
    it('are the ones its words name, in the order it names them', () => {
        expect(propsFor('Support inbox')).toEqual(['headset', 'envelope']);
        expect(propsFor('Email support')).toEqual(['envelope', 'headset']);
        expect(propsFor('Weekly digest')).toEqual(['newshat']);
        expect(propsFor('answers Shopify refund emails')).toEqual(['bag', 'envelope']);
        expect(propsFor('Code reviewer')).toEqual(['code']);
        expect(propsFor('Ski guide')).toEqual(['beanie']);
    });

    it('never hold two in one slot, nor more than two', () => {
        // A newspaper hat and a chef's hat both go on the head.
        expect(propsFor('Newsletter of recipes')).toEqual(['newshat']);
        expect(propsFor('Support emails, charts and code')).toEqual(['headset', 'envelope']);
    });

    it('are none for a role that names no job the kit dresses', () => {
        expect(propsFor('Ledger')).toEqual([]);
        expect(propsFor('')).toEqual([]);
        expect(propsFor(null)).toEqual([]);
    });
});

describe('each size', () => {
    const look = generate('agt_sizes', [], 'violet');
    const props: PropKey[] = ['headset', 'calendar'];

    it('names its level of detail: 20px and under, 24 to 32px, 40px and up', () => {
        expect([16, 20, 24, 28, 32, 40, 48, 80].map(tierOf)).toEqual(['xs', 'xs', 'sm', 'sm', 'sm', 'lg', 'lg', 'lg']);
    });

    it('at 20px and under is the head and two eyes: no props, mouth, extra or mark', () => {
        for (const size of [16, 20])
            for (const state of STATE_KEYS) {
                expect(draw(wearing(look, props), state, size)).toBe(draw(wearing(look, []), state, size));
                expect(draw(look, state, size)).not.toMatch(/m-ticks|m-z|m-spk|m-rd/);
            }
        // No extra either: a bow tie drops out.
        expect(draw({ ...look, acc: 'bowtie' }, 'waiting', 20)).toBe(draw({ ...look, acc: 'none' }, 'waiting', 20));
    });

    it('at 24 to 32px keeps what the head wears and the state’s mark, and drops what it holds or floats', () => {
        for (const size of [24, 28, 32]) {
            expect(draw(wearing(look, props), 'waiting', size)).toBe(draw(wearing(look, ['headset']), 'waiting', size));
            expect(draw(wearing(look, ['headset']), 'waiting', size)).not.toBe(draw(wearing(look, []), 'waiting', size));
            expect(draw(look, 'working', size)).toContain('m-ticks');
            // Where a ring round it already says the state, it goes without.
            expect(draw(look, 'working', size, { marks: false })).not.toContain('m-ticks');
        }
    });

    it('at 40px and up draws every prop and its details', () => {
        expect(draw(wearing(look, props), 'waiting', 40)).not.toBe(draw(wearing(look, ['headset']), 'waiting', 40));
        // The calendar's day dots are a detail.
        expect(draw(wearing(look, ['calendar']), 'waiting', 40)).toContain('r="1.3"');
    });

    it('draws every prop in every state without an error', () => {
        for (const k of PROP_KEYS)
            for (const state of STATE_KEYS) for (const size of [16, 24, 40, 80]) expect(draw(wearing(look, [k]), state, size)).toMatch(/^<svg [^>]*>.*<\/svg>$/);
        expect(Object.keys(PROPS)).toHaveLength(26);
    });
});

describe('the markup', () => {
    it('carries nothing of the agent but numbers and the kit’s own parts', () => {
        const seed = '"><script>alert(1)</script>';
        const name = 'Inbox <img src=x onerror=alert(1)> helper';
        for (const state of STATE_KEYS) {
            const svg = draw(generate(seed, propsFor(name), 'pink'), state, 48);
            expect(svg).not.toMatch(/script|alert|onerror|img|Inbox|helper/);
        }
    });
});
