// Unit tests for the @-mention token detector + inserter used by the chat
// composer's file autocomplete.

import { describe, it, expect } from 'vitest';
import { detectMentionToken, applyMention } from '~/utils/mentionToken';

describe('detectMentionToken', () => {
  it('activates for @ at the start of input', () => {
    expect(detectMentionToken('@rep', 4)).toEqual({ start: 0, query: 'rep' });
  });

  it('activates for @ after whitespace', () => {
    const v = 'see @rep';
    expect(detectMentionToken(v, v.length)).toEqual({ start: 4, query: 'rep' });
  });

  it('activates for a bare @ with empty query', () => {
    expect(detectMentionToken('hello @', 7)).toEqual({ start: 6, query: '' });
  });

  it('does NOT activate mid-word (a@b)', () => {
    expect(detectMentionToken('a@b', 3)).toBeNull();
  });

  it('closes once whitespace follows the @', () => {
    expect(detectMentionToken('@rep ', 5)).toBeNull();
  });

  it('uses the @ token the caret is actually inside', () => {
    const v = '@one two @thr';
    expect(detectMentionToken(v, v.length)).toEqual({ start: 9, query: 'thr' });
  });

  it('returns null when there is no @ before the caret', () => {
    expect(detectMentionToken('plain text', 10)).toBeNull();
  });
});

describe('applyMention', () => {
  it('replaces the @query span with the path plus a trailing space', () => {
    const v = 'see @rep';
    const token = detectMentionToken(v, v.length)!;
    const res = applyMention(v, v.length, token, '/workspace/report.md');
    expect(res.value).toBe('see /workspace/report.md ');
    expect(res.caret).toBe(res.value.length);
  });

  it('keeps text after the caret intact', () => {
    const v = '@rep done';
    // caret sits right after "rep" (index 4), before " done"
    const token = detectMentionToken(v, 4)!;
    const res = applyMention(v, 4, token, '/workspace/report.md');
    expect(res.value).toBe('/workspace/report.md  done');
    expect(res.caret).toBe('/workspace/report.md '.length);
  });
});
