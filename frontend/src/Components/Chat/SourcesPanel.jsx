import { useState, useEffect, useMemo } from 'react'
import { Plus, Search, FileText, GitBranch, ChevronRight, PanelLeftClose, MoreVertical, Trash2 } from 'lucide-react'
import useChatStore from '@/store/chatStore'

function SourcesPanel({ currentSession, sourceProgress, onCollapse, onOpenAddModal, handleOpenSource, selectedSources = [], onSelectionChange, isGraphViewOpen = false }) {
  const [openMenuId, setOpenMenuId] = useState(null)
  const [searchQuery, setSearchQuery] = useState('')
  const sources = currentSession?.sources || []
  const { removeSource } = useChatStore()

  const filteredSources = useMemo(() => {
    if (!searchQuery.trim()) return sources;
    const lowerQuery = searchQuery.toLowerCase();
    return sources.filter(source => 
      source.title?.toLowerCase().includes(lowerQuery)
    );
  }, [sources, searchQuery]);

  const FileIcon = ({ filename, className }) => {
    const ext = filename?.split('.').pop()?.toLowerCase();
    if (ext === 'pdf') return <img src="/fileIcons/file-pdf.svg" alt="PDF" className={className} />;
    if (ext === 'doc' || ext === 'docx') return <img src="/fileIcons/file-docx.svg" alt="Word" className={className} />;
    if (ext === 'md' || ext === 'markdown') return <img src="/fileIcons/file-code.svg" alt="Markdown" className={className} />;
    return (
      <>
        <img src="/fileIcons/file-text-dark.svg" alt="Text" className={`${className} hidden dark:block`} />
        <img src="/fileIcons/file-text-light.svg" alt="Text" className={`${className} block dark:hidden`} />
      </>
    );
  };

  useEffect(() => {
    const handleClickOutside = () => setOpenMenuId(null);
    if (openMenuId) {
      document.addEventListener('click', handleClickOutside);
    }
    return () => document.removeEventListener('click', handleClickOutside);
  }, [openMenuId]);

  const handleRemove = async (e, sourceId) => {
    e.stopPropagation();
    if (currentSession) {
      await removeSource(currentSession.id, sourceId);
      // Remove from selected list if deleted
      setSelectedSources(prev => prev.filter(id => id !== sourceId));
    }
  };

  const handleSelectAll = (e) => {
    if (e.target.checked) {
      const newSelections = new Set([...selectedSources, ...filteredSources.map(s => s.id)])
      onSelectionChange(Array.from(newSelections))
    } else {
      const filteredIds = new Set(filteredSources.map(s => s.id))
      onSelectionChange(selectedSources.filter(id => !filteredIds.has(id)))
    }
  }

  const handleSelect = (sourceId) => {
    onSelectionChange(
      selectedSources.includes(sourceId)
        ? selectedSources.filter(id => id !== sourceId)
        : [...selectedSources, sourceId]
    )
  }

  return (
    <div className="flex flex-col h-full bg-white dark:bg-[#1e1e1e] text-gray-900 dark:text-gray-200 border-r border-gray-200 dark:border-gray-800">
      <div className="flex items-center justify-between px-4 py-3">
        <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-200">Sources</h2>
        <button 
          onClick={onCollapse}
          className="text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-white p-1 rounded-md hover:bg-gray-100 dark:hover:bg-[#2a2a2a] transition-colors"
          title="Close Sources"
        >
          <PanelLeftClose className="w-4 h-4" />
        </button>
      </div>

      <div className="px-4 pb-3">
        <button 
          onClick={onOpenAddModal}
          className="w-full py-2 flex items-center justify-center gap-2 border border-gray-300 dark:border-gray-700 rounded-full text-sm font-medium hover:bg-gray-50 dark:hover:bg-[#2a2a2a] transition-colors text-gray-900 dark:text-white"
        >
          <Plus className="w-4 h-4" /> Add source
        </button>
      </div>

      <div className="px-4 pb-2">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 dark:text-gray-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search for sources"
            className="w-full bg-gray-100 dark:bg-[#2a2a2a] border border-transparent focus:border-gray-300 dark:focus:border-gray-600 rounded-lg pl-9 pr-4 py-1.5 text-sm text-gray-900 dark:text-white outline-none transition-colors placeholder:text-gray-500"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-2 mt-2 space-y-1">
        {/* Select All Header */}
        {filteredSources.length > 0 && (
          <div
            className="flex items-center justify-end px-2 py-2 mb-2 border-b border-gray-200 dark:border-gray-800 gap-3"
            title={isGraphViewOpen ? 'Close Graph View to change source selection' : ''}
          >
            <span className={`text-xs ${isGraphViewOpen ? 'text-gray-400 dark:text-gray-600' : 'text-gray-500 dark:text-gray-400'}`}>Select all</span>
            <input 
              type="checkbox" 
              checked={filteredSources.length > 0 && filteredSources.every(s => selectedSources.includes(s.id))}
              onChange={handleSelectAll}
              disabled={isGraphViewOpen}
              className={`rounded border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 text-blue-500 focus:ring-blue-500 focus:ring-offset-white dark:focus:ring-offset-gray-900 w-4 h-4 ml-1 ${isGraphViewOpen ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
            />
          </div>
        )}

        {filteredSources.map(source => {
          const isGithub = source.type === 'github'
          const progress = sourceProgress[source.id];
          const isIndexing = source.status !== 'indexed' && source.status !== 'failed';
          const isVectorIndexing = isIndexing && (progress ? !progress.vector_indexed : true);
          const isGraphIndexing = isIndexing && (progress ? !progress.graph_indexed : true);
          const showBlink = isVectorIndexing;

          return (
            <div key={source.id} className={`flex items-center justify-between p-2 rounded-lg hover:bg-gray-50 dark:hover:bg-[#2a2a2a] group cursor-pointer ${showBlink ? 'animate-pulse bg-gray-50/50 dark:bg-[#2a2a2a]/40' : ''}`}>
              <div 
                onClick={() => handleOpenSource && handleOpenSource(source)}
                className="flex items-center gap-3 overflow-hidden flex-1"
              >
                {isGithub ? (
                  <GitBranch className="w-4 h-4 text-gray-500 dark:text-gray-400 shrink-0" />
                ) : (
                  <FileIcon filename={source.title} className="w-4 h-4 shrink-0" />
                )}
                <span className="text-sm truncate text-gray-900 dark:text-gray-200">{source.title}</span>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {isVectorIndexing && source.status !== 'failed' && (
                  <span className="text-[10px] text-blue-500 dark:text-blue-400 font-medium">Indexing Vector...</span>
                )}
                {!isVectorIndexing && isGraphIndexing && source.status !== 'failed' && (
                  <span className="text-[10px] text-purple-500 dark:text-purple-400 font-medium">Indexing Graph...</span>
                )}
                
                {/* 3-Dot Menu */}
                <div className={`relative transition-opacity ${openMenuId === source.id ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`} onClick={e => e.stopPropagation()}>
                  <button 
                    onClick={() => setOpenMenuId(openMenuId === source.id ? null : source.id)}
                    className={`p-1 hover:text-gray-900 dark:hover:text-white rounded-md hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors ${openMenuId === source.id ? 'text-gray-900 bg-gray-200 dark:text-white dark:bg-gray-700' : 'text-gray-400'}`}
                  >
                    <MoreVertical className="w-4 h-4" />
                  </button>
                  {openMenuId === source.id && (
                    <div className="absolute right-0 top-full mt-1 w-36 bg-white dark:bg-[#1a1a1a] border border-gray-200 dark:border-gray-700 rounded-md shadow-lg z-50">
                      <button 
                        onClick={(e) => {
                          handleRemove(e, source.id);
                          setOpenMenuId(null);
                        }}
                        className="w-full flex items-center gap-2 px-3 py-2 text-xs text-red-500 dark:text-red-400 hover:text-red-600 dark:hover:text-red-300 hover:bg-gray-50 dark:hover:bg-[#2a2a2a] rounded-md transition-colors text-left"
                      >
                        <Trash2 className="w-3 h-3" /> Remove
                      </button>
                    </div>
                  )}
                </div>

                <input 
                  type="checkbox" 
                  checked={selectedSources.includes(source.id)}
                  onChange={() => handleSelect(source.id)}
                  disabled={isGraphViewOpen}
                  title={isGraphViewOpen ? 'Close Graph View to change source selection' : ''}
                  className={`rounded border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 text-blue-500 focus:ring-blue-500 focus:ring-offset-white dark:focus:ring-offset-gray-900 w-4 h-4 ml-1 ${isGraphViewOpen ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
                  onClick={(e) => e.stopPropagation()}
                />
              </div>
            </div>
          )
        })}
        {filteredSources.length === 0 && (
          <div className="px-4 py-8 text-center text-sm text-gray-500">
            {searchQuery.trim() ? "No sources match your search." : "No sources attached yet."}
          </div>
        )}
      </div>
    </div>
  )
}

export default SourcesPanel
