import { useEffect, useRef } from "react"
import { Button } from "@/components/ui/button"
import { ChatMessage, WorkingIndicator } from "./ChatMessage"
import { ChatComposer } from "./ChatComposer"
import type { ChatTurn } from "@/lib/api"

const SUGGESTIONS = [
  "What should I work on today?",
  "What's in my inbox?",
  "Draft a plan to ship a new feature",
]

export function ChatThread({ turns, pending, sending, error, onSend, onClear }: {
  turns: ChatTurn[]
  pending: string | null
  sending: boolean
  error: string | null
  onSend: (text: string) => void
  onClear: () => void
}) {
  const endRef = useRef<HTMLDivElement>(null)
  const isEmpty = turns.length === 0 && !pending && !error

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [turns.length, pending, sending, error])

  if (isEmpty) {
    return (
      <div className="mx-auto flex h-[calc(100vh-8rem)] w-full max-w-[44rem] flex-col justify-center px-4">
        <h1 className="mb-6 text-center text-2xl font-semibold">How can I help you today?</h1>
        <ChatComposer onSend={onSend} disabled={sending} />
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          {SUGGESTIONS.map((s) => (
            <Button key={s} variant="ghost" onClick={() => onSend(s)}
              className="h-auto rounded-full border border-border/60 px-3.5 py-1.5 text-[13px] font-normal text-muted-foreground hover:text-foreground">
              {s}
            </Button>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto flex h-[calc(100vh-4rem)] w-full max-w-[44rem] flex-col px-4">
      <div className="flex flex-1 flex-col gap-6 overflow-y-auto py-6">
        {turns.map((t, i) => <ChatMessage key={i} turn={t} />)}
        {pending && <ChatMessage turn={{ role: "user", text: pending }} />}
        {sending && <WorkingIndicator />}
        {error && <ChatMessage turn={{ role: "nathanbot", text: error, error: true }} />}
        <div ref={endRef} />
      </div>
      <div className="sticky bottom-0 bg-background pb-4">
        <ChatComposer onSend={onSend} disabled={sending} />
        <div className="mt-2 flex items-center justify-between px-1 text-[11px] text-muted-foreground/70">
          <span>Never sends email or creates events without approval.</span>
          {turns.length > 0 && (
            <button onClick={onClear} className="hover:text-foreground">clear</button>
          )}
        </div>
      </div>
    </div>
  )
}
