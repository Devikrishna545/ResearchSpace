import Image from "next/image";
import { cn } from "@/lib/utils";

export function BrandMark({ className, size = 36 }: { className?: string; size?: number }) {
  return <Image src="/brand/tile-192.png" alt="" aria-hidden="true" width={size} height={size}
    className={cn("shrink-0", className)} />;
}

function BrandName() {
  return <span>R<span className="text-indigo-deep">.</span>Space</span>;
}

export function BrandWordmark({ className }: { className?: string }) {
  return <span className={cn("inline-flex items-center gap-2.5 whitespace-nowrap font-serif font-semibold tracking-tight text-ink", className)}>
    <BrandMark className="h-9 w-9" /><BrandName />
  </span>;
}

export function BrandAuth() {
  return <div className="flex flex-col items-center gap-3">
    <BrandMark size={112} className="h-24 w-24 sm:h-28 sm:w-28" />
    <span className="font-serif text-4xl font-semibold tracking-tight text-ink"><BrandName /></span>
  </div>;
}
