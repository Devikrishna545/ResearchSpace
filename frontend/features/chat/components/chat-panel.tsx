"use client";

import type { Dispatch, ReactNode, SetStateAction } from "react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Archive, ArchiveRestore, ChevronLeft, ChevronRight, ChevronsDownUp, Download, Layers, LoaderCircle, MessageSquarePlus, Pin, RefreshCw } from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import { canCompress, neighborSession, presentMentions, sortSessions, summarizedCount } from "@/features/chat/chat-sessions";
import { draftKey, getDraft, initialChatState, isChatWorkspaceState, optimisticQuestion, reconcileQuestion, updateDraft, type ChatWorkspaceState, type PendingQuestion } from "@/features/chat/chat-state";
import { CHAT_TURNS_LIMIT, createChatExport, type ChatExportFormat } from "@/features/chat/chat-export";
import { withChatReadTimeout } from "@/features/chat/chat-requests";
import { useWorkspaceState } from "@/features/spaces/use-workspace-state";
import { notifyTask } from "@/lib/task-events";
import type { ChatResponse, ChatSession, Citation, Pin as PinnedPaper, ReaderTarget, SessionMention, Turn } from "@/lib/types";
import { cn, dateLabel } from "@/lib/utils";
import { LongOperation } from "./long-operation";
import { Markdown } from "@/components/ui/markdown";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { EmptyInset, ModuleLayout, PanelHeader } from "@/components/ui/module-layout";
import { ChatComposer } from "./chat-composer";
import { ChatSessionList, type SessionView } from "./chat-session-list";
import { ChatTurn, CitationPopover } from "./chat-turn";

const errorText = (err: unknown, fallback: string) => err instanceof ApiError || err instanceof Error ? err.message.replace(/^"|"$/g, "") : fallback;

export interface ChatPrefill { text: string; nonce: number }
export interface ChatFocus { sessionId: string; nonce: number }

export function ChatPanel({ spaceId, pins, openReader, memorySlot, prefill, focus, active = true }: {
  spaceId: string;
  pins: PinnedPaper[];
  openReader: (target: ReaderTarget) => void;
  memorySlot?: ReactNode;
  prefill?: ChatPrefill | null;
  focus?: ChatFocus | null;
  active?: boolean;
}) {
  const paperTitles = useMemo(() => new Map(pins.map((pin) => [pin.id, pin.title])), [pins]);
  const { confirm, dialog } = useConfirm();
  const [catalog, setCatalog] = useState<ChatSession[]>([]);
  const [catalogLoaded, setCatalogLoaded] = useState(false);
  const [workspace, setWorkspace, ready] = useWorkspaceState<ChatWorkspaceState>(spaceId, "chat", initialChatState, isChatWorkspaceState);
  const { activeId, view, query, showFull, pending } = workspace;
  const { text: question, mentions } = getDraft(workspace, activeId);
  const setActiveId = useCallback((id: string | null) => setWorkspace((prev) => ({ ...prev, selected: true, activeId: id })), [setWorkspace]);
  const setView = useCallback((next: SessionView) => setWorkspace((prev) => ({ ...prev, view: next })), [setWorkspace]);
  const setQuery = (next: string) => setWorkspace((prev) => ({ ...prev, query: next }));
  const setQuestion = (text: string) => setWorkspace((prev) => updateDraft(prev, activeId, { text }));
  const setMentions = (next: SessionMention[]) => setWorkspace((prev) => updateDraft(prev, activeId, { mentions: next }));
  const setShowFull: Dispatch<SetStateAction<Record<string, boolean>>> = (next) => setWorkspace((prev) => ({ ...prev, showFull: typeof next === "function" ? next(prev.showFull) : next }));
  const [searchResults, setSearchResults] = useState<ChatSession[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [turnsBySession, setTurnsBySession] = useState<Record<string, Turn[]>>({});
  const [loadingTurns, setLoadingTurns] = useState(false);
  const [lastMeta, setLastMeta] = useState<Record<string, ChatResponse>>({});
  const [liveRequestId, setLiveRequestId] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [exportFormat, setExportFormat] = useState<ChatExportFormat>("markdown");
  const [exporting, setExporting] = useState(false);
  const [compressing, setCompressing] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Guards against a double Enter sending twice before `pending` re-renders.
  const sending = useRef<string | null>(null);
  const recovered = useRef<string | null>(null);
  const handledPrefill = useRef<number | null>(null);
  const handledFocus = useRef<number | null>(null);
  const focusNewComposer = useRef(false);
  const mounted = useRef(false);
  const scopeVersion = useRef(0);
  const historyReads = useRef<Record<string, number>>({});

  // Invalidate in the unmount commit, before delayed promises can reach the global task bus.
  useLayoutEffect(() => {
    mounted.current = true;
    scopeVersion.current += 1;
    return () => { mounted.current = false; scopeVersion.current += 1; };
  }, [spaceId, setWorkspace]);

  useEffect(() => {
    setCatalog([]);
    setCatalogLoaded(false);
    setTurnsBySession({});
    setLastMeta({});
    setSearchResults(null);
    setActiveCitation(null);
    setError(null);
    setLiveRequestId(null);
    setChecking(false);
    setBusyId(null);
    setCompressing(null);
    setExporting(false);
    setLoadingTurns(false);
    setSearching(false);
    sending.current = null;
    recovered.current = null;
    historyReads.current = {};
  }, [spaceId, setWorkspace]);

  const reportError = useCallback((err: unknown, fallback: string) => {
    if (!mounted.current) return;
    const message = errorText(err, fallback);
    setError(message);
    notifyTask({ id: `chat-error-${crypto.randomUUID()}`, spaceId, module: "chat", title: "Chat action failed", message, status: "error" });
  }, [spaceId]);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    const scope = scopeVersion.current;
    setCatalogLoaded(false);
    withChatReadTimeout(api.chatSessions(spaceId, "all")).then((all) => {
      if (cancelled || scope !== scopeVersion.current) return;
      setCatalog(all);
      setWorkspace((prev) => {
        const restored = prev.selected ? all.find((session) => session.id === prev.activeId) : sortSessions(all.filter((session) => !session.archived))[0];
        return { ...prev, selected: true, activeId: prev.selected ? prev.activeId : restored?.id ?? null, view: !prev.selected && restored?.archived ? "archived" : prev.view,
          pending: prev.pending ? { ...prev.pending, status: prev.pending.status === "failed" ? "failed" : "unknown" } : null };
      });
    }).catch((err: unknown) => { if (!cancelled && scope === scopeVersion.current) reportError(err, "Could not load chats."); })
      .finally(() => { if (!cancelled && scope === scopeVersion.current) setCatalogLoaded(true); });
    return () => { cancelled = true; };
  }, [spaceId, ready, reportError, setWorkspace]);

  // Server-side search covers titles and message text; debounce keystrokes.
  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    const scope = scopeVersion.current;
    const q = query.trim();
    if (!q) { setSearchResults(null); setSearching(false); return; }
    setSearching(true);
    const handle = window.setTimeout(() => {
      withChatReadTimeout(api.chatSessions(spaceId, view, q))
        .then((results) => { if (!cancelled && scope === scopeVersion.current) setSearchResults(results); })
        .catch((err: unknown) => { if (!cancelled && scope === scopeVersion.current) { setSearchResults([]); reportError(err, "Could not search chats."); } })
        .finally(() => { if (!cancelled && scope === scopeVersion.current) setSearching(false); });
    }, 250);
    return () => { cancelled = true; window.clearTimeout(handle); };
  }, [query, spaceId, view, catalog, ready, reportError]);

  const activeSession = catalog.find((session) => session.id === activeId) ?? null;
  const visibleSessions = useMemo(
    () => searchResults ?? sortSessions(catalog.filter((session) => session.archived === (view === "archived"))),
    [catalog, searchResults, view],
  );
  const archivedCount = catalog.filter((session) => session.archived).length;
  const turns = useMemo(() => (activeId ? turnsBySession[activeId] ?? [] : []), [activeId, turnsBySession]);
  const cachedActive = activeId ? activeId in turnsBySession : true;

  useEffect(() => {
    if (!ready || !catalogLoaded || !activeId || cachedActive) return;
    let cancelled = false;
    const scope = scopeVersion.current;
    const revision = (historyReads.current[activeId] ?? 0) + 1;
    historyReads.current[activeId] = revision;
    setLoadingTurns(true);
    withChatReadTimeout(Promise.all([api.chatSession(activeId), api.chatSessionTurns(activeId, CHAT_TURNS_LIMIT)]))
      .then(([session, loaded]) => {
        if (cancelled || scope !== scopeVersion.current || historyReads.current[activeId] !== revision) return;
        if (session.space_id !== spaceId) throw new Error("This chat does not belong to the current space.");
        setCatalog((prev) => prev.some((item) => item.id === session.id) ? prev.map((item) => item.id === session.id ? session : item) : [session, ...prev]);
        setTurnsBySession((prev) => ({ ...prev, [activeId]: loaded }));
      })
      .catch((err: unknown) => {
        if (cancelled || scope !== scopeVersion.current) return;
        reportError(err, "Could not load this chat.");
        if (err instanceof ApiError && err.status === 404) setActiveId(null);
      })
      .finally(() => { if (!cancelled && scope === scopeVersion.current) setLoadingTurns(false); });
    return () => { cancelled = true; };
  }, [activeId, cachedActive, catalogLoaded, ready, reportError, setActiveId, spaceId]);

  useEffect(() => {
    if (!active) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [active, activeId, turns.length, pending, showFull]);

  useEffect(() => {
    if (!active || !focusNewComposer.current) return;
    focusNewComposer.current = false;
    document.getElementById("question")?.focus();
  }, [active, activeId]);

  useEffect(() => {
    if (!active || !ready || !prefill || handledPrefill.current === prefill.nonce) return;
    handledPrefill.current = prefill.nonce;
    setWorkspace((prev) => updateDraft(prev, prev.activeId, { text: prefill.text, mentions: [] }));
    const frame = window.requestAnimationFrame(() => document.getElementById("question")?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [active, ready, prefill, setWorkspace]);

  const selectSession = useCallback((id: string | null) => {
    setActiveId(id);
    setError(null);
    const target = catalog.find((session) => session.id === id);
    if (target && !query) setView(target.archived ? "archived" : "active");
  }, [catalog, query, setActiveId, setView]);

  useEffect(() => {
    if (!active || !focus || !catalogLoaded || handledFocus.current === focus.nonce) return;
    handledFocus.current = focus.nonce;
    selectSession(focus.sessionId);
  }, [active, focus, catalogLoaded, selectSession]);

  const navigate = useCallback((direction: -1 | 1) => {
    const next = neighborSession(visibleSessions, activeId, direction);
    if (next) selectSession(next);
  }, [activeId, selectSession, visibleSessions]);
  const previousId = neighborSession(visibleSessions, activeId, -1);
  const nextId = neighborSession(visibleSessions, activeId, 1);

  useEffect(() => {
    if (!active) return;
    const onKey = (event: KeyboardEvent) => {
      if (!event.altKey || (event.key !== "ArrowUp" && event.key !== "ArrowDown")) return;
      event.preventDefault();
      navigate(event.key === "ArrowUp" ? -1 : 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, navigate]);

  function startNewChat() {
    focusNewComposer.current = active && activeId !== null;
    setActiveId(null);
    setView("active");
    setError(null);
    if (active && activeId === null) document.getElementById("question")?.focus();
  }

  const upsertSession = useCallback((session: ChatSession) => {
    setCatalog((prev) => prev.some((item) => item.id === session.id) ? prev.map((item) => item.id === session.id ? session : item) : [session, ...prev]);
    setSearchResults((prev) => prev?.map((item) => item.id === session.id ? { ...session, match: item.match } : item) ?? null);
  }, []);

  const checkQuestion = useCallback(async (request: PendingQuestion) => {
    if (!request.sessionId) return null;
    const scope = scopeVersion.current;
    const revision = (historyReads.current[request.sessionId] ?? 0) + 1;
    historyReads.current[request.sessionId] = revision;
    const [session, loaded] = await withChatReadTimeout(Promise.all([api.chatSession(request.sessionId), api.chatSessionTurns(request.sessionId, CHAT_TURNS_LIMIT)]));
    if (scope !== scopeVersion.current || historyReads.current[request.sessionId] !== revision) return null;
    if (session.space_id !== spaceId) throw new Error("This chat does not belong to the current space.");
    upsertSession(session);
    setTurnsBySession((prev) => ({ ...prev, [session.id]: loaded }));
    const result = reconcileQuestion(request, loaded, Math.max(session.turn_count, loaded.length));
    setWorkspace((prev) => {
      if (prev.pending?.id !== request.id) return prev;
      return { ...prev, pending: result.status === "answered" ? null : { ...prev.pending, userTurnId: result.userTurnId, status: sending.current === request.id ? prev.pending.status : "unknown" } };
    });
    if (result.status === "answered") {
      notifyTask({ id: `${request.id}:response`, spaceId, module: "chat", title: "Chat response ready", message: session.title, status: "success" });
    }
    return result;
  }, [spaceId, setWorkspace, upsertSession]);

  useEffect(() => {
    if (!ready || !catalogLoaded || !pending?.sessionId || liveRequestId === pending.id || recovered.current === pending.id) return;
    recovered.current = pending.id;
    const scope = scopeVersion.current;
    setChecking(true);
    checkQuestion(pending)
      .catch((err: unknown) => { if (scope === scopeVersion.current) reportError(err, "Could not check the interrupted request. Try checking again."); })
      .finally(() => { if (scope === scopeVersion.current) setChecking(false); });
  }, [ready, catalogLoaded, pending, liveRequestId, checkQuestion, reportError]);

  async function checkPending() {
    if (!pending || checking) return;
    const scope = scopeVersion.current;
    setChecking(true);
    setError(null);
    try { await checkQuestion(pending); }
    catch (err) { if (scope === scopeVersion.current) reportError(err, "Could not check for a saved response. Your question is retained."); }
    finally { if (scope === scopeVersion.current) setChecking(false); }
  }

  async function recoverDraft() {
    if (!pending || (sending.current === pending.id && pending.status !== "unknown")) return;
    const request = pending;
    const scope = scopeVersion.current;
    const ok = await confirm({
      title: "Restore this question to its draft?",
      message: `${request.sessionId ? "The server may still finish this request. Check for a saved response before sending again. " : ""}This stops tracking the request and replaces any draft in its chat. Nothing will be sent automatically.`,
      confirmLabel: "Restore draft",
    });
    if (!ok || scope !== scopeVersion.current) return;
    if (sending.current === request.id) { sending.current = null; setLiveRequestId(null); }
    setWorkspace((prev) => prev.pending?.id !== request.id ? prev : {
      ...updateDraft(prev, request.sessionId, { text: request.text, mentions: request.mentions }),
      selected: true, activeId: request.sessionId, pending: null,
    });
    setError(null);
  }

  useEffect(() => {
    if (!pending || liveRequestId !== pending.id || pending.status === "unknown" || pending.status === "failed") return;
    const scope = scopeVersion.current;
    // A transport request can outlive its UI budget. Keep it running, but stop claiming progress.
    const timer = window.setTimeout(() => {
      if (scope !== scopeVersion.current) return;
      setWorkspace((prev) => prev.pending?.id === pending.id ? { ...prev, pending: { ...prev.pending, status: "unknown" } } : prev);
    }, Math.max(0, 180_000 - (Date.now() - pending.since)));
    return () => window.clearTimeout(timer);
  }, [pending, liveRequestId, setWorkspace]);

  async function submit(raw: string, chosenMentions: SessionMention[], since: number) {
    const text = raw.trim();
    if (!ready || !catalogLoaded || !text || pending || sending.current || activeSession?.archived) return;
    const sent = presentMentions(text, chosenMentions);
    setError(null);
    const scope = scopeVersion.current;
    let request: PendingQuestion = {
      id: crypto.randomUUID(), sessionId: activeId, text, mentions: sent, since,
      baselineCount: activeSession?.turn_count ?? 0, baselineLastId: turns.filter((turn) => !turn.id.startsWith("local-")).at(-1)?.id ?? null,
      status: activeId ? "pending" : "creating",
    };
    sending.current = request.id;
    setLiveRequestId(request.id);
    const initialRequest = request;
    setWorkspace((prev) => ({ ...updateDraft(prev, activeId, { text: "", mentions: [] }), pending: initialRequest }));
    try {
      if (!request.sessionId) {
        const created = await api.createChatSession(spaceId);
        if (scope !== scopeVersion.current || sending.current !== request.id) return;
        upsertSession(created);
        request = { ...request, sessionId: created.id, status: "pending" };
        const createdRequest = request;
        setTurnsBySession((prev) => ({ ...prev, [created.id]: [] }));
        setWorkspace((prev) => ({
          ...updateDraft(updateDraft(prev, created.id, getDraft(prev, null)), null, { text: "", mentions: [] }),
          activeId: prev.activeId === null ? created.id : prev.activeId, selected: true,
          pending: prev.pending?.id === createdRequest.id ? createdRequest : prev.pending,
        }));
      }
      const target = request.sessionId!;
      const response = await api.chat(spaceId, text, { sessionId: target, mentionedSessionIds: sent.map((mention) => mention.id) });
      if (scope !== scopeVersion.current) return;
      historyReads.current[target] = (historyReads.current[target] ?? 0) + 1;
      request = { ...request, responseTurnId: response.turn_id };
      setWorkspace((prev) => prev.pending?.id === request.id ? { ...prev, pending: { ...prev.pending, responseTurnId: response.turn_id } } : prev);
      const assistant: Turn = { id: response.turn_id, role: "assistant", content: response.answer, citations: response.citations, created_at: new Date().toISOString(), session_id: target };
      setTurnsBySession((prev) => {
        const existing = prev[target] ?? [];
        const result = reconcileQuestion(request, existing, activeSession?.turn_count ?? existing.length);
        return { ...prev, [target]: [...existing, ...(result.status === "missing" ? [optimisticQuestion(request)] : []), ...(!existing.some((turn) => turn.id === assistant.id) ? [assistant] : [])] };
      });
      setLastMeta((prev) => ({ ...prev, [response.turn_id]: response }));
      notifyTask({ id: `${request.id}:response`, spaceId, module: "chat", title: "Chat response ready", message: activeSession?.title ?? "New chat", status: "success" });
      try { await checkQuestion(request); }
      catch (err) {
        if (scope !== scopeVersion.current) return;
        setWorkspace((prev) => prev.pending?.id === request.id ? { ...prev, pending: { ...prev.pending, status: "unknown" } } : prev);
        reportError(err, "The answer arrived, but saved history could not be refreshed. Check for the saved response.");
      }
    } catch (err) {
      if (scope !== scopeVersion.current) return;
      const message = errorText(err, "The local model could not answer right now.");
      setWorkspace((prev) => prev.pending?.id === request.id ? { ...prev, pending: { ...prev.pending, status: request.sessionId ? "unknown" : "failed", error: message } } : prev);
      reportError(err, "The request was interrupted. Your question is retained; check whether the server saved a response.");
    } finally {
      if (scope === scopeVersion.current && sending.current === request.id) { sending.current = null; setLiveRequestId(null); }
    }
  }

  async function mutate(session: ChatSession, update: Parameters<typeof api.updateChatSession>[1]) {
    const scope = scopeVersion.current;
    setBusyId(session.id);
    setError(null);
    try {
      const updated = await api.updateChatSession(session.id, update);
      if (scope !== scopeVersion.current) return null;
      upsertSession(updated);
      return updated;
    } catch (err) {
      if (scope === scopeVersion.current) reportError(err, "Could not update this chat.");
      return null;
    } finally {
      if (scope === scopeVersion.current) setBusyId(null);
    }
  }

  const actions = {
    onSelect: (id: string) => selectSession(id),
    onNew: startNewChat,
    onRename: async (id: string, title: string) => { const session = catalog.find((item) => item.id === id); if (session) await mutate(session, { title }); },
    onTogglePin: async (session: ChatSession) => { await mutate(session, { pinned: !session.pinned }); },
    onToggleArchive: async (session: ChatSession) => {
      const scope = scopeVersion.current;
      const archiving = !session.archived;
      const leaving = session.id === activeId ? neighborSession(visibleSessions, activeId, 1) ?? neighborSession(visibleSessions, activeId, -1) : activeId;
      const updated = await mutate(session, { archived: archiving });
      if (!updated || scope !== scopeVersion.current) return;
      if (query) setSearchResults((prev) => prev?.filter((item) => item.id !== session.id) ?? null);
      if (session.id !== activeId) return;
      // Archiving moves on to a neighbouring chat; unarchiving keeps the chat open to continue it.
      if (archiving) { if (!query) setActiveId(leaving); } else setView("active");
    },
    onDelete: async (session: ChatSession) => {
      if (pending?.sessionId === session.id) { reportError(new Error("Check or recover the outstanding question before deleting this chat."), "Could not delete this chat."); return; }
      const scope = scopeVersion.current;
      const ok = await confirm({ title: "Delete this chat?", message: `“${session.title}” and all of its ${session.turn_count} messages will be permanently deleted. This cannot be undone.`, confirmLabel: "Delete chat" });
      if (!ok || scope !== scopeVersion.current) return;
      setBusyId(session.id);
      try {
        await api.deleteChatSession(session.id);
        if (scope !== scopeVersion.current) return;
        const fallback = neighborSession(visibleSessions, session.id, 1) ?? neighborSession(visibleSessions, session.id, -1);
        setCatalog((prev) => prev.filter((item) => item.id !== session.id));
        setSearchResults((prev) => prev?.filter((item) => item.id !== session.id) ?? null);
        setTurnsBySession((prev) => { const next = { ...prev }; delete next[session.id]; return next; });
        setWorkspace((prev) => {
          const drafts = { ...prev.drafts };
          const expanded = { ...prev.showFull };
          delete drafts[draftKey(session.id)];
          delete expanded[session.id];
          return { ...prev, drafts, showFull: expanded };
        });
        if (session.id === activeId) setActiveId(fallback);
      } catch (err) {
        if (scope === scopeVersion.current) reportError(err, "Could not delete this chat.");
      } finally {
        if (scope === scopeVersion.current) setBusyId(null);
      }
    },
  };

  async function compress() {
    if (!activeSession) return;
    const scope = scopeVersion.current;
    setCompressing(activeSession.id);
    setError(null);
    try {
      const session = await api.compressChatSession(activeSession.id);
      if (scope !== scopeVersion.current) return;
      upsertSession(session);
      setShowFull((prev) => ({ ...prev, [activeSession.id]: false }));
      notifyTask({ id: `chat-compress-${crypto.randomUUID()}`, spaceId, module: "chat", title: "Chat summary updated", message: activeSession.title, status: "success" });
    } catch (err) {
      if (scope === scopeVersion.current) reportError(err, "Could not compress this conversation.");
    } finally {
      if (scope === scopeVersion.current) setCompressing(null);
    }
  }

  async function exportChat() {
    if (!activeSession || exporting) return;
    const scope = scopeVersion.current;
    setExporting(true);
    setError(null);
    let url: string | null = null;
    try {
      const session = await withChatReadTimeout(api.chatSession(activeSession.id));
      if (scope !== scopeVersion.current) return;
      if (session.space_id !== spaceId) throw new Error("This chat does not belong to the current space.");
      if (session.turn_count > CHAT_TURNS_LIMIT) throw new Error(`This chat exceeds the API's ${CHAT_TURNS_LIMIT}-message export limit. A complete export is not possible; no partial file was downloaded.`);
      const saved = await withChatReadTimeout(api.chatSessionTurns(session.id, CHAT_TURNS_LIMIT));
      if (scope !== scopeVersion.current) return;
      const latestSession = await withChatReadTimeout(api.chatSession(session.id));
      if (scope !== scopeVersion.current) return;
      const file = createChatExport(latestSession, saved, exportFormat);
      url = URL.createObjectURL(new Blob([file.content], { type: file.mime }));
      const link = document.createElement("a");
      link.href = url;
      link.download = file.filename;
      document.body.appendChild(link);
      try { link.click(); } finally { link.remove(); }
    } catch (err) {
      if (scope === scopeVersion.current) reportError(err, "Could not export this chat.");
    } finally {
      if (url) URL.revokeObjectURL(url);
      if (scope === scopeVersion.current) setExporting(false);
    }
  }

  const covered = summarizedCount(activeSession, turns);
  const expanded = activeId ? Boolean(showFull[activeId]) : false;
  const shownTurns = covered && !expanded ? turns.slice(covered) : turns;
  const compressible = canCompress(activeSession);
  const isPendingHere = pending && pending.sessionId === activeId;
  const pendingResult = isPendingHere ? reconcileQuestion(pending, turns, activeSession?.turn_count ?? turns.length) : null;
  const showOptimistic = isPendingHere && pendingResult?.status === "missing" && !turns.some((turn) => turn.id === `local-${pending.id}`);
  const livePending = pending && liveRequestId === pending.id && (pending.status === "pending" || pending.status === "creating");
  const mentionCandidates = useMemo(() => sortSessions(catalog.filter((session) => session.id !== activeId && session.turn_count > 0)), [catalog, activeId]);

  const conversation = <div className="panel flex flex-col p-4 md:p-6">
    <div className="mb-4 flex flex-wrap items-center gap-2 border-b border-line pb-4">
      <div className="flex items-center gap-1">
        <button type="button" className="btn h-9 w-9 p-0" onClick={() => navigate(-1)} disabled={!previousId} aria-label="Previous chat" title="Previous chat (Alt+↑)"><ChevronLeft className="h-4 w-4" /></button>
        <button type="button" className="btn h-9 w-9 p-0" onClick={() => navigate(1)} disabled={!nextId} aria-label="Next chat" title="Next chat (Alt+↓)"><ChevronRight className="h-4 w-4" /></button>
      </div>
      <div className="min-w-0 flex-1">
        <h3 className="flex items-center gap-2 truncate font-serif text-2xl">{activeSession?.pinned ? <Pin className="h-4 w-4 shrink-0 fill-current text-indigo-deep" aria-label="Pinned" /> : null}<span className="truncate">{activeSession?.title ?? "New chat"}</span></h3>
        <p className="text-xs text-muted">{activeSession ? `${activeSession.turn_count} messages · updated ${dateLabel(activeSession.updated_at)}` : "Start a fresh conversation — existing chats stay untouched."}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {activeSession ? <div className="flex gap-1">
          <select aria-label="Chat export format" className="input h-9 w-auto py-1 text-sm" value={exportFormat} onChange={(event) => setExportFormat(event.target.value as ChatExportFormat)}>
            <option value="markdown">Markdown</option><option value="json">JSON</option>
          </select>
          <button type="button" className="btn h-9 px-3" onClick={() => void exportChat()} disabled={exporting} title="Download all saved messages, including the original compressed turns">
            {exporting ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}Export chat
          </button>
        </div> : null}
        {compressible ? <button type="button" className="btn h-9 px-3" onClick={() => void compress()} disabled={Boolean(compressing) || Boolean(pending)} title="Summarise older messages for easier review">
          {compressing === activeId ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Layers className="h-4 w-4" />}{activeSession?.summary ? "Update summary" : "Compress"}
        </button> : null}
        <button type="button" className="btn h-9 px-3" onClick={startNewChat}><MessageSquarePlus className="h-4 w-4" />New chat</button>
      </div>
    </div>
    {activeSession?.archived ? <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-amber/30 bg-amber/10 p-3 text-sm">
      <span className="flex items-center gap-2"><Archive className="h-4 w-4" />This chat is archived. Unarchive it to continue the conversation.</span>
      <button type="button" className="btn h-8 px-3" onClick={() => void actions.onToggleArchive(activeSession)}><ArchiveRestore className="h-4 w-4" />Unarchive</button>
    </div> : null}
    <div ref={scrollRef} className="min-h-[18rem] flex-1 space-y-5 overflow-y-auto pr-1 xl:max-h-[calc(100vh-24rem)] max-h-[65vh]" aria-live="polite">
      {loadingTurns && !cachedActive ? <div className="space-y-3"><div className="skeleton h-20" /><div className="skeleton h-32" /></div> : null}
      {covered && activeSession?.summary ? <CompressedSummary summary={activeSession.summary} count={activeSession.summary_turn_count} expanded={expanded} updatedAt={activeSession.summary_updated_at}
        onToggle={() => activeId && setShowFull((prev) => ({ ...prev, [activeId]: !prev[activeId] }))} /> : null}
      {!loadingTurns && turns.length === 0 && !isPendingHere ? <EmptyInset title={activeSession ? "No messages in this chat" : "Start a new chat"} text="Ask a question that can be answered from your pinned papers. Type @ to reference another chat." /> : null}
      {shownTurns.map((turn) => <ChatTurn key={turn.id} turn={turn} meta={lastMeta[turn.id]} onCitation={setActiveCitation} onOpenSession={(id) => selectSession(id)} />)}
      {showOptimistic ? <ChatTurn turn={optimisticQuestion(pending)} onCitation={setActiveCitation} onOpenSession={selectSession} /> : null}
      {isPendingHere && livePending && active ? <LongOperation startedAt={pending.since} label={pending.status === "creating" ? "Creating this chat — question retained" : "Waiting for a response"} /> : null}
      {isPendingHere && !livePending ? <div role="status" className="rounded-2xl border border-amber/30 bg-amber/10 p-4 text-sm">
        <p className="font-semibold">{pending.status === "failed" ? "Request failed — question retained" : "Request interrupted or status unknown"}</p>
        <p className="mt-1">{pending.responseTurnId ? "An answer was returned, but saved history still needs to be checked." : pending.sessionId ? "The server may still be processing your question. Nothing has been resent." : "Chat creation was interrupted. The question has not been confirmed sent."}</p>
        {pendingResult?.status === "saved" ? <p className="mt-1">Your question is saved; no saved answer was found yet.</p> : null}
        {pending.error ? <p className="mt-1 text-rose">{pending.error}</p> : null}
        <div className="mt-3 flex flex-wrap gap-2">
          {pending.sessionId ? <button type="button" className="btn" onClick={() => void checkPending()} disabled={checking}><RefreshCw className={cn("h-4 w-4", checking && "animate-spin")} />{checking ? "Checking…" : "Check for saved response"}</button> : null}
          <button type="button" className="btn" onClick={() => void recoverDraft()} disabled={checking}>Restore question to draft</button>
        </div>
      </div> : null}
    </div>
    {error ? <p role="alert" className="mt-4 rounded-2xl bg-rose/10 p-3 text-sm text-rose">{error}</p> : null}
    {pending && !isPendingHere ? <p className="mt-4 text-xs text-muted">{livePending ? "Another chat is waiting for an answer." : "Another chat has an interrupted request to check or recover."} Your draft here is saved. <button type="button" className="underline" onClick={() => selectSession(pending.sessionId)}>Open that question</button></p> : null}
    <div className="mt-5">
      <ChatComposer key={draftKey(activeId)} active={active} value={question} onChange={setQuestion} mentions={mentions} onMentionsChange={setMentions} candidates={mentionCandidates}
        disabled={!ready || !catalogLoaded || Boolean(activeSession?.archived)} busy={Boolean(pending) || Boolean(liveRequestId)} onSubmit={(text, chosen) => void submit(text, chosen, Date.now())}
        placeholder={activeSession?.archived ? "Unarchive this chat to reply" : "What does the evidence say about…?"} />
    </div>
  </div>;

  if (!ready) return <div className="panel p-6" role="status">Restoring chat workspace…</div>;

  return <>
    <ModuleLayout asideFirstOnMobile
      header={<PanelHeader eyebrow="Grounded Q&A" title="Ask the pinned papers" text="Answers are generated locally and checked by a peer-review loop before they appear. Keep separate chats per line of inquiry." />}
      main={conversation}
      aside={<ChatSessionList sessions={visibleSessions} activeId={activeId} view={view} onViewChange={(next) => { setView(next); }} query={query} onQueryChange={setQuery}
          searching={searching || !catalogLoaded} archivedCount={archivedCount} busyId={busyId} actions={actions} />}
      asideTrailing={memorySlot} />
    {active && activeCitation ? <CitationPopover citation={activeCitation} onClose={() => setActiveCitation(null)} paperTitles={paperTitles} onOpenPaper={openReader} /> : null}
    {active ? dialog : null}
  </>;
}

function CompressedSummary({ summary, count, expanded, updatedAt, onToggle }: { summary: string; count: number; expanded: boolean; updatedAt?: string | null; onToggle: () => void }) {
  return <section className="rounded-3xl border border-indigo/25 bg-indigo-soft/40 p-5">
    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
      <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-indigo-deep"><Layers className="h-4 w-4" />Summary of {count} earlier messages{updatedAt ? ` · ${dateLabel(updatedAt)}` : ""}</p>
      <button type="button" className="btn h-8 px-3 text-xs" onClick={onToggle} aria-expanded={expanded}>{expanded ? <><ChevronsDownUp className="h-3.5 w-3.5" />Collapse to summary</> : "Show full conversation"}</button>
    </div>
    <div className={cn("text-sm", expanded && "opacity-80")}><Markdown content={summary} /></div>
  </section>;
}
