"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function PanelHeader({ eyebrow, title, text, actions }: { eyebrow: string; title: string; text: string; actions?: ReactNode }) {
  return <header className="flex flex-wrap items-end justify-between gap-4">
    <div className="min-w-0 flex-1"><p className="eyebrow mb-2">{eyebrow}</p><h2 className="break-words font-serif text-3xl tracking-tight md:text-4xl">{title}</h2><p className="mt-2 max-w-3xl text-sm leading-6 text-muted">{text}</p></div>
    {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
  </header>;
}

export function EmptyInset({ title, text }: { title: string; text: string }) {
  return <div className="rounded-3xl border border-dashed border-line bg-paper p-10 text-center"><h3 className="font-serif text-2xl">{title}</h3><p className="mt-2 text-muted">{text}</p></div>;
}

/**
 * Consistent module layout: a primary work area plus a right-hand context rail.
 * The rail sits beside the main column on wide screens and stacks on smaller ones.
 * `asideTrailing` ends the rail on wide screens but follows the main content on small
 * screens, so optional context (space memory) never pushes the primary work down.
 */
export function ModuleLayout({ header, main, aside, asideTrailing, footer, asideFirstOnMobile = false }: { header: ReactNode; main: ReactNode; aside?: ReactNode; asideTrailing?: ReactNode; footer?: ReactNode; asideFirstOnMobile?: boolean }) {
  const hasAside = Boolean(aside || asideTrailing);
  const trailingAfterMain = asideFirstOnMobile && asideTrailing;
  return <section className="module-layout min-w-0 space-y-5">
    {header}
    <div className={cn("module-columns grid min-w-0 gap-5", hasAside && "module-with-aside")}>
      <div className={cn("module-primary min-w-0 space-y-5", asideFirstOnMobile && "module-mobile-secondary")}>
        {main}
        {trailingAfterMain ? <div className="module-mobile-trailing space-y-4">{asideTrailing}</div> : null}
      </div>
      {hasAside ? <aside aria-label="Module tools" className={cn("module-tools min-w-0 space-y-4", asideFirstOnMobile && "module-mobile-primary")}>
        {aside}
        {asideTrailing ? <div className={cn("space-y-4", trailingAfterMain && "module-desktop-trailing")}>{asideTrailing}</div> : null}
      </aside> : null}
    </div>
    {footer}
  </section>;
}

export function RailCard({ title, icon, actions, children, className }: { title: string; icon?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={cn("panel min-w-0 p-4", className)}>
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><h3 className="flex min-w-0 items-center gap-2 font-serif text-xl">{icon}{title}</h3>{actions ? <div className="flex items-center gap-1">{actions}</div> : null}</div>
    {children}
  </section>;
}

export function SelectAllToggle({ checked, indeterminate, disabled, onToggle, label = "Select all" }: { checked: boolean; indeterminate?: boolean; disabled?: boolean; onToggle: () => void; label?: string }) {
  return <label className={cn("inline-flex cursor-pointer select-none items-center gap-2 text-sm text-muted", disabled && "cursor-not-allowed opacity-50")}>
    <input type="checkbox" className="h-4 w-4" checked={checked} disabled={disabled}
      ref={(element) => { if (element) element.indeterminate = Boolean(indeterminate) && !checked; }}
      onChange={onToggle} />
    {checked ? "Deselect all" : label}
  </label>;
}
