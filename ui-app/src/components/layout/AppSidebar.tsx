import { MessageSquare, ListTodo, Brain, Sliders } from "lucide-react"
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupLabel,
  SidebarHeader, SidebarMenu, SidebarMenuButton, SidebarMenuItem, SidebarRail,
} from "@/components/ui/sidebar"

export type Section = "chat" | "tasks" | "memory" | "system"

const nav: { id: Section; label: string; icon: typeof MessageSquare }[] = [
  { id: "chat",   label: "Chat",   icon: MessageSquare },
  { id: "tasks",  label: "Tasks",  icon: ListTodo },
  { id: "memory", label: "Memory", icon: Brain },
  { id: "system", label: "System", icon: Sliders },
]

export function AppSidebar({ active, onNav }: { active: Section; onNav: (s: Section) => void }) {
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <div className="flex items-center gap-2.5 px-2 py-1.5">
          <div className="grid size-8 shrink-0 place-items-center rounded-lg bg-primary text-primary-foreground text-[13px] font-semibold">
            n
          </div>
          <div className="grid flex-1 leading-tight group-data-[collapsible=icon]:hidden">
            <span className="text-sm font-semibold tracking-tight">nathanbot</span>
            <span className="text-[11px] text-muted-foreground">personal AI system</span>
          </div>
        </div>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Workspace</SidebarGroupLabel>
          <SidebarMenu>
            {nav.map((n) => (
              <SidebarMenuItem key={n.id}>
                <SidebarMenuButton isActive={active === n.id} onClick={() => onNav(n.id)} tooltip={n.label}>
                  <n.icon />
                  <span>{n.label}</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            ))}
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        {/* Personalize: set your name + primary identity here (or wire to config/accounts.json). */}
        <div className="flex items-center gap-2 px-2 py-1.5 group-data-[collapsible=icon]:hidden">
          <div className="grid size-7 shrink-0 place-items-center rounded-full bg-muted text-[11px] font-semibold">n</div>
          <div className="grid flex-1 leading-tight">
            <span className="truncate text-[12px] font-medium">Owner</span>
            <span className="truncate text-[11px] text-muted-foreground">you@example.com</span>
          </div>
        </div>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
