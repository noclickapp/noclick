// @vitest-environment happy-dom
// Work with no page registered (the open edition, which has no platform API): it says Work isn't available here,
// and shows nothing else.
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import { hasWorkPage, WorkPage } from '~/components/shell/work';

describe('Work without a platform', () => {
    it('says Work is not available here, and nothing else', () => {
        expect(hasWorkPage()).toBe(false);
        render(
            <MemoryRouter initialEntries={['/dashboard?tab=work']}>
                <WorkPage user={{ email: 'dana@example.com' }} />
            </MemoryRouter>
        );
        expect(screen.getByTestId('work-notice').textContent).toContain("Work isn't available here");
        expect(screen.queryByTestId('work-page')).toBeNull();
        expect(screen.queryByRole('textbox')).toBeNull();
    });
});
