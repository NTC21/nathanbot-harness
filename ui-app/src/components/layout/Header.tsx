import { Info } from "lucide-react"
import { Separator } from "@/components/ui/separator"
import { SidebarTrigger } from "@/components/ui/sidebar"
import {
  Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger,
} from "@/components/ui/sheet"
import { Button } from "@/components/ui/button"
import { ThemeToggle } from "@/components/ThemeToggle"

const titles: Record<string, string> = {
  chat: "Chat", tasks: "Tasks", memory: "Memory", system: "System",
}

export function Header({ section, busy }: { section: string; busy: boolean }) {
  return (
    <header className="sticky top-0 z-40 flex h-14 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur-md">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="h-5" />
      <h1 className="text-[15px] font-semibold tracking-tight">{titles[section] ?? "Chat"}</h1>
      <span className="flex-1" />
      {busy && (
        <span className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
          <span className="size-1.5 animate-pulse rounded-full bg-foreground" />
          working
        </span>
      )}
      <ThemeToggle />
      <Sheet>
        <SheetTrigger asChild>
          <Button variant="ghost" size="icon" className="size-8" aria-label="About">
            <Info className="size-4" />
          </Button>
        </SheetTrigger>
        <SheetContent className="gap-0">
          <SheetHeader>
            <SheetTitle>nathanbot</SheetTitle>
            <SheetDescription>Your personal AI system — one place to plan, capture, and act.</SheetDescription>
          </SheetHeader>
          <div className="flex flex-col gap-4 px-4 pb-4 text-[13px] leading-relaxed">
            <div>
              <p className="mb-1 font-medium">The loop</p>
              <p className="text-muted-foreground">Capture an idea → it's filed as a task → you approve/defer/drop → it runs → your decisions teach it what you value.</p>
            </div>
            <div>
              <p className="mb-1 font-medium">Chat vs Tasks</p>
              <p className="text-muted-foreground"><b>Chat</b> is a full-context conversation. <b>Tasks</b> is where you capture and triage work. It never sends email or creates events without your approval.</p>
            </div>
            <div>
              <p className="mb-1 font-medium">On its own</p>
              <p className="text-muted-foreground">Briefs daily, tidies weekly, and proposes improvements — but nothing scheduled pushes, merges, or sends.</p>
            </div>
          </div>
        </SheetContent>
      </Sheet>
    </header>
  )
}
