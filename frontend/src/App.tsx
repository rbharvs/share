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
      <div className="min-h-full bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
        <header className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
            <div>
              <h1 className="text-xl font-semibold tracking-tight">share</h1>
              <p className="text-sm text-slate-500 dark:text-slate-400">
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
