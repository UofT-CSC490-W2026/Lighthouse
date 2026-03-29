import useSWR from "swr";
import { apiFetch, type User } from "@/lib/api";
import { clearApiToken, getApiToken } from "@/lib/auth";
import { useNavigate } from "react-router-dom";
import { useEffect } from "react";

export function useUser() {
  const navigate = useNavigate();

  const { data: user, error, isLoading } = useSWR<User>(
    getApiToken() ? "/v1/auth/me" : null,
    () => apiFetch<User>("/v1/auth/me"),
    { revalidateOnFocus: false }
  );

  useEffect(() => {
    if (!getApiToken()) {
      navigate("/login", { replace: true });
      return;
    }
    if (error) {
      clearApiToken();
      navigate("/login", { replace: true });
    }
  }, [error, navigate]);

  return { user: user ?? null, isLoading };
}
