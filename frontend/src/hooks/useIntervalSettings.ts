import { useCallback, useEffect, useState } from "react";

/**
 * The dashboard's auto-refresh intervals, persisted per browser.
 *
 * This is the first localStorage use in the app, so every access is guarded:
 * storage throws outright in some private-browsing and blocked-cookie setups,
 * and a preference that cannot be read must never be the reason the dashboard
 * fails to render.
 *
 * Per browser rather than per account is deliberate — it lets a slow tablet
 * run a gentler cadence than the counter terminal, and it keeps this change out
 * of the backend entirely.
 */

export const MIN_MINUTES = 1;
export const MAX_MINUTES = 60;
export const DEFAULT_SYNC_MINUTES = 10;
export const DEFAULT_LIST_MINUTES = 10;

const STORAGE_KEY = "chiang-mai:auto-refresh";

/**
 * Round to whole minutes and hold inside the allowed range. Non-numeric input
 * (a blank box, garbage) falls back to the value already in effect, so a
 * half-typed edit cannot silently become 1 minute.
 *
 * The floor is not cosmetic: it is what bounds how often a left-open dashboard
 * can ask Clover for orders.
 */
export function clampMinutes(value: number, fallback: number): number {
  if (!Number.isFinite(value)) return fallback;
  return Math.min(MAX_MINUTES, Math.max(MIN_MINUTES, Math.round(value)));
}

interface IntervalSettings {
  syncMinutes: number;
  listMinutes: number;
}

const DEFAULTS: IntervalSettings = {
  syncMinutes: DEFAULT_SYNC_MINUTES,
  listMinutes: DEFAULT_LIST_MINUTES,
};

function readSettings(): IntervalSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULTS;
    const parsed = JSON.parse(raw) as Partial<IntervalSettings> | null;
    return {
      syncMinutes: clampMinutes(
        Number(parsed?.syncMinutes),
        DEFAULT_SYNC_MINUTES
      ),
      listMinutes: clampMinutes(
        Number(parsed?.listMinutes),
        DEFAULT_LIST_MINUTES
      ),
    };
  } catch {
    // Unreadable storage or malformed JSON. Either way the defaults are a
    // perfectly good dashboard.
    return DEFAULTS;
  }
}

export function useIntervalSettings(): IntervalSettings & {
  setSyncMinutes: (minutes: number) => void;
  setListMinutes: (minutes: number) => void;
} {
  const [settings, setSettings] = useState<IntervalSettings>(readSettings);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch {
      // Best effort. The dashboard works for this session regardless.
    }
  }, [settings]);

  const setSyncMinutes = useCallback((minutes: number) => {
    setSettings((prev) => ({
      ...prev,
      syncMinutes: clampMinutes(minutes, prev.syncMinutes),
    }));
  }, []);

  const setListMinutes = useCallback((minutes: number) => {
    setSettings((prev) => ({
      ...prev,
      listMinutes: clampMinutes(minutes, prev.listMinutes),
    }));
  }, []);

  return { ...settings, setSyncMinutes, setListMinutes };
}
