import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { Task } from "@/lib/api"

const dot: Record<string, string> = {
  ready: "bg-status-ready", blocked: "bg-status-blocked", "needs-decision": "bg-status-attention",
}
const priLabel: Record<string, string> = { "1": "now", "2": "soon", "3": "next", "4": "later", "5": "someday" }

export function TaskRow({ task, ops, onOp }: {
  task: Task
  ops: [string, string][]
  onOp: (id: string, status: string) => void
}) {
  return (
    <div className="group flex items-start gap-3.5 border-b py-3.5 last:border-b-0">
      <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", dot[task.status ?? ""] ?? "bg-muted-foreground")} />
      <div className="min-w-0 flex-1">
        <p className="text-[15px] leading-snug text-foreground">{task.title ?? task._file}</p>
        <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12px] text-muted-foreground">
          <span className="rounded bg-muted px-1.5 py-0.5 text-[11px]">{task.project ?? "no project"}</span>
          {task.priority && <span>{priLabel[task.priority] ?? `P${task.priority}`}</span>}
        </p>
      </div>
      <div className="flex shrink-0 gap-1.5 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
        {ops.map(([label, status]) => (
          <Button key={label} size="sm" variant="outline"
            className="h-7 px-2.5 text-[12px]"
            onClick={() => task.id && onOp(task.id, status)}>
            {label}
          </Button>
        ))}
      </div>
    </div>
  )
}
