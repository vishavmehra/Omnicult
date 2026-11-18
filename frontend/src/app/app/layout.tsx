import { AuthGate } from "@/components/auth/auth-gate";
import { CommandBarProvider } from "@/features/desk/command-bar";

// The Command Bar (Ctrl or Cmd+K) is mounted once here so it works on every /app page.
export default function AppLayout({ children }: LayoutProps<"/app">) {
  return (
    <AuthGate>
      <CommandBarProvider>{children}</CommandBarProvider>
    </AuthGate>
  );
}
