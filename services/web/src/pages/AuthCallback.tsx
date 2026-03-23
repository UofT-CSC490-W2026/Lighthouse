import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { setApiToken } from "@/lib/auth";

export default function AuthCallback() {
  const navigate = useNavigate();

  useEffect(() => {
    const hash = window.location.hash.startsWith("#")
      ? window.location.hash.slice(1)
      : window.location.hash;
    const params = new URLSearchParams(hash);
    const token = params.get("token")?.trim();

    if (!token) {
      navigate("/login?error=missing_token", { replace: true });
      return;
    }

    setApiToken(token);
    navigate("/dashboard", { replace: true });
  }, [navigate]);

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="w-full max-w-sm rounded-lg border border-gray-200 bg-white p-6 text-center shadow-sm">
        <h1 className="text-lg font-semibold text-gray-900">Signing you in</h1>
        <p className="mt-2 text-sm text-gray-500">
          Finalizing Lighthouse authentication and loading your dashboard.
        </p>
      </div>
    </div>
  );
}
