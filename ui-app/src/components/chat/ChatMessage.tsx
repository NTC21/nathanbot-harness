import { useState } from "react"
import { Check, Copy } from "lucide-react"
import { Button } from "@/components/ui/button"
import { MarkdownText } from "./MarkdownText"
import { cn } from "@/lib/utils"
import type { ChatTurn } from "@/lib/api"

export function ChatMessage({ turn }: { turn: ChatTurn }) {
  if (turn.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl bg-muted px-4 py-2.5 text-[15px] leading-relaxed wrap-break-word">
          {turn.text}
        </div>
      </div>
    )
  }
  if (turn.error) {
    return (
      <div className="rounded-lg border border-status-danger/40 bg-status-danger/5 px-3.5 py-2.5 text-[14px] text-status-danger">
        {turn.text}
      </div>
    )
  }
  return <AssistantMessage text={turn.text} />
}

function AssistantMessage({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <div className="group">
      <MarkdownText text={text} />
      <div className="mt-1 flex h-6 items-center opacity-0 transition-opacity group-hover:opacity-100">
        <Button variant="ghost" size="icon" onClick={copy} className="size-6 text-muted-foreground"
          aria-label="Copy">
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
        </Button>
      </div>
    </div>
  )
}

export function WorkingIndicator() {
  return (
    <span className={cn("inline-block animate-pulse text-[15px] text-muted-foreground")}
      aria-label="nathanbot is working">●</span>
  )
}
