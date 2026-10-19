// @vitest-environment jsdom
// A turn's web searches share one Sources list under the reply: each page once, the pages the reply links to first,
// folded to one line until it's opened.
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { TurnCards } from '~/components/coordinator/toolCards';
import type { CoordinatorToolCall } from '~/lib/coordinatorToolCalls';

afterEach(cleanup);

const search = (id: string, results: { title: string; url: string }[], running = false): CoordinatorToolCall => ({
    id,
    tool: 'web_search',
    args: { query: id },
    result: running ? undefined : { success: true, results },
    running,
    startedAt: 0,
});

const titles = () => within(screen.getByTestId('coordinator-sources')).getAllByRole('link').map((a) => a.textContent);

it('lists every search of a turn once, deduplicated, behind one folded row', () => {
    render(
        <TurnCards
            calls={[
                search('http', [
                    { title: 'HTTP', url: 'https://en.wikipedia.org/wiki/HTTP' },
                    { title: 'Overview of HTTP', url: 'https://developer.mozilla.org/en-US/docs/Web/HTTP/Overview' },
                ]),
                search('http again', [
                    { title: 'HTTP', url: 'https://en.wikipedia.org/wiki/HTTP/' },
                    { title: 'RFC 9110', url: 'https://www.rfc-editor.org/rfc/rfc9110' },
                ]),
            ]}
        />
    );
    expect(screen.getAllByTestId('coordinator-sources')).toHaveLength(1);
    const toggle = screen.getByRole('button', { name: /3 sources/ });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryAllByRole('link')).toHaveLength(0);

    fireEvent.click(toggle);
    expect(titles()).toEqual(['HTTPen.wikipedia.org', 'Overview of HTTPdeveloper.mozilla.org', 'RFC 9110rfc-editor.org']);
});

it('puts the pages the reply links to first', () => {
    render(
        <TurnCards
            text="Per [the RFC](https://rfc-editor.org/rfc/rfc9110)."
            calls={[
                search('http', [
                    { title: 'HTTP', url: 'https://en.wikipedia.org/wiki/HTTP' },
                    { title: 'RFC 9110', url: 'https://www.rfc-editor.org/rfc/rfc9110' },
                ]),
            ]}
        />
    );
    fireEvent.click(screen.getByRole('button', { name: /2 sources/ }));
    expect(titles()[0]).toBe('RFC 9110rfc-editor.org');
});

it('names a page by its path when its title only repeats the site', () => {
    render(<TurnCards calls={[search('mcp', [{ title: 'code.claude.com', url: 'https://code.claude.com/docs/en/mcp' }])]} />);
    fireEvent.click(screen.getByRole('button', { name: /1 source/ }));
    expect(titles()).toEqual(['docs / en / mcpcode.claude.com']);
});

it('draws nothing for a search still running or one that found nothing', () => {
    render(<TurnCards calls={[search('a', [], false), search('b', [{ title: 'B', url: 'https://b.example' }], true)]} />);
    expect(screen.queryByTestId('coordinator-sources')).toBeNull();
});
