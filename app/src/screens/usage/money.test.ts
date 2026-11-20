// A whole-dollar estimate reads the same whatever float noise its sum carries: a total a hair either side of $5
// (the order a sum is added in, or the machine adding it) reads "$5", as $5 itself does.
import { expect, it } from 'vitest';
import { roundMoney } from './derive';

it('reads a sum within float noise of whole dollars as whole dollars', () => {
    expect(roundMoney(5)).toBe('$5');
    expect(roundMoney(4.999999999999999)).toBe('$5');
    expect(roundMoney(5.000000000000001)).toBe('$5');
    expect(roundMoney(0.1 + 0.2 + 4.7)).toBe('$5');
});

it('keeps the cents of anything else', () => {
    expect(roundMoney(4.99)).toBe('$4.99');
    expect(roundMoney(5.5)).toBe('$5.50');
    expect(roundMoney(0.5)).toBe('$0.50');
    expect(roundMoney(-4.999999999999999)).toBe('−$5');
    expect(roundMoney(0)).toBe('$0');
});
