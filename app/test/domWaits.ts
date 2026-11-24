// A find or waitFor gives up after one second by default, and a loaded machine can take longer than that to send a
// request or render after a click. DOM tests wait up to five seconds instead. The app built on this one runs its tests
// under the same setting.
if (typeof document !== 'undefined') {
    const { configure } = await import('@testing-library/react');
    configure({ asyncUtilTimeout: 5000 });
}

export {};
