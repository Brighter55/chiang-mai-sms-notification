import { useState } from "react";

import { Input } from "@/components/ui/input";
import { clampMinutes, MAX_MINUTES, MIN_MINUTES } from "@/hooks/useIntervalSettings";

interface AutoRefreshSettingsProps {
  id: string;
  syncMinutes: number;
  listMinutes: number;
  onSyncChange: (minutes: number) => void;
  onListChange: (minutes: number) => void;
}

/**
 * One interval box.
 *
 * The draft is a string so the field can be emptied and retyped — clamping on
 * every keystroke would turn a backspace into a 1-minute cadence. Committing
 * happens on blur, and an empty or unparseable box reverts to the value already
 * in effect rather than jumping to the floor.
 */
function MinutesField({
  id,
  label,
  value,
  onCommit,
}: {
  id: string;
  label: string;
  value: number;
  onCommit: (minutes: number) => void;
}) {
  const [draft, setDraft] = useState(() => String(value));

  function commit() {
    const trimmed = draft.trim();
    const next = clampMinutes(trimmed === "" ? NaN : Number(trimmed), value);
    setDraft(String(next));
    if (next !== value) onCommit(next);
  }

  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="whitespace-nowrap text-sm text-muted-foreground">
        {label}
      </label>
      <Input
        id={id}
        type="number"
        inputMode="numeric"
        min={MIN_MINUTES}
        max={MAX_MINUTES}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
        }}
        className="h-8 w-16 px-2 text-center"
      />
    </div>
  );
}

export function AutoRefreshSettings({
  id,
  syncMinutes,
  listMinutes,
  onSyncChange,
  onListChange,
}: AutoRefreshSettingsProps) {
  return (
    <div id={id} className="border-b bg-surface-low">
      <div className="container flex max-w-4xl flex-wrap items-center gap-x-6 gap-y-2 py-3">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Auto-refresh
        </span>
        <MinutesField
          id="sync-interval"
          label="Clover sync interval (minutes)"
          value={syncMinutes}
          onCommit={onSyncChange}
        />
        <MinutesField
          id="list-interval"
          label="Order list interval (minutes)"
          value={listMinutes}
          onCommit={onListChange}
        />
        <span className="text-xs text-muted-foreground">
          {MIN_MINUTES}–{MAX_MINUTES} minutes. Saved in this browser.
        </span>
      </div>
    </div>
  );
}
