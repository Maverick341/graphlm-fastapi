import { Network, FileText, ChevronRight, Info } from 'lucide-react'

const tools = [
  {
    id: 'graph',
    name: 'Graph View',
    description: 'Explore knowledge as an interactive network',
    icon: Network,
    iconColor: 'text-blue-400',
    iconBg: 'bg-blue-500/10 dark:bg-blue-500/20',
    available: true,
  },
  {
    id: 'docs',
    name: 'Docs',
    description: 'Generate structured documentation from sources',
    icon: FileText,
    iconColor: 'text-emerald-400',
    iconBg: 'bg-emerald-500/10 dark:bg-emerald-500/20',
    available: false, // coming soon
  },
]

export function CanvasHome({ onSelectTool, selectedSources = [] }) {
  const hasSelection = selectedSources.length > 0

  return (
    <div className="flex flex-col gap-3 p-4">
      {/* Info banner — shown when nothing is selected */}
      {!hasSelection && (
        <div className="flex items-start gap-2 px-3 py-2.5 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700/40 mb-1">
          <Info className="w-3.5 h-3.5 text-amber-500 dark:text-amber-400 shrink-0 mt-0.5" />
          <p className="text-xs text-amber-700 dark:text-amber-300 leading-snug">
            Select at least one source from the left panel to enable Canvas tools.
          </p>
        </div>
      )}

      <p className="text-xs text-gray-500 dark:text-gray-400 font-medium uppercase tracking-wider mb-1">
        Tools
      </p>
      {tools.map((tool) => {
        // A tool is interactive only if it's built and sources are selected
        const isActive = tool.available && hasSelection
        const isDisabled = !tool.available || !hasSelection
        const disabledReason = !hasSelection
          ? 'Select sources to enable'
          : 'Coming soon'

        return (
          <button
            key={tool.id}
            onClick={() => isActive && onSelectTool(tool.id)}
            disabled={isDisabled}
            title={isDisabled ? disabledReason : ''}
            className={`
              group relative w-full flex items-center gap-3 p-3.5 rounded-xl border text-left transition-all duration-150
              ${isActive
                ? 'bg-gray-50 dark:bg-[#2a2a2a] border-gray-200 dark:border-gray-700/60 hover:bg-white dark:hover:bg-[#333] hover:border-blue-300 dark:hover:border-blue-700/60 hover:shadow-sm cursor-pointer'
                : 'bg-gray-50/50 dark:bg-[#242424] border-gray-200/60 dark:border-gray-800/60 cursor-not-allowed opacity-50'
              }
            `}
          >
            <div className={`shrink-0 w-9 h-9 rounded-lg flex items-center justify-center ${tool.iconBg}`}>
              <tool.icon className={`w-5 h-5 ${tool.iconColor}`} />
            </div>

            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
                  {tool.name}
                </span>
                {!tool.available && (
                  <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400 uppercase tracking-wide">
                    Soon
                  </span>
                )}
                {tool.available && !hasSelection && (
                  <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-amber-100 dark:bg-amber-900/40 text-amber-600 dark:text-amber-400 uppercase tracking-wide">
                    Select sources
                  </span>
                )}
              </div>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 truncate">
                {tool.description}
              </p>
            </div>

            {isActive && (
              <ChevronRight className="shrink-0 w-4 h-4 text-gray-400 dark:text-gray-500 group-hover:text-gray-600 dark:group-hover:text-gray-300 transition-colors" />
            )}
          </button>
        )
      })}
    </div>
  )
}
