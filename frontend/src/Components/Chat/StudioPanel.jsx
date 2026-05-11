import { LayoutDashboard, Network, Share2, Layers, BookOpen, PanelRightClose } from 'lucide-react'

function StudioPanel({ onCollapse }) {
  const tools = [
    { name: 'Graph Explore', icon: Network, color: 'text-blue-500 dark:text-blue-400', bg: 'bg-[#2a2a2a]' },
    { name: 'Knowledge Map', icon: Share2, color: 'text-green-500 dark:text-green-400', bg: 'bg-[#2a2a2a]' },
    { name: 'Document Summary', icon: BookOpen, color: 'text-yellow-500 dark:text-yellow-400', bg: 'bg-[#2a2a2a]' },
    { name: 'Entity Layers', icon: Layers, color: 'text-purple-500 dark:text-purple-400', bg: 'bg-[#2a2a2a]' },
  ]

  return (
    <div className="flex flex-col h-full bg-white dark:bg-[#1e1e1e] text-gray-900 dark:text-gray-200 border-l border-gray-200 dark:border-gray-800">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-800">
        <h2 className="text-sm font-semibold flex items-center gap-2">
          <LayoutDashboard className="w-4 h-4 text-gray-700 dark:text-gray-400" />
          Studio
        </h2>
        <button 
          onClick={onCollapse}
          className="text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-white p-1 rounded-md hover:bg-gray-100 dark:hover:bg-[#2a2a2a] transition-colors"
          title="Close Studio"
        >
          <PanelRightClose className="w-4 h-4" />
        </button>
      </div>

      <div className="p-4 overflow-y-auto">
        <div className="bg-linear-to-r from-gray-50 to-gray-100 dark:from-[#212121] dark:to-[#2a2a2a] rounded-xl p-4 border border-gray-200 dark:border-gray-800 mb-6">
          <p className="text-sm text-gray-600 dark:text-gray-300">
            Welcome to Graph Studio. Explore your connected knowledge across documents and repositories.
          </p>
        </div>

        <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-500 uppercase tracking-wider mb-3">
          Available Tools
        </h3>

        <div className="grid grid-cols-2 gap-3">
          {tools.map((tool) => (
            <button 
              key={tool.name}
              className={`bg-white dark:${tool.bg} hover:bg-gray-50 dark:hover:bg-[#333] border border-gray-200 dark:border-gray-700/50 shadow-sm dark:shadow-none rounded-xl p-3 flex flex-col gap-2 items-start transition-colors`}
            >
              <tool.icon className={`w-5 h-5 ${tool.color}`} />
              <span className="text-xs font-medium text-left">{tool.name}</span>
            </button>
          ))}
        </div>

        <div className="mt-8 text-center px-4">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-blue-50 dark:bg-[#2a2a2a] text-blue-500 dark:text-blue-400 mb-3">
            <Network className="w-6 h-6" />
          </div>
          <h4 className="text-sm font-medium text-gray-900 dark:text-white mb-1">Graph outputs will appear here</h4>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Use the chat to ask questions that require exploring relationships.
          </p>
        </div>
      </div>
    </div>
  )
}

export default StudioPanel
