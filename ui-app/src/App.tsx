import { useCallback, useEffect, useRef, useState } from "react"
import { ChevronRight, CornerDownLeft } from "lucide-react"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { TooltipProvider } from "@/components/ui/tooltip"
import { AppSidebar, type Section } from "@/components/layout/AppSidebar"
import { Header } from "@/components/layout/Header"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Panel, Empty } from "@/components/Panel"
import { TaskRow } from "@/components/TaskRow"
import { ChatThread } from "@/components/chat/ChatThread"
import { api, type State, type ChatTurn } from "@/lib/api"
import { getTheme, applyTheme } from "@/lib/theme"
import { cn } from "@/lib/utils"

const byStatus = (s: State | null, status: string) =>
  (s?.open ?? []).filter((t) => t.status === status)

export default function App() {
  const [s, setS] = useState<State | null>(null)
  const [section, setSection] = useState<Section>("chat")
  const [busy, setBusy] = useState(false)
  const [connected, setConnected] = useState(true)

  // chat overlay state — kept OUT of `s` so the poller can't erase it
  const [pending, setPending] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [chatError, setChatError] = useState<string | null>(null)

  // tasks say-bar
  const sayRef = useRef<HTMLInputElement>(null)
  const [sayResult, setSayResult] = useState<{ verb: string; output: string } | null>(null)

  useEffect(() => { applyTheme(getTheme()) }, [])

  const load = useCallback(async () => {
    try {
      setS(await api.state())
      setConnected(true)
    } catch {
      setConnected(false)   // keep last good state, show a reconnecting hint
    }
  }, [])
  useEffect(() => { load(); const t = setInterval(load, 20000); return () => clearInterval(t) }, [load])

  // ── chat: optimistic overlay reconciled by load(), never a stuck bubble ──
  const sendChat = async (text: string) => {
    setChatError(null)
    setPending(text)
    setSending(true)
    try {
      const r = await api.chat(text)
      if (r.ok && !r.isError) {
        await load()                    // server persisted both turns
        setPending(null)                // clear overlay only AFTER reconcile
      } else {
        setChatError(r.reply || "Something went wrong — not saved.")
        setPending(null)
      }
    } catch {
      setChatError("Couldn't reach nathanbot. Try again.")
      setPending(null)
    } finally {
      setSending(false)
    }
  }
  const clearChat = async () => {
    await api.clearChat(); setChatError(null); await load()
  }

  // ── tasks ──
  const say = async () => {
    const v = sayRef.current?.value.trim()
    if (!v) return
    sayRef.current!.value = ""
    setBusy(true); setSayResult({ verb: "…", output: "working…" })
    const r = await api.say(v)
    setSayResult({ verb: r.verb, output: r.output }); setBusy(false); load()
  }
  const run = async (cmd: string) => {
    setBusy(true); setSayResult({ verb: cmd, output: "running…" })
    const r = await api.run(cmd)
    setSayResult({ verb: cmd, output: r.output }); setBusy(false); load()
  }
  const op = async (id: string, status: string) => { await api.setStatus(id, status); load() }

  const decide = byStatus(s, "needs-decision")
  const ready = byStatus(s, "ready")
  const blocked = byStatus(s, "blocked")
  const inbox = s?.inbox ?? []
  const chat: ChatTurn[] = s?.chat ?? []

  return (
    <TooltipProvider delayDuration={0}>
      <SidebarProvider>
        <AppSidebar active={section} onNav={setSection} />
        <SidebarInset>
          <Header section={section} busy={busy || sending} />
          {!connected && (
            <div className="border-b bg-muted/50 px-4 py-1.5 text-center text-[12px] text-muted-foreground">
              reconnecting…
            </div>
          )}

          {section === "chat" && (
            <ChatThread turns={chat} pending={pending} sending={sending} error={chatError}
              onSend={sendChat} onClear={clearChat} />
          )}

          {section !== "chat" && (
            <main className="mx-auto w-full max-w-[1100px] px-5 py-6">
              {section === "tasks" && (
                <>
                  <div className="flex items-center rounded-xl border bg-card transition-colors focus-within:border-ring">
                    <ChevronRight className="ml-4 size-4 shrink-0 text-muted-foreground" />
                    <Input ref={sayRef} onKeyDown={(e) => e.key === "Enter" && say()}
                      placeholder="Capture a task, or type: status · next · brief · plan <goal>"
                      className="h-auto border-0 bg-transparent px-3 py-3 text-[15px] shadow-none focus-visible:ring-0" />
                    <Button variant="ghost" onClick={say} aria-label="Send"
                      className="h-full rounded-none rounded-r-xl border-l px-4">
                      <CornerDownLeft className="size-3.5" />
                    </Button>
                  </div>
                  {sayResult && (
                    <div className="mt-3 overflow-hidden rounded-xl border bg-card">
                      <div className="border-b px-4 py-2 text-[12px] font-medium text-muted-foreground">{sayResult.verb}</div>
                      <div className="max-h-[280px] overflow-auto px-4 py-3 text-[13px] leading-relaxed whitespace-pre-wrap">{sayResult.output}</div>
                    </div>
                  )}

                  <div className="mt-5 grid grid-cols-1 items-start gap-4 lg:grid-cols-[1.25fr_1fr]">
                    <div className="flex flex-col gap-4">
                      <Panel title="Waiting on you" count={decide.length}>
                        {decide.length ? decide.map((t) => (
                          <TaskRow key={t._file} task={t} onOp={op}
                            ops={[["approve", "ready"], ["defer", "blocked"], ["drop", "done"]]} />
                        )) : <Empty>Nothing needs you.</Empty>}
                      </Panel>
                      <Panel title="Ready" count={ready.length}>
                        {ready.length ? ready.map((t) => (
                          <TaskRow key={t._file} task={t} onOp={op} ops={[["done", "done"], ["block", "blocked"]]} />
                        )) : <Empty>Nothing ready. Capture something above.</Empty>}
                      </Panel>
                      <Panel title="Blocked" count={blocked.length}>
                        {blocked.length ? blocked.map((t) => (
                          <TaskRow key={t._file} task={t} onOp={op} ops={[["unblock", "ready"], ["drop", "done"]]} />
                        )) : <Empty>Nothing blocked.</Empty>}
                      </Panel>
                    </div>
                    <div className="flex flex-col gap-4">
                      <Panel title="Brief">
                        <div className="max-h-[400px] overflow-auto text-[13px] leading-relaxed whitespace-pre-wrap text-muted-foreground">{s?.brief ?? ""}</div>
                        <div className="mt-3 flex gap-2">
                          <Button size="sm" variant="outline" onClick={() => run("brief")}>refresh</Button>
                          <Button size="sm" variant="outline" onClick={() => run("triage")}>triage inbox</Button>
                        </div>
                      </Panel>
                      <Panel title="Inbox" count={inbox.length}>
                        {inbox.length ? inbox.map((x, i) => (
                          <p key={i} className="border-b py-2.5 text-[13px] last:border-b-0">{x}</p>
                        )) : <Empty>Empty. Capture above.</Empty>}
                      </Panel>
                    </div>
                  </div>
                </>
              )}

              {section === "memory" && (
                <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
                  <Panel title="Wiki" count={s?.wiki.length}>
                    <div className="flex flex-wrap gap-1.5 py-1">
                      {(s?.wiki ?? []).map((w) => (
                        <Badge key={w.slug} variant="secondary" className="text-[11px] font-normal">{w.slug}</Badge>
                      ))}
                    </div>
                    <p className="mt-3 text-[12px] text-muted-foreground/70">
                      Run <span className="font-medium text-muted-foreground">nb discuss</span> in a terminal to grow this by talking.
                    </p>
                  </Panel>
                  <Panel title="Recently done" count={s?.done.length}>
                    {(s?.done ?? []).slice(-14).reverse().map((t) => (
                      <div key={t._file} className="flex items-center justify-between gap-3 border-b py-2.5 last:border-b-0">
                        <span className="truncate text-[13px]">{t.title ?? t._file}</span>
                        <Badge variant="outline" className="shrink-0 text-[10px] font-normal">{t.project}</Badge>
                      </div>
                    ))}
                    {!(s?.done ?? []).length && <Empty>Nothing finished yet.</Empty>}
                  </Panel>
                </div>
              )}

              {section === "system" && (
                <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
                  <div className="flex flex-col gap-4">
                    <Panel title="Identities">
                      {Object.entries(s?.accounts ?? {}).sort((a, b) => (a[1].rank ?? 9) - (b[1].rank ?? 9)).map(([k, a]) => (
                        <div key={k} className="flex items-center justify-between gap-3 border-b py-2.5 last:border-b-0">
                          <span className="truncate text-[13px] text-muted-foreground">{a.email}</span>
                          <Badge variant={a.connected ? "default" : "outline"} className="shrink-0 text-[10px] font-normal">
                            {a.connected ? "authorized" : "not authorized"}
                          </Badge>
                        </div>
                      ))}
                    </Panel>
                    <Panel title="Maintenance">
                      <div className="flex flex-wrap gap-2 py-1">
                        {["audit", "groom", "tidy", "evolve"].map((c) => (
                          <Button key={c} size="sm" variant="outline" onClick={() => run(c)}>{c}</Button>
                        ))}
                      </div>
                      <p className="mt-3 text-[12px] leading-relaxed text-muted-foreground/70">
                        On its own: <span className="font-medium text-muted-foreground">brief</span> daily ·{" "}
                        <span className="font-medium text-muted-foreground">tidy + groom</span> Sundays ·{" "}
                        <span className="font-medium text-muted-foreground">evolve + learn</span> Mondays.
                        Nothing scheduled pushes, merges, or sends.
                      </p>
                    </Panel>
                  </div>
                  <Panel title="Permissions">
                    {Object.entries(s?.permissions ?? {})
                      .filter(([g]) => !g.startsWith("_"))
                      .map(([group, entries]) => (
                        <div key={group} className="border-b py-2.5 last:border-b-0">
                          <p className="mb-1.5 text-[12px] font-medium capitalize">{group}</p>
                          <div className="flex flex-col gap-1">
                            {Object.entries(entries)
                              .filter(([k, v]) => !k.startsWith("_") && v && typeof v === "object" && "level" in v)
                              .map(([k, v]) => (
                                <div key={k} className="flex items-center justify-between gap-3">
                                  <span className="text-[12px] text-muted-foreground">{k}</span>
                                  <Badge variant="outline" className={cn("shrink-0 text-[10px] font-normal",
                                    v.level === "always" && "border-status-ready/40 text-status-ready",
                                    v.level === "ask" && "border-status-attention/40 text-status-attention",
                                    v.level === "never" && "border-status-danger/40 text-status-danger")}>
                                    {v.level}
                                  </Badge>
                                </div>
                              ))}
                          </div>
                        </div>
                      ))}
                  </Panel>
                </div>
              )}
            </main>
          )}
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  )
}
