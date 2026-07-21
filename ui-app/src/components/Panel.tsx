import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"

export function Panel({ title, count, children, className }: {
  title: string; count?: number; children: React.ReactNode; className?: string
}) {
  return (
    <Card className={cn("gap-0 overflow-hidden py-0", className)}>
      <div className="flex items-center gap-2.5 border-b px-4 py-3">
        <h2 className="text-[13px] font-semibold tracking-tight text-foreground">{title}</h2>
        {count !== undefined && count > 0 && (
          <span className="grid min-w-5 place-items-center rounded-full bg-muted px-1.5 font-mono text-[11px] tabular-nums text-muted-foreground">
            {count}
          </span>
        )}
      </div>
      <div className="px-4 py-1.5 pb-2.5">{children}</div>
    </Card>
  )
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="py-4 text-[13px] leading-relaxed text-muted-foreground/70">{children}</p>
}
