"use client";

import { useEffect, useRef, useState } from "react";
import { Copy, Download, Mail, X } from "lucide-react";
import { api, ApiError, type LinkedInSource, type LinkedInStatus } from "@/lib/api/client";

export interface ShareItem {
  id: string;
  source: LinkedInSource;
  kind: string;
  text: string;
  citation?: string;
  warning?: string;
}

const WIDTH = 1080;
const HEIGHT = 1350;
const EMAIL_URL_LIMIT = 1800;

function wrapLines(ctx: CanvasRenderingContext2D, text: string, width: number): string[] {
  const lines: string[] = [];
  for (const paragraph of text.split(/\r?\n/)) {
    if (!paragraph.trim()) { lines.push(""); continue; }
    let line = "";
    for (const word of paragraph.split(/\s+/)) {
      const candidate = line ? `${line} ${word}` : word;
      if (ctx.measureText(candidate).width <= width) { line = candidate; continue; }
      if (line) lines.push(line);
      line = "";
      // Break unusually long tokens too, rather than cropping them at the edge.
      for (const char of word) {
        if (line && ctx.measureText(line + char).width > width) {
          lines.push(line);
          line = "";
        }
        line += char;
      }
    }
    lines.push(line);
  }
  return lines;
}

function drawCard(canvas: HTMLCanvasElement, kind: string, text: string, citation: string): boolean {
  const ctx = canvas.getContext("2d");
  if (!ctx) return false;
  canvas.width = WIDTH;
  canvas.height = HEIGHT;
  ctx.fillStyle = "#f6f3ed";
  ctx.fillRect(0, 0, WIDTH, HEIGHT);
  ctx.fillStyle = "#33287d";
  ctx.fillRect(0, 0, WIDTH, 18);
  ctx.fillStyle = "#33287d";
  ctx.font = "bold 32px sans-serif";
  ctx.fillText("RESEARCH NOTE", 88, 120);
  ctx.fillStyle = "#22203b";
  ctx.font = "bold 66px Georgia, serif";
  const heading = wrapLines(ctx, kind, 904);
  if (heading.length > 2) return false;
  heading.forEach((line, index) => ctx.fillText(line, 88, 235 + index * 78));
  const bodyTop = 305 + (heading.length - 1) * 78;
  const sourceTop = citation ? 1130 : 1200;
  const availableHeight = sourceTop - bodyTop - 65;
  let lines: string[] = [];
  let fontSize = 50;
  for (; fontSize >= 26; fontSize -= 2) {
    ctx.font = `${fontSize}px Georgia, serif`;
    lines = wrapLines(ctx, text, 904);
    if (lines.length * fontSize * 1.4 <= availableHeight) break;
  }
  if (fontSize < 26) return false;
  ctx.fillStyle = "#22203b";
  ctx.font = `${fontSize}px Georgia, serif`;
  lines.forEach((line, index) => ctx.fillText(line, 88, bodyTop + index * fontSize * 1.4));
  if (citation) {
    ctx.fillStyle = "#514a68";
    ctx.font = "26px sans-serif";
    const sourceLines = wrapLines(ctx, citation, 904);
    if (sourceLines.length > 4) return false;
    ctx.fillRect(88, 1060, 904, 2);
    sourceLines.forEach((line, index) => ctx.fillText(line, 88, 1112 + index * 35));
  }
  ctx.fillStyle = "#766d80";
  ctx.font = "24px sans-serif";
  ctx.fillText("Edited and shared by the author", 88, 1280);
  return true;
}

export function SharePreview({ item, onClose }: { item: ShareItem; onClose: () => void }) {
  const [text, setText] = useState(item.text);
  const [includeCitation, setIncludeCitation] = useState(false);
  const [citation, setCitation] = useState(item.citation ?? "");
  const [status, setStatus] = useState("");
  const [imageFits, setImageFits] = useState(false);
  const [linkedin, setLinkedin] = useState<LinkedInStatus | null>(null);
  const [visibility, setVisibility] = useState<"" | "PUBLIC" | "CONNECTIONS">("");
  const [confirmed, setConfirmed] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [published, setPublished] = useState(false);
  const requestId = useRef<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const body = `${item.kind}\n\n${text.trim()}${includeCitation && citation.trim() ? `\n\nSource: ${citation.trim()}` : ""}`;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  useEffect(() => {
    if (canvasRef.current) setImageFits(drawCard(canvasRef.current, item.kind, text.trim(), includeCitation ? `Source: ${citation.trim()}` : ""));
  }, [item.kind, text, includeCitation, citation]);
  useEffect(() => {
    let active = true;
    api.linkedinStatus().then((result) => { if (active) setLinkedin(result); }).catch(() => {
      if (active) setLinkedin({ available: false, connected: false, reason: "LinkedIn status could not be checked." });
    });
    return () => { active = false; };
  }, []);

  async function connect() {
    try {
      const { authorization_url } = await api.linkedinConnect();
      window.location.assign(authorization_url);
    } catch {
      setStatus("LinkedIn connection could not start. Check developer credentials and HTTPS callback configuration.");
    }
  }

  async function disconnect() {
    try {
      const result = await api.linkedinDisconnect();
      setLinkedin({ available: true, connected: false });
      setStatus(result.external_revocation);
    } catch {
      setStatus("LinkedIn disconnect failed; the connection was not removed.");
    }
  }

  async function publish() {
    if (!linkedin?.connected || !visibility || !confirmed || !text.trim() || publishing || published) return;
    setPublishing(true);
    setStatus("");
    if (!requestId.current) requestId.current = crypto.randomUUID();
    try {
      const result = await api.linkedinPublish(item.source, body, visibility, requestId.current);
      setStatus(`Published to LinkedIn (${result.visibility}). No other workspace content was sent.`);
      setPublished(true);
      setConfirmed(false);
    } catch (error) {
      setStatus(error instanceof ApiError && (error.status === 409 || error.status === 503)
        ? error.message
        : error instanceof ApiError && error.status === 429
          ? "LinkedIn rate limit reached. Check your profile; do not retry this request automatically."
          : "LinkedIn did not confirm publication. Check your profile before reopening the preview and trying again; this request cannot be posted twice.");
    } finally {
      setPublishing(false);
    }
  }

  async function copy(value = body) {
    try {
      await navigator.clipboard.writeText(value);
      setStatus("Copied. Only the text shown above was copied.");
      return true;
    } catch {
      setStatus("Clipboard unavailable. Select and copy the preview text manually.");
      return false;
    }
  }

  async function email() {
    const link = `mailto:?subject=${encodeURIComponent(item.kind)}&body=${encodeURIComponent(body)}`;
    if (link.length > EMAIL_URL_LIMIT) {
      if (await copy()) setStatus("Email text is too long for a mailto link. Copied instead; paste it into your email.");
      return;
    }
    window.location.href = link;
  }

  function download() {
    const canvas = canvasRef.current;
    if (!canvas || !imageFits) return;
    canvas.toBlob((blob) => {
      if (!blob) { setStatus("Could not create image. Try again in another browser."); return; }
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `research-${item.kind.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.png`;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setStatus("Image downloaded locally. Nothing was posted to Instagram.");
    }, "image/png");
  }

  return <div className="fixed inset-0 z-[80] overflow-y-auto bg-ink/50 p-4 backdrop-blur-sm" onClick={onClose}>
    <section role="dialog" aria-modal="true" aria-labelledby="share-heading" className="mx-auto my-4 max-w-5xl rounded-3xl border border-line bg-paper p-5 shadow-soft md:p-8" onClick={(event) => event.stopPropagation()}>
      <div className="mb-5 flex items-start justify-between gap-4"><div><p className="eyebrow">Selective sharing</p><h2 id="share-heading" className="font-serif text-3xl">Share one {item.kind.toLowerCase()}</h2><p className="mt-2 text-sm text-muted">Review and redact the text before sending it. Nothing is published or shared automatically.</p></div><button type="button" className="btn h-10 w-10 shrink-0 p-0" onClick={onClose} aria-label="Close share preview"><X className="h-4 w-4" /></button></div>
      {item.warning ? <p className="mb-4 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-ink" role="alert">{item.warning}</p> : null}
      <div className="grid gap-6 md:grid-cols-2">
        <div className="space-y-4">
          <label className="block text-sm font-medium" htmlFor="share-text">Text to share (edit or remove anything private)</label>
          <textarea id="share-text" autoFocus className="input min-h-56" value={text} onChange={(event) => { setText(event.target.value); setConfirmed(false); setStatus(""); }} />
          {item.citation ? <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={includeCitation} onChange={(event) => { setIncludeCitation(event.target.checked); setConfirmed(false); }} />Include source citation (off by default)</label> : <p className="text-sm text-muted">No source citation available for this item.</p>}
          {includeCitation ? <><label className="block text-sm font-medium" htmlFor="share-citation">Source citation (editable)</label><textarea id="share-citation" className="input min-h-20" value={citation} onChange={(event) => { setCitation(event.target.value); setConfirmed(false); }} /></> : null}
          <div><p className="mb-2 text-sm font-medium">Exact text for copy or email</p><pre className="max-h-52 overflow-auto whitespace-pre-wrap break-words rounded-xl border border-line bg-white p-3 text-sm">{body}</pre></div>
          <div className="flex flex-wrap gap-2"><button type="button" className="btn btn-primary" disabled={!text.trim()} onClick={() => void copy()}><Copy className="h-4 w-4" />Copy text</button><button type="button" className="btn" disabled={!text.trim()} onClick={() => void email()}><Mail className="h-4 w-4" />Open email</button></div>
          <div className="rounded-xl border border-line bg-white p-4 text-sm">
            <p className="font-medium">LinkedIn member post (optional)</p>
            {!linkedin ? <p className="mt-2 text-muted">Checking connection…</p>
              : !linkedin.available ? <p className="mt-2 text-muted">Unavailable: {linkedin.reason}</p>
              : !linkedin.connected ? <><p className="mt-2 text-muted">Connect separately using an approved LinkedIn app with member-posting permission. The configured callback must be HTTPS.</p><button type="button" className="btn mt-3" onClick={() => void connect()}>Connect LinkedIn</button></>
              : <>
                <p className="mt-2 text-muted">Only the exact edited text above will be posted; no paper, workspace, or app link is attached.</p>
                <fieldset className="mt-3"><legend className="font-medium">Choose visibility for this post</legend><label className="mt-2 flex gap-2"><input type="radio" name="linkedin-visibility" checked={visibility === "CONNECTIONS"} onChange={() => { setVisibility("CONNECTIONS"); setConfirmed(false); }} />Connections only</label><label className="mt-2 flex gap-2"><input type="radio" name="linkedin-visibility" checked={visibility === "PUBLIC"} onChange={() => { setVisibility("PUBLIC"); setConfirmed(false); }} />Public</label></fieldset>
                <label className="mt-3 flex gap-2"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />I reviewed this text and approve this specific LinkedIn post.</label>
                <div className="mt-3 flex gap-2"><button type="button" className="btn btn-primary" disabled={publishing || published || !confirmed || !visibility || !text.trim()} onClick={() => void publish()}>{published ? "Published" : publishing ? "Publishing…" : "Publish to LinkedIn"}</button><button type="button" className="btn" onClick={() => void disconnect()}>Disconnect</button></div>
              </>}
          </div>
        </div>
        <div><p className="mb-2 text-sm font-medium">Instagram-ready card · 1080 × 1350 PNG</p><canvas ref={canvasRef} role="img" aria-label="Preview of the downloadable research card" className="w-full rounded-xl border border-line shadow-card" /><button type="button" className="btn mt-3" disabled={!text.trim() || !imageFits} onClick={download}><Download className="h-4 w-4" />Download image</button>{!imageFits ? <p className="mt-2 text-sm text-rose">Shorten the text or source citation to fit the image.</p> : null}<p className="mt-2 text-xs text-muted">Rendered in this browser; download and post it yourself. The image contains only the edited text and any citation you opted into.</p></div>
      </div>
      {status ? <p role="status" className="mt-4 rounded-xl bg-indigo-soft p-3 text-sm text-indigo-deep">{status}</p> : null}
    </section>
  </div>;
}
