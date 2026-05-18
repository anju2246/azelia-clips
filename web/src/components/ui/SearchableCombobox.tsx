import React, { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Search, X } from "lucide-react";

export interface ComboboxItem {
  id: string;
  label: string;
}

interface SearchableComboboxProps {
  items: ComboboxItem[];
  value: string;
  onChange: (id: string) => void;
  placeholder?: string;
  emptyMessage?: string;
  disabled?: boolean;
  className?: string;
  /** Pre-filter text to narrow the list (e.g., only LATAM countries). */
  hint?: string;
}

/**
 * Accessible combobox with type-to-search. Works for large lists (hundreds of
 * items) without overwhelming the user with a giant native <select>.
 *
 * - Click the button → opens a panel with a search input focused
 * - Typing filters by label and id (case-insensitive)
 * - Enter selects the highlighted row; Esc or clicking outside closes
 * - Value stored is the canonical `id` (normalized taxonomy)
 */
export const SearchableCombobox: React.FC<SearchableComboboxProps> = ({
  items,
  value,
  onChange,
  placeholder = "Select an option",
  emptyMessage = "No matches.",
  disabled = false,
  className = "",
  hint,
}) => {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIdx, setActiveIdx] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const selectedItem = useMemo(
    () => items.find((i) => i.id === value),
    [items, value],
  );

  const filtered = useMemo(() => {
    const q = (query || "").trim().toLowerCase();
    const base = hint
      ? items.filter(
          (i) =>
            i.label.toLowerCase().includes(hint.toLowerCase()) ||
            i.id.toLowerCase().includes(hint.toLowerCase()),
        )
      : items;
    if (!q) return base;
    return base.filter(
      (i) =>
        i.label.toLowerCase().includes(q) || i.id.toLowerCase().includes(q),
    );
  }, [items, query, hint]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIdx(0);
      // Focus after the panel is on screen.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node))
        setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, Math.max(filtered.length - 1, 0)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const item = filtered[activeIdx];
      if (item) {
        onChange(item.id);
        setOpen(false);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div ref={wrapRef} className={`relative ${className}`}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className={`w-full flex items-center justify-between bg-black/40 border border-white/10 rounded-xl px-4 py-3 text-left transition-all ${disabled ? "opacity-50 cursor-not-allowed" : "hover:border-white/20 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"}`}
      >
        <span className={selectedItem ? "text-white" : "text-zinc-500"}>
          {selectedItem ? selectedItem.label : placeholder}
        </span>
        <ChevronDown
          className={`w-4 h-4 text-zinc-500 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div className="absolute z-20 mt-2 w-full rounded-xl border border-white/10 bg-zinc-950/95 backdrop-blur-md shadow-2xl overflow-hidden">
          <div className="relative p-2 border-b border-white/5">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setActiveIdx(0);
              }}
              onKeyDown={handleKey}
              placeholder="Search…"
              className="w-full bg-black/40 border border-white/5 rounded-lg pl-9 pr-8 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-brand-500"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                className="absolute right-4 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
                aria-label="Clear search"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
          <div className="max-h-64 overflow-y-auto py-1" role="listbox">
            {filtered.length === 0 ? (
              <div className="px-4 py-3 text-sm text-zinc-500">
                {emptyMessage}
              </div>
            ) : (
              filtered.map((item, idx) => {
                const isSelected = item.id === value;
                const isActive = idx === activeIdx;
                return (
                  <button
                    key={item.id}
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    onMouseEnter={() => setActiveIdx(idx)}
                    onClick={() => {
                      onChange(item.id);
                      setOpen(false);
                    }}
                    className={`w-full flex items-center justify-between px-4 py-2 text-sm text-left transition-colors ${isActive ? "bg-brand-500/10 text-white" : "text-zinc-300 hover:bg-white/5"}`}
                  >
                    <span>{item.label}</span>
                    {isSelected && <Check className="w-4 h-4 text-brand-400" />}
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
};
