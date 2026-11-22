import { describe, expect, it } from 'vitest';
import { getParentPaths } from './ReferenceHoverContext';

describe('getParentPaths', () => {
    it('normalizes every closing bracket in nested array paths', () => {
        expect(getParentPaths('node-1', 'output.items[0][1].name')).toEqual([
            'node-1:output',
            'node-1:output.items',
            'node-1:output.items[0]',
            'node-1:output.items[0][1]',
            'node-1:output.items[0][1].name',
        ]);
    });
});
