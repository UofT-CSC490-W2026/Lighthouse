import { Navbar } from "@/components/Navbar";
import { AddRepoForm } from "@/components/AddRepoForm";
import { Card, CardContent } from "@/components/ui/card";
import { useUser } from "@/lib/hooks";

export default function AddRepo() {
  const { user, isLoading } = useUser();

  if (isLoading && !user) return null;

  return (
    <>
      <Navbar user={user} />
      <main className="mx-auto max-w-lg px-4 py-8 sm:px-6 lg:px-8 space-y-6">
        <div className="space-y-1">
          <h1 className="text-xl font-semibold text-foreground">Add Repository</h1>
          <p className="text-sm text-muted-foreground">
            Provide a GitHub repository URL to index. Lighthouse will resolve the
            default branch automatically and process the repository so your AI
            coding agent can search it for context.
          </p>
        </div>
        <Card>
          <CardContent className="p-6">
            <AddRepoForm />
          </CardContent>
        </Card>
      </main>
    </>
  );
}
