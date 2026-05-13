import { useEffect, useRef, useState } from 'react'
import { Network as NetworkIcon, Search, Loader2, Maximize2, Minimize2, RefreshCw, X } from 'lucide-react'
import { Network, DataSet } from 'vis-network/standalone'
import chatSessionService from '@/api/chatSessionService'

// Color palette per node label
const LABEL_COLORS = {
  default:  { background: '#3b82f6', border: '#1d4ed8', font: '#ffffff' },
  Person:   { background: '#8b5cf6', border: '#6d28d9', font: '#ffffff' },
  Concept:  { background: '#10b981', border: '#047857', font: '#ffffff' },
  File:     { background: '#f59e0b', border: '#b45309', font: '#ffffff' },
  Function: { background: '#ef4444', border: '#b91c1c', font: '#ffffff' },
  Class:    { background: '#06b6d4', border: '#0e7490', font: '#ffffff' },
  Module:   { background: '#ec4899', border: '#be185d', font: '#ffffff' },
}

function getLabelColor(label) {
  return LABEL_COLORS[label] || LABEL_COLORS.default
}

function buildVisData(graphData) {
  if (!graphData?.nodes?.length) return { nodes: new DataSet([]), edges: new DataSet([]) }

  const nodeItems = graphData.nodes.map((n) => {
    const color = getLabelColor(n.label)
    const name = n.properties?.name || n.properties?.title || n.label
    return {
      id: n.id,
      label: name.length > 25 ? name.slice(0, 24) + '…' : name,
      title: `<b>${n.label}</b><br/>${Object.entries(n.properties || {}).slice(0, 4).map(([k, v]) => `${k}: ${v}`).join('<br/>')}`,
      color: { background: color.background, border: color.border, highlight: { background: color.border, border: color.background } },
      font: { color: color.font, size: 12 },
      borderWidth: 1.5,
      shape: 'box',
      margin: 6,
    }
  })

  const edgeItems = graphData.edges.map((e, i) => ({
    id: `edge-${i}`,
    from: e.source,
    to: e.target,
    label: e.type || e.relationship_type || '',
    font: { size: 10, align: 'middle', color: '#9ca3af', strokeWidth: 0 },
    color: { color: '#6b7280', highlight: '#3b82f6' },
    arrows: { to: { enabled: true, scaleFactor: 0.6 } },
    smooth: { type: 'cubicBezier', roundness: 0.3 },
  }))

  return { nodes: new DataSet(nodeItems), edges: new DataSet(edgeItems) }
}

const VIS_OPTIONS = {
  physics: {
    enabled: true,
    solver: 'forceAtlas2Based',
    forceAtlas2Based: { gravitationalConstant: -50, springLength: 100 },
    stabilization: { iterations: 150 },
  },
  interaction: { hover: true, tooltipDelay: 150, navigationButtons: false },
  layout: { randomSeed: 42 },
}

export function GraphView({ currentSession, graphData, syncMode, onSetSyncMode }) {
  const containerRef = useRef(null)
  const networkRef = useRef(null)
  const [query, setQuery] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [isEmpty, setIsEmpty] = useState(true)
  const [nodeCount, setNodeCount] = useState(0)
  const [edgeCount, setEdgeCount] = useState(0)
  const [errorMsg, setErrorMsg] = useState('')
  const mode = syncMode ? 'sync' : 'explore'

  // Render/update graph when graphData changes
  useEffect(() => {
    if (!containerRef.current || !graphData) return
    setErrorMsg('')

    const { nodes, edges } = buildVisData(graphData)
    setNodeCount(nodes.length)
    setEdgeCount(edges.length)
    setIsEmpty(nodes.length === 0)

    if (networkRef.current) {
      networkRef.current.setData({ nodes, edges })
    } else {
      networkRef.current = new Network(containerRef.current, { nodes, edges }, VIS_OPTIONS)
    }
  }, [graphData])

  // Load full graph on mount in explore mode if no graphData yet
  useEffect(() => {
    if (!currentSession || graphData) return
    handleLoadFullGraph()
  }, [currentSession?.id])

  const handleLoadFullGraph = async () => {
    if (!currentSession) return
    setIsLoading(true)
    setErrorMsg('')
    try {
      const res = await chatSessionService.getFullGraph(currentSession.id)
      const data = res.data
      if (!data?.nodes?.length) {
        setIsEmpty(true)
      } else {
        const { nodes, edges } = buildVisData(data)
        setNodeCount(nodes.length)
        setEdgeCount(edges.length)
        setIsEmpty(nodes.length === 0)
        if (networkRef.current) {
          networkRef.current.setData({ nodes, edges })
        } else if (containerRef.current) {
          networkRef.current = new Network(containerRef.current, { nodes, edges }, VIS_OPTIONS)
        }
      }
    } catch (err) {
      setErrorMsg('Failed to load graph. Make sure sources are indexed.')
    } finally {
      setIsLoading(false)
    }
  }

  const handleExploreQuery = async (e) => {
    e.preventDefault()
    if (!query.trim() || !currentSession) return
    setIsLoading(true)
    setErrorMsg('')
    try {
      const res = await chatSessionService.queryGraph(currentSession.id, { query: query.trim() })
      const data = res.data
      if (!data?.nodes?.length) {
        setIsEmpty(true)
        setErrorMsg('No nodes found for that query.')
      } else {
        const { nodes, edges } = buildVisData(data)
        setNodeCount(nodes.length)
        setEdgeCount(edges.length)
        setIsEmpty(false)
        if (networkRef.current) {
          networkRef.current.setData({ nodes, edges })
        } else if (containerRef.current) {
          networkRef.current = new Network(containerRef.current, { nodes, edges }, VIS_OPTIONS)
        }
      }
    } catch {
      setErrorMsg('Query failed. Try a different phrase.')
    } finally {
      setIsLoading(false)
    }
  }

  const graphContent = (
    <div className="relative flex-1 min-h-0">
      {/* Graph canvas */}
      <div
        ref={containerRef}
        className="w-full h-full bg-gray-50 dark:bg-[#1a1a1a] rounded-lg"
        style={{ minHeight: 300 }}
      />

      {/* Overlay: loading */}
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-white/60 dark:bg-[#1a1a1a]/60 rounded-lg">
          <div className="flex flex-col items-center gap-2 text-gray-500 dark:text-gray-400">
            <Loader2 className="w-7 h-7 animate-spin" />
            <span className="text-xs">Building graph…</span>
          </div>
        </div>
      )}

      {/* Overlay: empty / error */}
      {!isLoading && isEmpty && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-center px-6">
          <div className="w-12 h-12 rounded-full bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center">
            <NetworkIcon className="w-6 h-6 text-blue-500 dark:text-blue-400" />
          </div>
          <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
            {errorMsg || (mode === 'sync' ? 'Graph updates from chat will appear here' : 'No graph data yet')}
          </p>
          {mode === 'explore' && !errorMsg && (
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Enter a query below or load the full graph
            </p>
          )}
        </div>
      )}

      {/* Node/edge counter badge */}
      {!isEmpty && (
        <div className="absolute bottom-2 right-2 flex gap-1.5">
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/80 dark:bg-[#2d2d2d]/80 backdrop-blur text-gray-600 dark:text-gray-400 border border-gray-200 dark:border-gray-700 font-mono">
            {nodeCount}N · {edgeCount}E
          </span>
        </div>
      )}

      {/* Load full graph button (explore) */}
      {mode === 'explore' && !isEmpty && (
        <button
          onClick={handleLoadFullGraph}
          title="Reload full graph"
          className="absolute top-2 right-2 p-1.5 rounded-lg bg-white/80 dark:bg-[#2d2d2d]/80 backdrop-blur border border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 transition-colors"
        >
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  )

  if (isFullscreen) {
    return (
      <div className="fixed inset-0 z-50 flex flex-col bg-white dark:bg-[#1a1a1a]">
        {/* Fullscreen header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-800">
          <span className="text-sm font-semibold text-gray-800 dark:text-gray-100">Graph View — Fullscreen</span>
          <button onClick={() => setIsFullscreen(false)} className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-[#2a2a2a] text-gray-500 dark:text-gray-400 transition-colors">
            <Minimize2 className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 min-h-0 p-4 flex flex-col">
          {graphContent}
        </div>
        {/* Query bar in fullscreen explore mode */}
        {mode === 'explore' && (
          <form onSubmit={handleExploreQuery} className="px-4 pb-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="text"
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Search the graph…"
                className="w-full pl-9 pr-12 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-full bg-white dark:bg-[#2d2d2d] text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:focus:ring-blue-500 placeholder:text-gray-400"
              />
              <button type="submit" disabled={!query.trim() || isLoading} className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded-full bg-blue-600 text-white disabled:opacity-40 hover:bg-blue-700 transition-colors">
                <Search className="w-3.5 h-3.5" />
              </button>
            </div>
          </form>
        )}
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full gap-0">
      {/* Mode toggle + fullscreen */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-100 dark:border-gray-800">
        {/* Sync / Explore toggle */}
        <div className="flex items-center gap-1 bg-gray-100 dark:bg-[#2a2a2a] rounded-lg p-0.5">
          {['sync', 'explore'].map(m => (
            <button
              key={m}
              onClick={() => onSetSyncMode(m === 'sync')}
              className={`px-3 py-1 text-xs font-medium rounded-md transition-colors capitalize ${
                mode === m
                  ? 'bg-white dark:bg-[#3d3d3d] text-gray-900 dark:text-gray-100 shadow-sm'
                  : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'
              }`}
            >
              {m === 'sync' ? '⟳ Sync' : '⌕ Explore'}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-1.5">
          {/* Reload full graph */}
          <button
            onClick={handleLoadFullGraph}
            title="Load full graph"
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-[#2a2a2a] transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
          {/* Fullscreen */}
          <button
            onClick={() => setIsFullscreen(true)}
            title="Expand graph"
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-[#2a2a2a] transition-colors"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Graph area */}
      <div className="flex-1 min-h-0 p-3 flex flex-col gap-2">
        {graphContent}
      </div>

      {/* Explore mode query bar */}
      {mode === 'explore' && (
        <form onSubmit={handleExploreQuery} className="px-3 pb-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
            <input
              type="text"
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search the knowledge graph…"
              className="w-full pl-8 pr-10 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-full bg-white dark:bg-[#2d2d2d] text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:focus:ring-blue-500 placeholder:text-gray-400 dark:placeholder:text-gray-500"
            />
            <button
              type="submit"
              disabled={!query.trim() || isLoading}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-full bg-blue-600 text-white disabled:opacity-40 hover:bg-blue-700 transition-colors"
            >
              <Search className="w-3 h-3" />
            </button>
          </div>
        </form>
      )}

      {/* Sync mode hint */}
      {mode === 'sync' && (
        <p className="px-4 pb-3 text-xs text-center text-gray-500 dark:text-gray-500">
          Graph will auto-update as you chat
        </p>
      )}
    </div>
  )
}
