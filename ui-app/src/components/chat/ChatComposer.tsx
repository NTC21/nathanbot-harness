import { useRef } from "react"
import { ArrowUp } from "lucide-react"
import { Button } from "@/components/ui/button"

export function ChatComposer({ onSend, disabled }: {
  onSend: (text: string) => void
  disabled?: boolean
}) {
  const ref = useRef<HTMLTextAreaElement>(null)

  const grow = () => {
    const el = ref.current
    if (!el) return
    el.style.height = "auto"
    el.style.height = Math.min(el.scrollHeight, 160) + "px"
  }
  const send = () => {
    const v = ref.current?.value.trim()
    if (!v) return
    onSend(v)
    if (ref.current) { ref.current.value = ""; ref.current.style.height = "auto" }
  }
  return (
    <div className="flex items-end gap-2 rounded-[1.5rem] border bg-card p-2 shadow-sm transition-colors focus-within:border-ring">
      <textarea ref={ref} rows={1} autoFocus onInput={grow}
        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send() } }}
        placeholder="Message nathanbot…"
        className="max-h-40 min-h-10 flex-1 resize-none bg-transparent px-3 py-2 text-[15px] outline-none placeholder:text-muted-foreground" />
      <Button size="icon" onClick={send} disabled={disabled}
        className="size-9 shrink-0 rounded-full" aria-label="Send">
        <ArrowUp className="size-4.5" />
      </Button>
    </div>
  )
}
