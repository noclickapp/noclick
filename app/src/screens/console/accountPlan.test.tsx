// @vitest-environment happy-dom
// The console names the plan the account is on, as `GET /v1/status` names it, at the sidebar's foot and on Settings.
// `/v1/account`'s `plan.tier` is the tier stored for the account: on the Free and Member plans, an account that pays
// is a Member whether that tier says Plus, Pro or Member; an account still on an older plan is on that plan.
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useParams } from 'react-router';
import { afterEach, describe, expect, it } from 'vitest';
import { ConsoleProviders } from './ConsoleProviders';
import { DeveloperConsole } from './DeveloperConsole';
import { ConsoleSidebarContent } from './Sidebar';
import { fixtureClient } from './fixtures/client';
import { fixtureConsole } from './fixtures/context';
import { FIXTURE_NOW_MS, FIXTURE_USER, planRoutes, type FixtureRoute } from './fixtures/core';

afterEach(cleanup);

function sidebar(tier: string, plan: string) {
    render(
        <MemoryRouter initialEntries={['/developers']}>
            <ConsoleProviders value={fixtureConsole({ routes: planRoutes(tier, plan) })}>
                <ConsoleSidebarContent active={null} collapsed={false} headerEnd={null} />
            </ConsoleProviders>
        </MemoryRouter>
    );
}

/** The whole console on its Settings page, over the fixtures (the lab's own when `routes` is empty). */
function settings(routes: readonly FixtureRoute[] = []) {
    const client = fixtureClient({ set: 'populated', routes }, { maxRetries: 0 });
    function Mounted() {
        return (
            <DeveloperConsole
                section={useParams()['*']}
                client={client}
                actsAs="owner"
                basePath="/developers"
                apiUrl="https://api.noclick.com"
                site="https://noclick.com"
                home="/"
                user={FIXTURE_USER}
                now={() => FIXTURE_NOW_MS}
                onSignOut={() => undefined}
                live={null}
            />
        );
    }
    render(
        <MemoryRouter initialEntries={['/developers/settings']}>
            <Routes>
                <Route path="/developers/*" element={<Mounted />} />
            </Routes>
        </MemoryRouter>
    );
}

/** Settings' Plan row, once it has read the plan. */
async function planRow() {
    const sentence = await screen.findByText((_, element) => element?.tagName === 'P' && /Signed in as/.test(element.textContent ?? ''));
    return sentence.textContent;
}

describe("the console's account", () => {
    it('reads as a Member for an account on the Member plan whose stored tier is Pro', async () => {
        sidebar('pro', 'member');
        expect(await screen.findByText('Member plan')).toBeTruthy();
        expect(screen.queryByText('Pro plan')).toBeNull();
    });

    it('reads as the older plan for an account still on it', async () => {
        sidebar('pro', 'pro');
        expect(await screen.findByText('Pro plan')).toBeTruthy();
    });

    it('reads as Free for a free account', async () => {
        sidebar('free', 'free');
        expect(await screen.findByText('Free plan')).toBeTruthy();
    });
});

describe("Settings' Plan", () => {
    it('names the plan the account is on, not its stored tier', async () => {
        settings(planRoutes('pro', 'member'));
        expect(await planRow()).toBe(`Member plan. Signed in as ${FIXTURE_USER.email}.`);
    });

    it("reads right over the lab's own fixtures, there and in the sidebar", async () => {
        settings();
        expect(await planRow()).toBe(`Member plan. Signed in as ${FIXTURE_USER.email}.`);
        expect(screen.getByRole('button', { name: /Member plan$/ })).toBeTruthy();
    });
});
