// Which pages follow the stored theme: all of them until an app names the ones it built for both themes, then only
// those; and the head script that applies a light preference before first paint tests the same pages.
import { expect, it } from 'vitest';
import { isThemedPath, registerThemedPaths, themedPathSources, themeInitScript } from './theme';

it('themes every page until some are named, then only those', () => {
    expect(themedPathSources()).toEqual([]);
    expect(isThemedPath('/')).toBe(true);
    expect(isThemedPath('/anything/at/all')).toBe(true);
    expect(themeInitScript()).toBe(
        "try{var t=localStorage.getItem('nc-theme');if((t==='light'||(t==='system'&&!matchMedia('(prefers-color-scheme: dark)').matches))){document.documentElement.classList.remove('dark')}}catch(e){}",
    );

    registerThemedPaths(/^\/app(?:\/|$)/);
    registerThemedPaths(/^\/settings$/);
    // Naming one twice changes nothing (a dev server runs the naming module again on each reload).
    registerThemedPaths(/^\/app(?:\/|$)/);
    expect(themedPathSources()).toEqual(['^\\/app(?:\\/|$)', '^\\/settings$']);
    expect(isThemedPath('/app/inbox')).toBe(true);
    expect(isThemedPath('/settings')).toBe(true);
    expect(isThemedPath('/')).toBe(false);
    expect(themeInitScript()).toBe(
        "try{var t=localStorage.getItem('nc-theme');if((t==='light'||(t==='system'&&!matchMedia('(prefers-color-scheme: dark)').matches))&&[\"^\\\\/app(?:\\\\/|$)\",\"^\\\\/settings$\"].some(function(s){return new RegExp(s).test(location.pathname)})){document.documentElement.classList.remove('dark')}}catch(e){}",
    );
});
