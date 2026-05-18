import { useState, useRef, useEffect, memo, useMemo } from 'react'
import { ArrowUp, Loader2, MoreVertical, Pencil, X } from 'lucide-react'
import { useChatStore } from '@/store'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { parseContent } from '../../utils/parseContent'
import { CodeBlock } from './Renderers/CodeBlock'
import { TableRenderer, TableHead, TableBody, TableRow, TableHeader, TableCell } from './Renderers/TableRenderer'
import { CitationBadge } from './Renderers/CitationBadge'

const MARKDOWN_COMPONENTS = {
  code: CodeBlock,
  table: TableRenderer,
  thead: TableHead,
  tbody: TableBody,
  tr: TableRow,
  th: TableHeader,
  td: TableCell,
}

function renderParsedContent(content) {
  const blocks = parseContent(content)
  return blocks.map((block, i) => {
    if (block.type === 'citation') {
      return <CitationBadge key={i} source={block.source} page={block.page} />
    }
    return (
      <ReactMarkdown key={i} remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
        {block.value}
      </ReactMarkdown>
    )
  })
}

// Memoised bubble — only re-renders when its own message object reference changes.
// During streaming only the one streaming message updates; all completed ones stay frozen.
const MessageBubble = memo(function MessageBubble({ msg }) {
  return (
    <div className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] lg:max-w-2xl px-5 py-3 ${
          msg.role === 'user'
            ? 'bg-blue-600 dark:bg-[#303134] text-white rounded-2xl rounded-tr-sm'
            : 'bg-white dark:bg-[#2d2d2d] text-gray-900 dark:text-gray-200 shadow-sm border border-gray-200 dark:border-gray-700/50 rounded-2xl rounded-tl-sm'
        } ${msg.status === 'error' ? 'border-red-500 border' : ''}`}
      >
        {msg.status === 'streaming' && !msg.content ? (
          <div className="flex items-center gap-3 text-gray-500 dark:text-gray-400">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span className="text-sm italic">
              {msg.metadata?.phase
                ? msg.metadata.phase
                    .split('_')
                    .map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
                    .join(' ') + '...'
                : 'Thinking...'}
            </span>
          </div>
        ) : (
          <div className={`text-base leading-relaxed prose dark:prose-invert prose-p:my-1 prose-pre:bg-transparent dark:prose-pre:bg-transparent max-w-none ${msg.role === 'user' ? 'prose-p:text-white prose-a:text-blue-200' : ''}`}>
            {msg.role === 'user' ? (
              <p>{msg.content}</p>
            ) : (
              renderParsedContent(msg.content)
            )}
          </div>
        )}
      </div>
    </div>
  )
})

function ChatPanel({ currentSession, isVectorIndexing, selectedSources = [] }) {
  const [input, setInput] = useState('')
  const { messages, sendMessage, stopStreaming, isStreaming, isLoadingMessages, isFetchingMore, hasMoreMessages, loadMoreMessages } = useChatStore()
  const { fetchSessions } = useChatStore()
  const messagesEndRef = useRef(null)
  const scrollContainerRef = useRef(null)
  const previousScrollHeight = useRef(0)
  const isFetchingRef = useRef(false)

  // 3-dot menu state
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef(null)

  // Rename dialog state
  const [isRenaming, setIsRenaming] = useState(false)
  const [renameValue, setRenameValue] = useState('')
  const [renameLoading, setRenameLoading] = useState(false)
  const renameInputRef = useRef(null)

  const isAtBottom = useRef(true)

  // Close 3-dot menu on outside click
  useEffect(() => {
    const handleClick = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  // Focus rename input when dialog opens
  useEffect(() => {
    if (isRenaming) {
      setRenameValue(currentSession?.title || '')
      setTimeout(() => renameInputRef.current?.select(), 50)
    }
  }, [isRenaming])

  const handleOpenRename = () => {
    setMenuOpen(false)
    setIsRenaming(true)
  }

  const handleRename = async (e) => {
    e.preventDefault()
    const trimmed = renameValue.trim()
    if (!trimmed || !currentSession) return
    setRenameLoading(true)
    try {
      const { chatSessionService } = await import('@/api/chatSessionService')
      await chatSessionService.renameSession(currentSession.id, trimmed)
      await fetchSessions()
    } catch (err) {
      console.error('Rename failed:', err)
    } finally {
      setRenameLoading(false)
      setIsRenaming(false)
    }
  }

  // Pin the scroll to the bottom during streaming — instant, no animation fighting
  const pinToBottom = () => {
    const el = scrollContainerRef.current
    if (el) el.scrollTop = el.scrollHeight
  }

  // Smooth scroll only for the initial jump when user sends a message
  const smoothScrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    if (isFetchingRef.current && scrollContainerRef.current) {
      // Preserve scroll position when prepending old messages
      const newScrollHeight = scrollContainerRef.current.scrollHeight;
      scrollContainerRef.current.scrollTop = newScrollHeight - previousScrollHeight.current;
      isFetchingRef.current = false;
    } else if (!isFetchingMore && !isFetchingRef.current && isAtBottom.current) {
      // Only auto-scroll if user is already near the bottom.
      // Use instant scroll during streaming to avoid competing animations.
      pinToBottom()
    }
  }, [messages])

  const handleScroll = (e) => {
    const el = e.target
    // Track if user is near the bottom (within 80px threshold)
    isAtBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80

    if (el.scrollTop === 0 && hasMoreMessages && !isFetchingMore && currentSession) {
      previousScrollHeight.current = el.scrollHeight;
      isFetchingRef.current = true;
      loadMoreMessages(currentSession.id);
    }
  }

  const handleSendMessage = async (e) => {
    e.preventDefault()
    if (!input.trim() || isVectorIndexing || isStreaming || !currentSession) return

    const content = input
    setInput('')
    isAtBottom.current = true // ensure we scroll to new message
    await sendMessage(currentSession.id, content, selectedSources)
  }


  return (
    <div className="flex h-full flex-col bg-gray-50 dark:bg-[#212121] relative">

      {/* Chat panel header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-[#1e1e1e] shrink-0">
        <span className="text-sm font-medium text-gray-700 dark:text-gray-300 flex items-center gap-2">
          <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-gray-400 dark:text-gray-500">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
          Chat
        </span>

        {/* 3-dot menu */}
        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setMenuOpen(o => !o)}
            className="p-1 rounded-md text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-[#2a2a2a] transition-colors"
            title="Chat options"
          >
            <MoreVertical className="w-4 h-4" />
          </button>

          {menuOpen && (
            <div className="absolute right-0 top-full mt-1 w-40 bg-white dark:bg-[#2a2a2a] border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-50 py-1 overflow-hidden">
              <button
                onClick={handleOpenRename}
                className="flex items-center gap-2.5 w-full px-3 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-[#3a3a3a] transition-colors"
              >
                <Pencil className="w-3.5 h-3.5 text-gray-400" />
                Rename
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Rename dialog */}
      {isRenaming && (
        <div className="absolute inset-0 z-50 flex items-start justify-center pt-24 px-6">
          {/* Backdrop */}
          <div className="absolute inset-0 bg-black/30 dark:bg-black/50" onClick={() => setIsRenaming(false)} />
          <form
            onSubmit={handleRename}
            className="relative w-full max-w-sm bg-white dark:bg-[#2a2a2a] rounded-xl shadow-2xl border border-gray-200 dark:border-gray-700 p-5"
          >
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Rename chat</h3>
              <button type="button" onClick={() => setIsRenaming(false)} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>
            <input
              ref={renameInputRef}
              type="text"
              value={renameValue}
              onChange={e => setRenameValue(e.target.value)}
              maxLength={100}
              placeholder="Chat name"
              className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-[#1e1e1e] text-gray-900 dark:text-white placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:focus:ring-blue-600 mb-3"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setIsRenaming(false)}
                className="px-3 py-1.5 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-[#3a3a3a] rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!renameValue.trim() || renameLoading}
                className="px-3 py-1.5 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {renameLoading ? 'Saving…' : 'Save'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Scrollable messages area */}
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-6 pt-6 pb-24"
      >
        <div className="max-w-3xl mx-auto space-y-8">
          {hasMoreMessages && !isFetchingMore && (
            <div className="flex justify-center py-2">
              <button 
                onClick={() => {
                  isFetchingRef.current = true;
                  loadMoreMessages(currentSession.id);
                }} 
                className="text-xs font-medium px-4 py-1.5 rounded-full bg-gray-100 hover:bg-gray-200 dark:bg-[#2d2d2d] dark:hover:bg-[#3d3d3d] text-gray-600 dark:text-gray-300 transition-colors"
              >
                Load previous messages
              </button>
            </div>
          )}
          {isFetchingMore && (
            <div className="flex justify-center items-center py-4 text-gray-500">
              <Loader2 className="w-5 h-5 animate-spin mr-2" />
              <span className="text-sm">Loading older messages...</span>
            </div>
          )}
          {isLoadingMessages ? (
            <div className="flex justify-center items-center py-10 text-gray-500">
              <Loader2 className="w-6 h-6 animate-spin mr-2" />
              Loading messages...
            </div>
          ) : messages.length === 0 ? (
             <div className="flex flex-col items-center justify-center py-20 text-center">
               <div className="w-16 h-16 bg-blue-100 dark:bg-blue-900/30 rounded-full flex items-center justify-center mb-6">
                 <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-blue-600 dark:text-blue-400"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
               </div>
               <h3 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-2">How can I help you today?</h3>
               <p className="text-gray-500 dark:text-gray-400 max-w-md">Ask questions about your documents and the knowledge graph will provide accurate, grounded answers.</p>
             </div>
          ) : (
            <>
              {messages.map(msg => (
                <MessageBubble key={msg.id} msg={msg} />
              ))}
            </>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      <div className="absolute bottom-0 left-0 right-0 p-4 pb-6 bg-transparent pointer-events-none">
        <form onSubmit={handleSendMessage} className="max-w-3xl mx-auto relative pointer-events-auto">
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            disabled={isVectorIndexing || isStreaming}
            placeholder={isVectorIndexing ? "Indexing documents (please wait)..." : isStreaming ? "Assistant is typing..." : "Message GraphLM..."}
            className={`w-full px-4 py-2.5 pr-14 border border-gray-300 dark:border-gray-700/50 rounded-full bg-white dark:bg-[#303134] text-gray-900 dark:text-white shadow-sm focus:outline-none focus:ring-1 focus:ring-blue-500 dark:focus:ring-gray-500 transition-all placeholder:text-gray-500 dark:placeholder:text-gray-400 ${isVectorIndexing || isStreaming ? 'opacity-70 cursor-not-allowed' : ''}`}
          />
          
          {isStreaming ? (
            <button
              type="button"
              onClick={stopStreaming}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded-full bg-red-600 dark:bg-red-500 text-white hover:bg-red-700 dark:hover:bg-red-600 transition-colors"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="currentColor" stroke="none"><rect x="6" y="6" width="12" height="12" rx="2" ry="2"/></svg>
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim() || isVectorIndexing}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded-full bg-blue-600 dark:bg-white text-white dark:text-black hover:bg-blue-700 dark:hover:bg-gray-200 disabled:opacity-50 disabled:bg-gray-300 dark:disabled:bg-gray-600 disabled:text-gray-500 dark:disabled:text-gray-400 transition-colors"
            >
              <ArrowUp className="w-5 h-5" />
            </button>
          )}
        </form>
      </div>
    </div>
  )
}

export default ChatPanel
