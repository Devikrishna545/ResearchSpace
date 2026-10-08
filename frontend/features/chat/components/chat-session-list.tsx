"use client";

import type { ReactNode } from "react";
import { useRef, useState } from "react";
import { Archive, ArchiveRestore, MessageSquarePlus, Pencil, Pin, PinOff, Search, Trash2, X } from "lucide-react";
import type { ChatSession } from "@/lib/types";
import { cn, dateLabel } from "@/lib/utils";
import { RailCard } from "@/components/ui/module-layout";

export type SessionView = "active" | "archived";

export interface SessionActions {
  onSelect: (id: string) => void;
  onNew: () => void;
  onRename: (id: string, title: string) => Promise<void>;
  onTogglePin: (session: ChatSession) => Promise<void>;
  onToggleArchive: (session: ChatSession) => Promise<void>;
  onDelete: (session: ChatSession) => Promise<void>;
}

export function ChatSessionList({ sessions, activeId, view, onViewChange, query, onQueryChange, searching, archivedCount, busyId, actions }: {
  sessions: ChatSession[];
  activeId: string | null;
  view: SessionView;
  onViewChange: (view: SessionView) => void;
  query: string;
  onQueryChange: (value: string) => void;
  searching?: boolean;
  archivedCount: number;
  busyId?: string | null;
  actions: SessionActions;
}) {
  const [editing, setEditing] = useState<{ id: string; title: string } | null>(null);
  const cancelRename = useRef(false);

  async function commitRename() {
    if (!editing) return;
    const { id, title } = editing;
    const cancelled = cancelRename.current;
    cancelRename.current = false;
    setEditing(null);
    const current = sessions.find((session) => session.id === id);
    if (!cancelled && title.trim() && current && title.trim() !== current.title) await actions.onRename(id, title.trim());
  }

  return <RailCard title="Chats" actions={<button type="button" className="btn btn-primary h-8 px-3 text-xs" onClick={actions.onNew}><MessageSquarePlus className="h-4 w-4" />New chat</button>}>
    <div className="relative mb-3">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
      <input className="input py-2 pl-9 pr-8 text-sm" value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder="Search chats and messages" aria-label="Search chat sessions" />
      {query ? <button type="button" className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full p-1 text-muted hover:text-ink" onClick={() => onQueryChange("")} aria-label="Clear search"><X className="h-3.5 w-3.5" /></button> : null}
    </div>
    <div className="mb-3 flex gap-1 rounded-full bg-linen p-1 text-xs" role="tablist" aria-label="Chat list view">
      {(["active", "archived"] as const).map((item) => <button key={item} type="button" role="tab" aria-selected={view === item} className={cn("flex-1 rounded-full px-3 py-1.5 font-medium transition", view === item ? "bg-white text-ink shadow-sm" : "text-muted hover:text-ink")} onClick={() => onViewChange(item)}>
        {item === "active" ? "Chats" : `Archived${archivedCount ? ` (${archivedCount})` : ""}`}
      </button>)}
    </div>
    <ul className="-mx-1 max-h-[22rem] space-y-1 overflow-y-auto px-1" aria-label={view === "active" ? "Chat sessions" : "Archived chat sessions"}>
      {searching ? <li className="skeleton h-14" /> : null}
      {!searching && sessions.length === 0 ? <li className="rounded-2xl border border-dashed border-line p-4 text-center text-sm text-muted">{query ? "No chats match your search." : view === "archived" ? "No archived chats." : "No chats yet. Ask a question to start one."}</li> : null}
      {!searching ? sessions.map((session) => {
        const active = session.id === activeId;
        const isEditing = editing?.id === session.id;
        return <li key={session.id} className={cn("group rounded-2xl border transition", active ? "border-indigo/40 bg-indigo-soft/60" : "border-transparent hover:border-line hover:bg-paper", busyId === session.id && "opacity-60")}>
          {isEditing ? <div className="p-2">
            <input autoFocus className="input py-1.5 text-sm" value={editing.title} maxLength={200} aria-label="Chat title"
              onChange={(event) => setEditing({ id: session.id, title: event.target.value })}
              onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); event.currentTarget.blur(); } if (event.key === "Escape") { event.preventDefault(); cancelRename.current = true; event.currentTarget.blur(); } }}
              onBlur={() => void commitRename()} />
          </div> : <div className="flex items-start gap-1 p-1">
            <button type="button" className="min-w-0 flex-1 rounded-xl px-2 py-1.5 text-left" onClick={() => actions.onSelect(session.id)} aria-current={active ? "true" : undefined}>
              <span className="flex items-center gap-1.5 text-sm font-medium text-ink">{session.pinned ? <Pin className="h-3.5 w-3.5 shrink-0 fill-current text-indigo-deep" aria-label="Pinned" /> : null}<span className="truncate">{session.title}</span></span>
              <span className="mt-0.5 line-clamp-1 text-xs text-muted">{session.match ?? session.last_message ?? "No messages yet"}</span>
              <span className="mt-0.5 block text-[11px] text-muted/80">{dateLabel(session.updated_at)} · {session.turn_count} messages</span>
            </button>
            <div className={cn("flex shrink-0 flex-col gap-0.5 opacity-0 transition focus-within:opacity-100 group-hover:opacity-100", active && "opacity-100")}>
              <IconButton label={session.pinned ? "Unpin chat" : "Pin chat"} onClick={() => void actions.onTogglePin(session)}>{session.pinned ? <PinOff className="h-3.5 w-3.5" /> : <Pin className="h-3.5 w-3.5" />}</IconButton>
              <IconButton label="Rename chat" onClick={() => setEditing({ id: session.id, title: session.title })}><Pencil className="h-3.5 w-3.5" /></IconButton>
              <IconButton label={session.archived ? "Unarchive chat" : "Archive chat"} onClick={() => void actions.onToggleArchive(session)}>{session.archived ? <ArchiveRestore className="h-3.5 w-3.5" /> : <Archive className="h-3.5 w-3.5" />}</IconButton>
              <IconButton label="Delete chat" danger onClick={() => void actions.onDelete(session)}><Trash2 className="h-3.5 w-3.5" /></IconButton>
            </div>
          </div>}
        </li>;
      }) : null}
    </ul>
  </RailCard>;
}

function IconButton({ label, onClick, danger, children }: { label: string; onClick: () => void; danger?: boolean; children: ReactNode }) {
  return <button type="button" className={cn("rounded-lg p-1 text-muted transition hover:bg-white hover:text-indigo-deep", danger && "hover:text-rose")} onClick={onClick} aria-label={label} title={label}>{children}</button>;
}
