import { WORKSPACES, type WorkspaceKey } from "@/components/shell/workspaces";
import { cn } from "@/lib/utils";

/**
 * RoleMark: a workspace's clay tile in its colour role with its icon, the same mark the workspace header, the spine
 * station, Today's lists and the Command Bar use. Decorative (aria-hidden): always put the workspace name beside it.
 *
 *   <RoleMark workspace="lens" size="sm" />
 */
const SIZE = { xs: "size-6 rounded-md [&>svg]:size-3.5", sm: "size-8 rounded-lg [&>svg]:size-4", md: "size-11 rounded-card [&>svg]:size-5" };

export function RoleMark({ workspace, size = "sm", className }: { workspace: WorkspaceKey; size?: keyof typeof SIZE; className?: string }) {
  const { Icon } = WORKSPACES[workspace];
  return (
    <span aria-hidden className={cn("grid shrink-0 place-items-center text-[#2b2233] shadow-clay", SIZE[size], className)} style={{ backgroundColor: `var(--role-${workspace})` }}>
      <Icon />
    </span>
  );
}
