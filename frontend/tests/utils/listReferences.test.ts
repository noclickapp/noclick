import { describe, it, expect } from 'vitest';
import {
  hasListReference,
  parseListReference,
  buildItemsReference,
  rewriteListRefsForIteration,
  getValueAtPath,
  clipSampleItem,
} from '~/lib/listReferences';

describe('clipSampleItem', () => {
  it('keeps top-level keys, truncates long strings, summarizes nested', () => {
    const item = {
      firstName: 'Alex',
      about: 'x'.repeat(200),
      courses: [{ a: 1 }, { a: 2 }],
      address: { city: 'SF', zip: '94000' },
      count: 1464,
    };
    const clipped = clipSampleItem(item) as Record<string, unknown>;
    expect(Object.keys(clipped)).toEqual(['firstName', 'about', 'courses', 'address', 'count']);
    expect(clipped.firstName).toBe('Alex');
    expect((clipped.about as string).length).toBeLessThanOrEqual(81);
    expect(clipped.courses).toBe('[2 items]');
    expect(clipped.address).toBe('{2 fields}');
    expect(clipped.count).toBe(1464);
  });
  it('passes through primitives', () => {
    expect(clipSampleItem('hi')).toBe('hi');
    expect(clipSampleItem(5)).toBe(5);
  });
});

describe('getValueAtPath', () => {
  const out = { data: { items: [{ firstName: 'A' }, { firstName: 'B' }] }, results: [{ rows: [1, 2] }] };
  it('reads a nested dotted path', () => {
    expect(getValueAtPath(out, 'data.items')).toEqual([{ firstName: 'A' }, { firstName: 'B' }]);
  });
  it('reads through [n] indices', () => {
    expect(getValueAtPath(out, 'results[0].rows')).toEqual([1, 2]);
  });
  it('empty path returns the object itself', () => {
    expect(getValueAtPath(out, '')).toBe(out);
  });
  it('returns undefined for missing segments', () => {
    expect(getValueAtPath(out, 'data.missing')).toBeUndefined();
    expect(getValueAtPath(null, 'a.b')).toBeUndefined();
  });
});

describe('listReferences', () => {
  describe('hasListReference', () => {
    it('detects a [] reference', () => {
      expect(hasListReference('{{youtube_1.items[].snippet.title}}')).toBe(true);
      expect(hasListReference('hi {{a.b[].c}} there')).toBe(true);
    });
    it('is false for plain refs / non-strings', () => {
      expect(hasListReference('{{youtube_1.items}}')).toBe(false);
      expect(hasListReference('{{a.b[0].c}}')).toBe(false);
      expect(hasListReference('no refs')).toBe(false);
      expect(hasListReference(42 as unknown)).toBe(false);
    });
  });

  describe('parseListReference', () => {
    it('parses nodeId + nested array path + remainder', () => {
      expect(parseListReference('{{youtube_1.items[].snippet.title}}')).toEqual({
        raw: '{{youtube_1.items[].snippet.title}}',
        nodeId: 'youtube_1',
        arrayPath: 'items',
        remainder: 'snippet.title',
      });
      expect(parseListReference('{{src.data.records[].name}}')).toMatchObject({
        nodeId: 'src',
        arrayPath: 'data.records',
        remainder: 'name',
      });
    });
    it('handles a node whose output IS the array (no array path)', () => {
      expect(parseListReference('{{src[].name}}')).toMatchObject({
        nodeId: 'src',
        arrayPath: '',
        remainder: 'name',
      });
    });
    it('handles a bare [] (whole item)', () => {
      expect(parseListReference('{{src.items[]}}')).toMatchObject({
        nodeId: 'src',
        arrayPath: 'items',
        remainder: '',
      });
    });
    it('returns null when there is no list ref', () => {
      expect(parseListReference('{{src.items}}')).toBeNull();
      expect(parseListReference('plain text')).toBeNull();
    });
  });

  describe('buildItemsReference', () => {
    it('builds the iteration items ref from a parsed list ref', () => {
      expect(buildItemsReference(parseListReference('{{youtube_1.items[].snippet.title}}')!)).toBe(
        '{{youtube_1.items}}',
      );
      expect(buildItemsReference(parseListReference('{{src[].name}}')!)).toBe('{{src}}');
    });
  });

  describe('rewriteListRefsForIteration', () => {
    it('rewrites same-source refs to the per-item form', () => {
      expect(
        rewriteListRefsForIteration('{{youtube_1.items[].snippet.title}}', 'youtube_1', 'items', 'iteration_x'),
      ).toBe('{{iteration_x.item.snippet.title}}');
    });
    it('rewrites a bare [] to {{iter.item}}', () => {
      expect(rewriteListRefsForIteration('{{src.items[]}}', 'src', 'items', 'it1')).toBe('{{it1.item}}');
    });
    it('rewrites multiple same-source refs in one string', () => {
      expect(
        rewriteListRefsForIteration('{{s.rows[].a}} and {{s.rows[].b}}', 's', 'rows', 'it1'),
      ).toBe('{{it1.item.a}} and {{it1.item.b}}');
    });
    it('leaves references to a different source untouched', () => {
      const v = '{{s.rows[].a}} {{other.list[].x}} {{s.cols[].y}}';
      expect(rewriteListRefsForIteration(v, 's', 'rows', 'it1')).toBe(
        '{{it1.item.a}} {{other.list[].x}} {{s.cols[].y}}',
      );
    });
  });
});
