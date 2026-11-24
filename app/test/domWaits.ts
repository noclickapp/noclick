// A find or waitFor ends once what it waits for is there; its deadline only bounds a wait for something that never
// comes. Testing Library's default gives up after one second, and a loaded machine (several suites at once) can take
// longer than that, or than five seconds, to load a page's code and draw it after a click. DOM tests wait up to thirty
// seconds instead. The app built on this one runs its tests under the same setting.
if (typeof document !== 'undefined') {
    const { configure } = await import('@testing-library/react');
    configure({ asyncUtilTimeout: 30_000 });
}

export {};
