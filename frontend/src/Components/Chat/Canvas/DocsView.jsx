import { FileText, Sparkles } from 'lucide-react'

export function DocsView() {
  return (
    <div className="flex flex-col h-full items-center justify-center px-6 text-center gap-4">
      <div className="w-14 h-14 rounded-2xl bg-emerald-50 dark:bg-emerald-900/20 flex items-center justify-center">
        <FileText className="w-7 h-7 text-emerald-500 dark:text-emerald-400" />
      </div>
      <div>
        <h3 className="text-base font-semibold text-gray-800 dark:text-gray-100 mb-1">
          Docs Workspace
        </h3>
        <p className="text-sm text-gray-500 dark:text-gray-400 max-w-xs leading-relaxed">
          Generate structured documentation, summaries, and knowledge reports from your sources.
        </p>
      </div>
      <div className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-emerald-50 dark:bg-emerald-900/20 text-emerald-600 dark:text-emerald-400 text-xs font-medium border border-emerald-200 dark:border-emerald-800">
        <Sparkles className="w-3.5 h-3.5" />
        Coming soon
      </div>
    </div>
  )
}
