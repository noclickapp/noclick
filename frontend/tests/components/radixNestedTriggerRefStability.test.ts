// @vitest-environment happy-dom
//
// Regression test for the canvas React #185 ("Maximum update depth exceeded")
// loop driven by NESTING two Radix asChild triggers onto one element — the
// CanvasTopBar MoreMenu shape (and the WorkflowCheckpointControl + FlowCanvas
// invite-button variants). Runs in CI (vitest + jsdom), no live session.
// Companion to radixSlotRefStability.test.ts, which only covers the SINGLE-slot
// regression (react-slot <= 1.2.4) — that one passes on slot 1.3.0. This file
// covers the case slot 1.3.0's useComposedRefs memoization does NOT fix on its
// own: two asChild Popper-anchor triggers composing onto ONE element.
//
//   <Tooltip><TooltipTrigger asChild>      // Tooltip Popper anchor (state-setter ref)
//     <DropdownMenuTrigger asChild>         // composes its ref INLINE every render
//       <Button .../>                       // ONE element, TWO composed-onto refs
//     </DropdownMenuTrigger>
//   </TooltipTrigger>...</Tooltip>
//
// MECHANISM (verified against the installed dist, not theory):
//   @radix-ui/react-dropdown-menu@2.1.16 DropdownMenuTrigger builds its ref with a
//   non-memoized `ref: composeRefs(forwardedRef, context.triggerRef)` on every
//   render, so the element it slots onto gets a NEW callback-ref identity each
//   commit. React 19 detaches (ref(null)) + re-attaches (ref(node)) it every
//   re-render. In isolation that churn is benign (PopperAnchor gates its effect on
//   an actual node change). The LOOP closes only in the double-asChild stack,
//   where that SAME churning element is ALSO the Tooltip's Popper anchor: the
//   Tooltip's setAnchor state-setter is wired to a ref that flips identity every
//   render, so external canvas re-renders push a transient null through it ->
//   setAnchor -> render -> ... -> React #185 (~40 nested commits in the probe).
//   react-slot 1.3.0 does NOT save this: the outer Tooltip Slot's memo dep is the
//   inner DropdownMenuTrigger element's `.ref`, which itself churns.
//
// THE FIX (applied to all three sites): give each trigger its OWN element — a
// stable inline-flex wrapper is the Tooltip trigger's single asChild child,
// wrapping the inner trigger + Button. The Tooltip's anchor state-setter then
// composes onto the stable wrapper (which nothing else churns); the inner trigger
// still churns its own button ref but is no longer wired to a Popper state-setter,
// so it is inert.
//
// CORRECT SIGNAL: measure the ref of the element the OUTER (Tooltip) trigger
// composes onto — the loop-bearing element. In the bug that is the dropdown-
// churned Button; in the fix it is the stable wrapper span. (Measuring the inner
// button in the fixed shape would still see churn and give a false RED.) Both
// blocks render the REAL Radix Tooltip + DropdownMenu primitives; the ONLY
// variable between them is the component shape, so the pass/fail split proves the
// fix rather than the assertion.
//
// Radix fixed the mechanism upstream in @radix-ui/react-dropdown-menu 2.1.19, so
// both shapes now hold the Tooltip-anchored ref stable: NESTED_SHAPE guards the
// upstream fix, CANONICAL_FIX the shape the source ships.
import { it, expect, beforeAll } from 'vitest';
import { render } from '@testing-library/react';
import React from 'react';
import * as Tooltip from '@radix-ui/react-tooltip';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';

// jsdom lacks a couple of APIs Radix touches on mount. The unit vitest config
// registers no setupFiles, so polyfill them here. We deliberately do NOT mount the
// Popper anchors open (no open={true}, no Portal/Content) — the churn is in the
// TRIGGER's ref composition, which is exercised by mounting the closed trigger and
// re-rendering. Keeping the surface minimal avoids leaking portal timers into
// sibling suites in the shared jsdom worker.
beforeAll(() => {
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  for (const m of ['hasPointerCapture', 'setPointerCapture', 'releasePointerCapture'] as const) {
    if (!(Element.prototype as unknown as Record<string, unknown>)[m]) {
      (Element.prototype as unknown as Record<string, unknown>)[m] = () => false;
    }
  }
});

const h = React.createElement;
const RERENDERS = 8;

// A stable callback ref: its identity never changes, so on a correctly-composed
// (memoized) slot React attaches it once and never detaches across clean
// re-renders; on a churning composition React detaches + re-attaches it every
// render.
function makeRefCounter() {
  let attaches = 0;
  let detaches = 0;
  const ref = (node: unknown) => {
    if (node) attaches++;
    else detaches++;
  };
  return {
    ref,
    get attaches() {
      return attaches;
    },
    get detaches() {
      return detaches;
    },
  };
}

// Renders once, then RERENDERS clean re-renders, returning the measured-element
// attach/detach counts.
function measure(buildTree: (counter: ReturnType<typeof makeRefCounter>, tick: number) => React.ReactElement) {
  const counter = makeRefCounter();
  const { rerender } = render(buildTree(counter, 0));
  for (let i = 1; i <= RERENDERS; i++) rerender(buildTree(counter, i));
  return counter;
}

// BUGGY shape (the pre-fix MoreMenu): TooltipTrigger asChild > DropdownMenuTrigger
// asChild > button. Both the Tooltip's and the DropdownMenu's anchor refs compose
// onto the SAME button — the measured element carries the loop-driving Tooltip
// anchor AND the dropdown's churning inline composeRefs.
const buggyDoubleAsChild = (counter: ReturnType<typeof makeRefCounter>, tick: number) =>
  h(
    Tooltip.Provider,
    null,
    h(
      DropdownMenu.Root,
      null,
      h(
        Tooltip.Root,
        null,
        h(
          Tooltip.Trigger,
          { asChild: true },
          h(
            DropdownMenu.Trigger,
            { asChild: true },
            h('button', { ref: counter.ref, 'aria-label': 'More options', 'data-tick': tick }, 'x'),
          ),
        ),
      ),
    ),
  );

// FIXED shape (the shipped fix): a stable inline-flex <span> is the Tooltip
// trigger's single asChild child and wraps the DropdownMenuTrigger + button. The
// Tooltip's anchor state-setter composes onto the SPAN (measured); the dropdown
// composes onto the button.
const canonicalWrapperFix = (counter: ReturnType<typeof makeRefCounter>, tick: number) =>
  h(
    Tooltip.Provider,
    null,
    h(
      DropdownMenu.Root,
      null,
      h(
        Tooltip.Root,
        null,
        h(
          Tooltip.Trigger,
          { asChild: true },
          h(
            'span',
            { ref: counter.ref, 'data-tick': tick, style: { display: 'inline-flex' } },
            h(
              DropdownMenu.Trigger,
              { asChild: true },
              h('button', { 'aria-label': 'More options' }, 'x'),
            ),
          ),
        ),
      ),
    ),
  );

it('NESTED_SHAPE: double-asChild (Tooltip>Dropdown>Button) keeps the Tooltip-anchored ref stable since dropdown-menu 2.1.19', () => {
  const counter = measure(buggyDoubleAsChild);

  // Up to @radix-ui/react-dropdown-menu 2.1.16 this shape detached and re-attached
  // the Tooltip-anchored button on every clean re-render (9 detaches over these 8),
  // the per-commit detach that drove the canvas #185 loop. 2.1.19 memoizes the
  // trigger's composed ref ("Fixed infinite re-render loop in React 19 caused by
  // unstable composed ref callback references"), so the same shape is now inert.
  // A Radix release that brings the churn back fails here.
  expect(counter.attaches).toBeGreaterThanOrEqual(1);
  expect(counter.detaches).toBeLessThanOrEqual(1);
});

it('CANONICAL_FIX: wrapper-span between the nested triggers keeps the Tooltip-anchored ref stable across re-renders (no churn -> no #185)', () => {
  const counter = measure(canonicalWrapperFix);

  // With the Tooltip anchored to a stable wrapper span (the fix applied to
  // CanvasTopBar.MoreMenu, WorkflowCheckpointControl, and the FlowCanvas invite
  // button), the anchored element is attached once and never detached across the
  // same clean re-renders.
  expect(counter.attaches).toBeGreaterThanOrEqual(1);
  expect(counter.detaches).toBeLessThanOrEqual(1);

  // On dropdown-menu <= 2.1.16 the nested shape above failed this same assertion
  // with `expected 9 to be less than or equal to 1`; the wrapper kept it stable then
  // and still does.
});
