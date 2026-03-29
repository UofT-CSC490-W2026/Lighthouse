import { Link } from "react-router-dom";
import { MCPTokenPanel } from "@/components/MCPTokenPanel";
import { Navbar } from "@/components/Navbar";
import { RepoList } from "@/components/RepoList";
import { Button } from "@/components/ui/button";
import { useUser } from "@/lib/hooks";

export default function Dashboard() {
  const { user, isLoading } = useUser();

  if (isLoading && !user) return null;

  return (
    <>
      <Navbar user={user} />
      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="space-y-6">
          <MCPTokenPanel />
          <div className="flex items-center justify-between">
            <h1 className="text-xl font-semibold text-foreground">Repositories</h1>
            <div className="flex items-center gap-3">
              <Button variant="outline" size="sm" asChild>
                <Link to="/dashboard/search">Search Indexed Code</Link>
              </Button>
              <Button size="sm" asChild>
                <Link to="/dashboard/add-repo">+ Add Repository</Link>
              </Button>
            </div>
          </div>
          <RepoList />
        </div>
      </main>
    </>
  );
}
