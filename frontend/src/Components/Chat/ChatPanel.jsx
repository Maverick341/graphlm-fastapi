import { useState, useRef, useEffect, memo, useMemo } from 'react'
import { ArrowUp, Loader2 } from 'lucide-react'
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
  const messagesEndRef = useRef(null)
  const scrollContainerRef = useRef(null)
  const previousScrollHeight = useRef(0)
  const isFetchingRef = useRef(false)

  const isAtBottom = useRef(true)

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
      <div 
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className="absolute inset-0 overflow-y-auto px-6 pt-8 pb-24"
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

      <footer className="absolute bottom-0 left-0 right-0 p-4 pb-6 bg-transparent pointer-events-none">
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
      </footer>
    </div>
  )
}

export default ChatPanel
