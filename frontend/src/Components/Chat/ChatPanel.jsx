import { useState } from 'react'
import { ArrowUp } from 'lucide-react'

function ChatPanel({ currentSession, messages, setMessages, isVectorIndexing }) {
  const [input, setInput] = useState('')

  const handleSendMessage = (e) => {
    e.preventDefault()
    if (!input.trim() || isVectorIndexing) return

    const newMessage = {
      id: Date.now().toString(),
      text: input,
      sender: 'user',
      timestamp: new Date().toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
        hour12: true,
      }),
    }

    setMessages(prev => [...prev, newMessage])
    setInput('')

    // Simulate assistant response
    setTimeout(() => {
      setMessages(prev => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          text: 'This is a placeholder response for the new panel architecture.',
          sender: 'assistant',
          timestamp: new Date().toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit',
            hour12: true,
          }),
        },
      ])
    }, 500)
  }

  return (
    <div className="flex h-full flex-col bg-gray-50 dark:bg-[#212121]">
      <div className="flex-1 overflow-y-auto px-6 py-8">
        <div className="max-w-3xl mx-auto space-y-8">
          {messages.map(msg => (
            <div
              key={msg.id}
              className={`flex ${msg.sender === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-[85%] lg:max-w-2xl px-5 py-3 ${
                  msg.sender === 'user'
                    ? 'bg-blue-600 dark:bg-[#303134] text-white rounded-2xl rounded-tr-sm'
                    : 'bg-white dark:bg-transparent text-gray-900 dark:text-gray-200 shadow-sm dark:shadow-none border border-gray-200 dark:border-transparent rounded-2xl rounded-tl-sm'
                }`}
              >
                <p className="text-base leading-relaxed">{msg.text}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      <footer className="p-4 pt-0">
        <form onSubmit={handleSendMessage} className="max-w-3xl mx-auto relative">
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            disabled={isVectorIndexing}
            placeholder={isVectorIndexing ? "Indexing documents (please wait)..." : "Start typing..."}
            className={`w-full px-4 py-3.5 pr-14 border border-gray-300 dark:border-gray-700/50 rounded-full bg-white dark:bg-[#303134] text-gray-900 dark:text-white shadow-sm focus:outline-none focus:ring-1 focus:ring-blue-500 dark:focus:ring-gray-500 transition-all placeholder:text-gray-500 dark:placeholder:text-gray-400 ${isVectorIndexing ? 'opacity-70 cursor-not-allowed' : ''}`}
          />
          <button
            type="submit"
            disabled={!input.trim() || isVectorIndexing}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded-full bg-gray-900 dark:bg-white text-white dark:text-black hover:bg-gray-800 dark:hover:bg-gray-200 disabled:opacity-50 disabled:bg-gray-300 dark:disabled:bg-gray-600 disabled:text-gray-500 dark:disabled:text-gray-400 transition-colors"
          >
            <ArrowUp className="w-5 h-5" />
          </button>
        </form>
      </footer>
    </div>
  )
}

export default ChatPanel
