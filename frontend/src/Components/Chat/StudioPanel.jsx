import { useState } from 'react'
import { LayoutTemplate, ChevronRight, PanelRightClose } from 'lucide-react'
import { useChatStore } from '@/store'
import { CanvasHome } from './Canvas/CanvasHome'
import { GraphView } from './Canvas/GraphView'
import { DocsView } from './Canvas/DocsView'

const TOOL_LABELS = {
  graph: 'Graph View',
  docs: 'Docs',
}

function CanvasPanel({ onCollapse, currentSession }) {
  const [activeTool, setActiveTool] = useState(null) // null = home
  const { graphData, subgraphMode, setSubgraphMode } = useChatStore()

  // Disable sync mode whenever the user leaves Graph View
  const handleBack = () => {
    if (activeTool === 'graph') setSubgraphMode(false)
    setActiveTool(null)
  }

  const handleSelectTool = (toolId) => {
    if (activeTool === 'graph' && toolId !== 'graph') setSubgraphMode(false)
    setActiveTool(toolId)
  }

  const handleCollapse = () => {
    setSubgraphMode(false)
    onCollapse()
  }

  return (
    <div className="flex flex-col h-full bg-white dark:bg-[#1e1e1e] text-gray-900 dark:text-gray-200 border-l border-gray-200 dark:border-gray-800">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-800 shrink-0">
        {/* Breadcrumb */}
        <nav className="flex items-center gap-1 text-sm font-medium min-w-0">
          <button
            onClick={handleBack}
            className={`flex items-center gap-1.5 transition-colors ${
              activeTool
                ? 'text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-100'
                : 'text-gray-800 dark:text-gray-100 cursor-default'
            }`}
          >
            <LayoutTemplate className="w-4 h-4 shrink-0" />
            <span>Canvas</span>
          </button>

          {activeTool && (
            <>
              <ChevronRight className="w-3.5 h-3.5 text-gray-400 dark:text-gray-600 shrink-0" />
              <span className="text-gray-800 dark:text-gray-100 truncate">
                {TOOL_LABELS[activeTool]}
              </span>
            </>
          )}
        </nav>

        <button
          onClick={handleCollapse}
          className="shrink-0 ml-2 text-gray-400 hover:text-gray-700 dark:text-gray-500 dark:hover:text-gray-200 p-1 rounded-md hover:bg-gray-100 dark:hover:bg-[#2a2a2a] transition-colors"
          title="Close Canvas"
        >
          <PanelRightClose className="w-4 h-4" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {activeTool === null && (
          <CanvasHome onSelectTool={handleSelectTool} />
        )}
        {activeTool === 'graph' && (
          <GraphView
            currentSession={currentSession}
            graphData={graphData}
            syncMode={subgraphMode}
            onSetSyncMode={setSubgraphMode}
          />
        )}
        {activeTool === 'docs' && (
          <DocsView />
        )}
      </div>
    </div>
  )
}

export default CanvasPanel
