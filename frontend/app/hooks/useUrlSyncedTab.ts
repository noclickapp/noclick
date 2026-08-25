/**
 * Hook for managing tab/section state that syncs with URL params.
 * Solves the common race condition between async URL updates and React state.
 *
 * Key features:
 * - Optimistic state updates (immediate, no flicker)
 * - URL sync in background (for persistence across refreshes)
 * - One-time initialization from URL (prevents re-sync on navigation)
 * - Optional waitFor condition for async dependencies (e.g., org context loading)
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams } from 'react-router';

interface UseUrlSyncedTabOptions<T extends string> {
  /** The URL param name (e.g., 'section', 'orgTab') */
  param: string;
  /** Default value when no URL param or initial value is present */
  defaultValue: T;
  /** Optional list of valid values for validation */
  validValues?: readonly T[];
  /** Initial value from props/parent - takes precedence over URL for immediate render */
  initial?: T;
  /**
   * Condition that must be true before initializing from URL.
   * Useful when URL value depends on async data (e.g., org context).
   * Defaults to true (initialize immediately).
   */
  waitFor?: boolean;
  /**
   * Additional URL params to set on every update.
   * Example: { tab: 'settings' } ensures tab=settings is always set.
   */
  extraParams?: Record<string, string>;
  /**
   * URL params to clear when value changes to a specific value.
   * Example: { usage: ['orgTab'] } clears orgTab when switching to usage.
   */
  clearParamsOn?: Record<string, string[]>;
}

export function useUrlSyncedTab<T extends string>(
  options: UseUrlSyncedTabOptions<T>
): [T, (value: T) => void] {
  const {
    param,
    defaultValue,
    validValues,
    initial,
    waitFor = true,
    extraParams = {},
    clearParamsOn = {},
  } = options;

  const [searchParams, setSearchParams] = useSearchParams();
  const hasInitializedRef = useRef(false);
  const prevInitialRef = useRef(initial);

  // Validate if a value is acceptable
  const isValid = useCallback((v: string | null): v is T => {
    if (!v) return false;
    return !validValues || validValues.includes(v as T);
  }, [validValues]);

  // Get current URL value
  const urlValue = searchParams.get(param);

  // Determine initial state: prefer initial prop, then URL, then default
  const getInitialState = (): T => {
    if (initial !== undefined) return initial;
    if (isValid(urlValue)) return urlValue;
    return defaultValue;
  };

  const [value, setValue] = useState<T>(getInitialState);

  // One-time initialization from URL when waitFor condition is met
  // This handles race conditions with async data (e.g., org context loading)
  useEffect(() => {
    if (hasInitializedRef.current) return;
    if (!waitFor) return;

    hasInitializedRef.current = true;

    // Only sync from URL if we didn't have an initial prop value
    // (initial prop represents optimistic state from parent)
    if (initial === undefined && isValid(urlValue) && urlValue !== value) {
      setValue(urlValue);
    }
  }, [waitFor, urlValue, initial, value, isValid]);

  // Handle initial prop changes after mount
  // This allows parent components to drive the state optimistically
  useEffect(() => {
    if (initial !== undefined && initial !== prevInitialRef.current) {
      setValue(initial);
      prevInitialRef.current = initial;
    }
  }, [initial]);

  // Update value with URL sync
  const setValueWithSync = useCallback((newValue: T) => {
    // Optimistic state update first (immediate, no flicker)
    setValue(newValue);

    // URL sync in background (for persistence)
    setSearchParams(prev => {
      const newParams = new URLSearchParams(prev);
      newParams.set(param, newValue);

      // Set additional params
      Object.entries(extraParams).forEach(([key, val]) => {
        newParams.set(key, val);
      });

      // Clear specified params for this value
      const paramsToClear = clearParamsOn[newValue];
      if (paramsToClear) {
        paramsToClear.forEach(key => newParams.delete(key));
      }

      return newParams;
    }, { replace: true });
  }, [param, extraParams, clearParamsOn, setSearchParams]);

  return [value, setValueWithSync];
}
