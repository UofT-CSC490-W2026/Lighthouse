import { Link, useNavigate } from "react-router-dom";
import type { User } from "@/lib/api";
import { apiFetch } from "@/lib/api";
import { clearApiToken } from "@/lib/auth";

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
    <nav className="border-b border-gray-200 bg-white">
      <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
        <div className="flex h-14 items-center justify-between">
          <Link to="/dashboard" className="text-lg font-semibold text-gray-900">
            Lighthouse
          </Link>

          {user ? (
            <div className="flex items-center gap-3">
              {user.avatar_url && (
                <img
                  src={user.avatar_url}
                  alt={user.github_login}
                  className="h-7 w-7 rounded-full"
                />
              )}
              <span className="text-sm text-gray-700">
                {user.github_login}
              </span>
              <button
                onClick={handleLogout}
                className="text-sm text-gray-500 hover:text-gray-700"
              >
                Sign out
              </button>
            </div>
          ) : (
            <Link
              to="/login"
              className="text-sm text-gray-600 hover:text-gray-900"
            >
              Sign in
            </Link>
          )}
        </div>
      </div>
    </nav>
  );
}
