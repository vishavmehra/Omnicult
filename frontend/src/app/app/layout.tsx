import { AuthGate } from "@/components/auth/auth-gate";

export default function AppLayout({ children }: LayoutProps<"/app">) {
  return <AuthGate>{children}</AuthGate>;
}
