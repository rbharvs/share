import { ContentLibrary } from "@/components/ContentLibrary";
import { UploadDropzone } from "@/components/UploadDropzone";
import { ToastProvider } from "@/components/ui/toast";
import { useLibrary } from "@/hooks/useLibrary";

function Dashboard() {
  const library = useLibrary();
  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-8 px-6 py-8">
      <UploadDropzone onUploaded={library.prepend} />
      <ContentLibrary library={library} />
    </main>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <div className="min-h-full bg-retro-bg text-retro-ink">
        <header className="border-b border-retro-line bg-retro-surface">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
            <div className="flex items-baseline gap-3">
              <h1 className="font-mono text-xl font-bold uppercase tracking-[0.3em] text-retro-ink">
                share
              </h1>
              <p className="text-sm text-retro-muted">
                Personal sharing dashboard
              </p>
            </div>
          </div>
        </header>
        <Dashboard />
      </div>
    </ToastProvider>
  );
}
