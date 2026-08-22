// @vitest-environment jsdom
//
// Regression test for the canvas-tab React #185 ("Maximum update depth exceeded")
// loop — radix-ui/primitives #3799. Runs in CI (vitest + jsdom), no live session.
//
// ROOT CAUSE: @radix-ui/react-slot <= 1.2.4 composes the asChild child ref
// INLINE on every render — `props.ref = composeRefs(forwardedRef, childrenRef)` —
// producing a NEW callback-ref identity each render. Under React 19's ref
// semantics, a changed callback-ref identity forces React to detach the old ref
// (call it with null) and attach the new one on EVERY re-render. In the real
// app the composed ref includes a Popper state-setter (setAnchor) and an
// asChild Tooltip trigger, so that per-commit detach calls setState → re-render
// → new ref identity → ... → #185. Fixed in react-slot >= 1.2.5 (radix-ui/primitives#3899) by
// memoizing with useComposedRefs (stable identity).
//
// This test isolates the FIX VARIABLE (ref-identity stability) rather than the
// #185 symptom — an unguarded-useEffect driver throws #185 on its own,
// independent of Radix (see tests/nc/react185-control), so a raw #185 repro
// can't verify the fix. A STABLE child ref must be attached once and never
// detached across clean re-renders; the buggy slot detaches + re-attaches it
// every render.
import { it, expect } from 'vitest';
import { render } from '@testing-library/react';
import React from 'react';
import { Slot } from '@radix-ui/react-slot';

// Mirrors how Radix Tooltip/Popover wire an asChild trigger: a forwardRef parent
// hands the slot a forwardedRef, so the slot takes the inline-composeRefs path.
const Forwarder = React.forwardRef<HTMLButtonElement, { children: React.ReactNode }>(
  function Forwarder(props, ref) {
    return React.createElement(Slot, { ref, children: props.children });
  },
);

it('react-slot keeps an asChild child ref stable across re-renders (radix #3799 / canvas #185 cause)', () => {
  let attaches = 0;
  let detaches = 0;
  const childRef = (node: unknown) => { if (node) attaches++; else detaches++; };
  const forwarded = React.createRef<HTMLButtonElement>();

  const tree = (tick: number) => {
    const child = React.createElement(
      'button',
      { ref: childRef, 'data-tick': tick },
      'tab',
    );
    return React.createElement(Forwarder, {
      ref: forwarded,
      children: child,
    });
  };

  const { rerender } = render(tree(0));
  for (let i = 1; i <= 6; i++) rerender(tree(i));

  // The child ref is stable (same identity every render). On a fixed slot React
  // attaches it once and never detaches on these 6 clean re-renders. On the
  // buggy slot (<=1.2.4) the inline composeRefs gives a new composed-ref identity
  // each render, so React detaches + re-attaches the child ref every time.
  expect(attaches).toBeGreaterThanOrEqual(1);
  expect(detaches).toBeLessThanOrEqual(1);
});
