"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { AtSign, MessageSquare, Send } from "lucide-react";
import { activeMentionQuery, insertMention } from "@/features/chat/chat-sessions";
import type { ChatSession, SessionMention } from "@/lib/types";
import { cn } from "@/lib/utils";

const MAX_SUGGESTIONS = 6;

/**
 * Message input: Enter sends, Shift+Enter inserts a newline, and typing `@` offers other
 * chat sessions to reference. Selected mentions are tracked by id alongside the text.
 */
export function ChatComposer({ value, onChange, mentions, onMentionsChange, candidates, disabled, busy, onSubmit, placeholder, active = true }: {
  value: string;
  onChange: (value: string) => void;
  mentions: SessionMention[];
  onMentionsChange: (mentions: SessionMention[]) => void;
  candidates: ChatSession[];
  disabled?: boolean;
  /** True while an answer is pending; Enter and Send are ignored. */
  busy?: boolean;
  /** Receives the live textarea text and mentions, which can be newer than the last render. */
  onSubmit: (text: string, mentions: SessionMention[]) => void;
  placeholder?: string;
  active?: boolean;
}) {
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const focusFrame = useRef<number | null>(null);
  useEffect(() => () => { if (focusFrame.current !== null) window.cancelAnimationFrame(focusFrame.current); }, [active]);
  const [mention, setMention] = useState<{ start: number; query: string } | null>(null);
  const [highlight, setHighlight] = useState(0);
  // Start index of an `@` the user dismissed with Escape, so Enter sends instead of picking.
  const [dismissed, setDismissed] = useState<number | null>(null);
  const latestMentions = useRef(mentions);
  useEffect(() => { latestMentions.current = mentions; }, [mentions]);

  const matching = useCallback((query: string) => {
    const needle = query.toLowerCase();
    return candidates.filter((session) => session.title.toLowerCase().includes(needle)).slice(0, MAX_SUGGESTIONS);
  }, [candidates]);
  const suggestions = useMemo(() => (mention ? matching(mention.query) : []), [matching, mention]);
  const pickerOpen = Boolean(mention) && mention?.start !== dismissed && suggestions.length > 0;

  function syncMention(text: string, caret: number) {
    const next = activeMentionQuery(text, caret);
    setMention(next);
    setHighlight(0);
    if (!next || next.start !== dismissed) setDismissed(null);
  }

  function choose(session: ChatSession, at?: { start: number; caret: number }) {
    const el = inputRef.current;
    const target = at ?? (mention && el ? { start: mention.start, caret: el.selectionStart ?? el.value.length } : null);
    if (!target || !el) return;
    const next = insertMention(el.value, target.start, target.caret, session.title);
    // Update the DOM immediately so an Enter pressed before the next render sees the mention.
    el.value = next.text;
    el.setSelectionRange(next.caret, next.caret);
    onChange(next.text);
    if (!latestMentions.current.some((item) => item.id === session.id)) {
      latestMentions.current = [...latestMentions.current, { id: session.id, title: session.title }];
      onMentionsChange(latestMentions.current);
    }
    setMention(null);
    if (active) focusFrame.current = window.requestAnimationFrame(() => { el.focus(); el.setSelectionRange(next.caret, next.caret); });
  }

  function submitLive() {
    const text = inputRef.current?.value ?? value;
    if (active && !busy && !disabled && text.trim()) onSubmit(text, latestMentions.current);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (!active) return;
    // Read the DOM directly: key events can arrive before React re-renders the latest keystrokes.
    const el = event.currentTarget;
    const caret = el.selectionStart ?? el.value.length;
    const live = activeMentionQuery(el.value, caret);
    const liveSuggestions = live ? matching(live.query) : [];
    if (live && live.start !== dismissed && liveSuggestions.length) {
      const index = Math.min(highlight, liveSuggestions.length - 1);
      if (event.key === "ArrowDown") { event.preventDefault(); setHighlight((index + 1) % liveSuggestions.length); return; }
      if (event.key === "ArrowUp") { event.preventDefault(); setHighlight((index - 1 + liveSuggestions.length) % liveSuggestions.length); return; }
      if ((event.key === "Enter" && !event.shiftKey) || event.key === "Tab") { event.preventDefault(); choose(liveSuggestions[index], { start: live.start, caret }); return; }
      if (event.key === "Escape") { event.preventDefault(); setDismissed(live.start); setMention(null); return; }
    }
    // IME composition uses Enter to confirm characters; never send mid-composition.
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submitLive();
    }
  }

  function insertAt() {
    const el = inputRef.current;
    if (!el) return;
    const current = el.value;
    const caret = el.selectionStart ?? current.length;
    const needsSpace = caret > 0 && !/\s/.test(current[caret - 1]);
    const text = `${current.slice(0, caret)}${needsSpace ? " " : ""}@${current.slice(caret)}`;
    const nextCaret = caret + (needsSpace ? 2 : 1);
    onChange(text);
    syncMention(text, nextCaret);
    if (active) focusFrame.current = window.requestAnimationFrame(() => { el.focus(); el.setSelectionRange(nextCaret, nextCaret); });
  }

  return <form onSubmit={(event: FormEvent) => { event.preventDefault(); submitLive(); }} className="relative">
    {active && pickerOpen ? <ul role="listbox" aria-label="Mention a chat" className="absolute bottom-full left-0 z-20 mb-2 w-full max-w-md overflow-hidden rounded-2xl border border-line bg-paper p-1 shadow-soft">
      <li className="px-3 py-1 text-[11px] font-semibold uppercase tracking-widest text-muted">Reference a chat</li>
      {suggestions.map((session, index) => <li key={session.id} role="option" aria-selected={index === highlight}>
        <button type="button" className={cn("flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm", index === highlight ? "bg-indigo-soft text-indigo-deep" : "hover:bg-linen")}
          onMouseDown={(event) => { event.preventDefault(); choose(session); }} onMouseEnter={() => setHighlight(index)}>
          <MessageSquare className="h-4 w-4 shrink-0" /><span className="truncate">{session.title}</span>{session.archived ? <span className="ml-auto text-[11px] text-muted">archived</span> : null}
        </button>
      </li>)}
    </ul> : null}
    <div className="flex gap-3">
      <label className="sr-only" htmlFor="question">Research question</label>
      <textarea ref={inputRef} id="question" className="input min-h-16 resize-y" value={value} disabled={disabled} placeholder={placeholder}
        aria-describedby="composer-hint" aria-autocomplete="list"
        onChange={(event) => { onChange(event.target.value); syncMention(event.target.value, event.target.selectionStart ?? event.target.value.length); }}
        onSelect={(event) => syncMention(event.currentTarget.value, event.currentTarget.selectionStart ?? 0)}
        onBlur={() => setMention(null)}
        onKeyDown={onKeyDown} />
      <div className="flex flex-col justify-end gap-2">
        <button type="button" className="btn h-10 w-10 p-0" onClick={insertAt} disabled={disabled || candidates.length === 0} aria-label="Mention another chat" title="Mention another chat"><AtSign className="h-4 w-4" /></button>
        <button className="btn btn-primary" disabled={disabled || busy || !value.trim()}><Send className="h-4 w-4" />Send</button>
      </div>
    </div>
    <p id="composer-hint" className="mt-2 text-xs text-muted">Enter to send · Shift+Enter for a new line · @ to reference another chat</p>
  </form>;
}
