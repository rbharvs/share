import { ContentLibrary } from "@/components/ContentLibrary";

export default function App() {
  return (
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
      <main className="mx-auto max-w-6xl px-6 py-8">
        <ContentLibrary />
      </main>
    </div>
  );
}
