import { Navigate, useSearchParams } from "react-router-dom";
import { getApiToken } from "@/lib/auth";
import { LoginForm } from "@/components/login-form";
import lighthouseLoginImage from "@/assets/images/lighthouse-login.png";

const MCP_URL = import.meta.env.VITE_MCP_URL || "";

export default function Login() {
  const [params] = useSearchParams();
  const error = params.get("error");
  const apiToken = getApiToken();

  if (apiToken) {
    return <Navigate to="/dashboard" replace />;
  }

  const errorMessage =
    error === "missing_token"
      ? "Authentication completed, but no Lighthouse API token was returned."
      : error
        ? "Authentication failed. Please try again."
        : null;

  return (
    <div
      className="flex min-h-screen items-center justify-center bg-cover bg-center"
      style={{ backgroundImage: `url(${lighthouseLoginImage})` }}
    >
      <div className="w-full max-w-sm">
        <LoginForm
          githubAuthUrl={`${MCP_URL}/v1/auth/github`}
          errorMessage={errorMessage}
        />
      </div>
    </div>
  );
}
