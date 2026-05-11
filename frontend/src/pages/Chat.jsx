import { useState, useEffect, useMemo, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, PanelLeftOpen, PanelRightOpen, GitBranch } from 'lucide-react'
import { useChatStore } from '@/store'
import sourceService from '@/api/sourceService'
import { Panel, Group as PanelGroup, Separator as PanelResizeHandle } from "react-resizable-panels"
import { toast } from 'sonner'

// Import our new panel components
import SourcesPanel from '@/Components/Chat/SourcesPanel'
import ChatPanel from '@/Components/Chat/ChatPanel'
import StudioPanel from '@/Components/Chat/StudioPanel'
import AddSourceModal from '@/Components/Chat/AddSourceModal'

function Chat() {
  const { id } = useParams()
  const navigate = useNavigate()
  
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
  
  const { sessions, fetchSessions } = useChatStore()

  // Make sure sessions are loaded
  useEffect(() => {
    if (!sessions.length) {
      fetchSessions()
    }
  }, [sessions.length, fetchSessions])

  const currentSession = useMemo(() => {
    return sessions.find(s => s.id === id)
  }, [sessions, id])

  const [messages, setMessages] = useState([
    {
      id: '1',
      text: 'Hello! How can I help you with your knowledge graph?',
      sender: 'assistant',
      timestamp: '10:30 AM',
    },
  ])
  
  const [sourceProgress, setSourceProgress] = useState({})

  // Panel refs and state
  const [isSourcesOpen, setIsSourcesOpen] = useState(true)
  const [isStudioOpen, setIsStudioOpen] = useState(false)
  const [isAddModalOpen, setIsAddModalOpen] = useState(false)

  const handleOpenSource = (source) => {
    const meta = source.metadata || source.source_metadata || {};
    const url = meta.repo_url || meta.file_url || meta.cloudinary_url || meta.local_path;
    
    if (url) {
      // Create an anchor tag to bypass async popup blockers
      const a = document.createElement('a');
      a.href = url;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } else {
      toast.error('No URL available for this source.');
    }
  };

  // Subscribe to SSE for active indexing sources
  useEffect(() => {
    if (!currentSession || !currentSession.sources) return;

    const activeSources = currentSession.sources.filter(s => s.status !== 'indexed' && s.status !== 'failed');
    if (activeSources.length === 0) return;

    const eventSources = [];

    activeSources.forEach(source => {
      const es = sourceService.subscribeToSourceStatus(source.id, {
        onSnapshot: (data) => {
          setSourceProgress(prev => ({
            ...prev,
            [source.id]: { 
              vector_indexed: data.vector?.indexed || false,
              graph_indexed: data.graph?.indexed || false 
            }
          }));
        },
        onIndexChanged: (data) => {
          setSourceProgress(prev => {
            const prevProgress = prev[source.id] || {};
            const nextVectorIndexed = data.vector_indexed !== undefined ? data.vector_indexed : (prevProgress.vector_indexed || false);
            const nextGraphIndexed = data.graph_indexed !== undefined ? data.graph_indexed : (prevProgress.graph_indexed || false);
            return {
              ...prev,
              [source.id]: { 
                vector_indexed: nextVectorIndexed,
                graph_indexed: nextGraphIndexed
              }
            };
          });
        },
        onComplete: () => {
          fetchSessions(); // Refresh session to get updated sources status
        }
      }, source.title);
      eventSources.push(es);
    });

    return () => {
      eventSources.forEach(es => es.close());
    };
  }, [currentSession, fetchSessions]);

  const isVectorIndexing = useMemo(() => {
    if (!currentSession || !currentSession.sources) return false;
    // Chat is disabled if any source is currently indexing and its vector is not yet indexed
    return currentSession.sources.some(s => {
      if (s.status === 'indexed' || s.status === 'failed') return false;
      const progress = sourceProgress[s.id];
      // If we haven't received a snapshot yet, assume it's indexing and block
      if (!progress) return true;
      return !progress.vector_indexed;
    });
  }, [currentSession, sourceProgress]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-white dark:bg-[#1e1e1e]">
      {/* Top Header - Global App Header or Session Return */}
      <div className="border-b border-gray-200 dark:border-gray-800 px-4 py-3 flex items-center justify-between bg-white dark:bg-[#1e1e1e]">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate('/dashboard')}
            className="group relative flex items-center justify-center p-1.5 rounded-lg text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-[#2a2a2a] transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
            <div className="absolute top-full mt-2 px-2 py-1 bg-gray-900 dark:bg-white text-white dark:text-gray-900 text-xs font-medium rounded opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all whitespace-nowrap z-50 shadow-md pointer-events-none">
              Back to Dashboard
            </div>
          </button>
          
          <div className="flex flex-col">
            <h1 className="text-base font-medium text-gray-900 dark:text-white leading-tight">
              {currentSession?.title || 'Loading session...'}
            </h1>
            <span className="text-xs text-gray-500 dark:text-gray-400">
              {currentSession?.sources?.length || 0} sources • {currentSession?.created_at ? new Date(currentSession.created_at).toLocaleDateString() : 'Today'}
            </span>
          </div>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-hidden flex">
        {/* Collapsed Sources Toolbar */}
        {!isSourcesOpen && (
          <div className="w-16 shrink-0 h-full bg-white dark:bg-[#1e1e1e] border-r border-gray-200 dark:border-gray-800 flex flex-col items-center py-3 gap-4">
            <button
              onClick={() => setIsSourcesOpen(true)}
              className="group relative p-2 rounded-lg text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-[#2a2a2a] transition-colors"
            >
              <PanelLeftOpen className="w-5 h-5" />
              <div className="absolute left-full ml-3 px-2 py-1 bg-gray-900 dark:bg-white text-white dark:text-gray-900 text-xs font-medium rounded opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all whitespace-nowrap z-50 shadow-md pointer-events-none">
                Open Sources
              </div>
            </button>
            <div className="flex flex-col gap-2 w-full px-2">
              <button 
                onClick={() => setIsAddModalOpen(true)}
                className="group relative p-2 rounded-lg bg-gray-100 dark:bg-[#2a2a2a] text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white flex items-center justify-center transition-colors"
              >
                <span className="text-lg leading-none">+</span>
                <div className="absolute left-full ml-3 px-2 py-1 bg-gray-900 dark:bg-white text-white dark:text-gray-900 text-xs font-medium rounded opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all whitespace-nowrap z-50 shadow-md pointer-events-none">
                  Add Source
                </div>
              </button>
              {currentSession?.sources?.map(s => (
                <div 
                  key={s.id} 
                  onClick={() => handleOpenSource(s)}
                  className="group relative w-full aspect-square rounded-lg bg-gray-100 dark:bg-[#2a2a2a] flex items-center justify-center cursor-pointer hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
                >
                  {s.type === 'github' ? (
                    <GitBranch className="w-5 h-5 text-gray-500 dark:text-gray-400" />
                  ) : (
                    <FileIcon filename={s.title} className="w-5 h-5" />
                  )}
                  <div className="absolute left-full ml-3 px-2 py-1 bg-gray-900 dark:bg-white text-white dark:text-gray-900 text-xs font-medium rounded opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all whitespace-nowrap z-50 shadow-md pointer-events-none">
                    {s.title}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="flex-1 min-w-0">
          <PanelGroup direction="horizontal">
            {/* Panel 1: Sources */}
            {isSourcesOpen && (
              <>
                <Panel defaultSize="20" minSize="15" maxSize="40">
                  <SourcesPanel 
                    currentSession={currentSession} 
                    sourceProgress={sourceProgress} 
                    onCollapse={() => setIsSourcesOpen(false)}
                    onOpenAddModal={() => setIsAddModalOpen(true)}
                    handleOpenSource={handleOpenSource}
                  />
                </Panel>
                <PanelResizeHandle className="w-1 bg-transparent hover:bg-blue-500/50 active:bg-blue-500 transition-colors cursor-col-resize z-10" />
              </>
            )}

            {/* Panel 2: Chat */}
            <Panel defaultSize="50" minSize="30">
              <ChatPanel 
                currentSession={currentSession}
                messages={messages}
                setMessages={setMessages}
                isVectorIndexing={isVectorIndexing}
              />
            </Panel>

            {/* Panel 3: Studio */}
            {isStudioOpen && (
              <>
                <PanelResizeHandle className="w-1 bg-transparent hover:bg-blue-500/50 active:bg-blue-500 transition-colors cursor-col-resize z-10" />
                <Panel defaultSize="30" minSize="20" maxSize="50">
                  <StudioPanel 
                    onCollapse={() => setIsStudioOpen(false)}
                  />
                </Panel>
              </>
            )}
          </PanelGroup>
        </div>

        {/* Collapsed Studio Toolbar */}
        {!isStudioOpen && (
          <div className="w-16 shrink-0 h-full bg-white dark:bg-[#1e1e1e] border-l border-gray-200 dark:border-gray-800 flex flex-col items-center py-3 gap-4">
            <button
              onClick={() => setIsStudioOpen(true)}
              className="group relative p-2 rounded-lg text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-[#2a2a2a] transition-colors"
            >
              <PanelRightOpen className="w-5 h-5" />
              <div className="absolute right-full mr-3 px-2 py-1 bg-gray-900 dark:bg-white text-white dark:text-gray-900 text-xs font-medium rounded opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all whitespace-nowrap z-50 shadow-md pointer-events-none">
                Open Studio
              </div>
            </button>
            <div className="flex flex-col gap-3 w-full px-2">
               {/* Studio placeholder tools */}
               <div className="group relative w-full aspect-square rounded-lg bg-gray-100 dark:bg-[#2a2a2a] flex items-center justify-center text-blue-500 dark:text-blue-400 cursor-pointer hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors">
                  <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M16 3h5v5"/><path d="M21 3 9 15"/><path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/></svg>
                  <div className="absolute right-full mr-3 px-2 py-1 bg-gray-900 dark:bg-white text-white dark:text-gray-900 text-xs font-medium rounded opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all whitespace-nowrap z-50 shadow-md pointer-events-none">
                    Graph Tools
                  </div>
               </div>
               <div className="group relative w-full aspect-square rounded-lg bg-gray-100 dark:bg-[#2a2a2a] flex items-center justify-center text-green-500 dark:text-green-400 cursor-pointer hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors">
                  <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
                  <div className="absolute right-full mr-3 px-2 py-1 bg-gray-900 dark:bg-white text-white dark:text-gray-900 text-xs font-medium rounded opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all whitespace-nowrap z-50 shadow-md pointer-events-none">
                    Network View
                  </div>
               </div>
            </div>
          </div>
        )}
      </div>
      
      <AddSourceModal 
        isOpen={isAddModalOpen} 
        onClose={() => setIsAddModalOpen(false)}
        currentSession={currentSession}
      />
    </div>
  )
}

export default Chat

