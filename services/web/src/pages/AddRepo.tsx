import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiFetch, type User } from "@/lib/api";
import { clearApiToken, getApiToken } from "@/lib/auth";
import { Navbar } from "@/components/Navbar";
import { AddRepoForm } from "@/components/AddRepoForm";

export default function AddRepo() {
  const navigate = useNavigate();
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    if (!getApiToken()) {
      navigate("/login", { replace: true });
      return;
    }

    apiFetch<User>("/v1/auth/me")
      .then(setUser)
      .catch(() => {
        clearApiToken();
        navigate("/login", { replace: true });
      });
  }, [navigate]);

  if (!user) return null;

  return (
    <>
      <Navbar user={user} />
      <main className="mx-auto max-w-lg px-4 py-8 sm:px-6 lg:px-8 space-y-6">
        <h1 className="text-xl font-semibold text-gray-900">Add Repository</h1>
        <p className="text-sm text-gray-500">
          Provide a GitHub repository URL to index. Lighthouse will resolve the
          default branch automatically and process the repository so your AI
          coding agent can search it for context.
        </p>
        <AddRepoForm />
      </main>
    </>
  );
}
