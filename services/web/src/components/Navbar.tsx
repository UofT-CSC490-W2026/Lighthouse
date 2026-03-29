import { Link, useNavigate } from "react-router-dom";
import { SiLighthouse } from "react-icons/si";
import type { User } from "@/lib/api";
import { apiFetch } from "@/lib/api";
import { clearApiToken } from "@/lib/auth";
import { Button } from "@/components/ui/button";

export function Navbar({ user }: { user: User | null }) {
  const navigate = useNavigate();

  async function handleLogout() {
    try {
      await apiFetch("/v1/auth/logout", { method: "POST" });
    } catch {
      /* ignore */
    }
    clearApiToken();
    navigate("/login", { replace: true });
  }

  return (
    <nav className="border-b border-border bg-background">
      <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
        <div className="flex h-14 items-center justify-between">
          <div className="flex items-center gap-6">
            <Link
              to="/dashboard"
              className="flex items-center text-foreground hover:text-primary transition-colors"
            >
              <SiLighthouse className="size-5" />
            </Link>
            {user ? (
              <div className="flex items-center gap-1">
                <Button variant="ghost" size="sm" asChild>
                  <Link to="/dashboard">Dashboard</Link>
                </Button>
                <Button variant="ghost" size="sm" asChild>
                  <Link to="/dashboard/search">Search</Link>
                </Button>
              </div>
            ) : null}
          </div>

          {user ? (
            <div className="flex items-center gap-3">
              {user.avatar_url && (
                <img
                  src={user.avatar_url}
                  alt={user.github_login}
                  className="h-7 w-7 rounded-full"
                />
              )}
              <span className="text-sm text-muted-foreground">
                {user.github_login}
              </span>
              <Button variant="ghost" size="sm" onClick={handleLogout}>
                Sign out
              </Button>
            </div>
          ) : (
            <Button variant="ghost" size="sm" asChild>
              <Link to="/login">Sign in</Link>
            </Button>
          )}
        </div>
      </div>
    </nav>
  );
}
