// @vitest-environment jsdom
//
// Pins the single-dollar math regression: chat prose is full of literal `$`
// ("A$AP Rocky", prices), and remark-math's default singleDollarTextMath
// turned everything between two dollars into KaTeX — serif italics, stripped
// spaces, literal ∗ for ** (2026-07-19). Explicit $$…$$ math must still render.

import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import { MarkdownRenderer } from '~/components/chat/MarkdownRenderer';

afterEach(cleanup);

describe('MarkdownRenderer math handling', () => {
  it('leaves single-dollar text literal (A$AP Rocky stays prose)', () => {
    const { container } = render(
      <MarkdownRenderer content={'**Song:** "Big Dawgs" — A$AP Rocky **(2024)**. Also under A$AP Ferg.'} />,
    );
    expect(container.querySelector('.katex')).toBeNull();
    expect(container.textContent).toContain('A$AP Rocky');
    expect(container.textContent).toContain('A$AP Ferg');
    // The bold between the dollars survives as real <strong>, not math ∗.
    const bolds = Array.from(container.querySelectorAll('strong')).map(el => el.textContent);
    expect(bolds).toContain('(2024)');
  });

  it('still renders explicit double-dollar math via KaTeX', () => {
    const { container } = render(<MarkdownRenderer content={'inline $$x^2 + y^2$$ math'} />);
    expect(container.querySelector('.katex')).not.toBeNull();
  });
});
