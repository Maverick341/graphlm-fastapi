import { create } from 'zustand';
import chatSessionService from '@/api/chatSessionService';
import chatMessageService from '@/api/chatMessageService';
import { toast } from 'sonner';

const useChatStore = create((set, get) => ({
  sessions: [],
  currentSession: null,
  messages: [],
  hasMoreMessages: false,
  messagesSkip: 0,
  isFetchingMore: false,
  
  // Streaming states
  isStreaming: false,
  abortController: null,

  // Graph canvas state
  graphData: null,
  subgraphMode: false,
  
  // Loading states
  isLoadingSessions: false,
  isLoadingMessages: false,
  isCreatingSession: false,
  
  error: null,

  setSubgraphMode: (enabled) => set({ subgraphMode: enabled }),
  clearGraphData: () => set({ graphData: null }),

  stopStreaming: () => {
    const controller = get().abortController;
    if (controller) {
      controller.abort();
    }
    set({
      isStreaming: false,
      abortController: null
    });
  },

  // --- Session Actions ---
  
  fetchSessions: async (params = {}) => {
    set({ isLoadingSessions: true, error: null });
    try {
      const data = await chatSessionService.getSessions(params);
      set({ sessions: data.data || [] });
    } catch (err) {
      console.error(err);
      set({ error: err.message || 'Failed to fetch sessions' });
    } finally {
      set({ isLoadingSessions: false });
    }
  },

  fetchSession: async (sessionId) => {
    try {
      const data = await chatSessionService.getSessionById(sessionId);
      const sessionData = data.data || data;
      set((state) => ({ 
        currentSession: sessionData,
        sessions: state.sessions.map(s => s.id === sessionId ? sessionData : s)
      }));
    } catch (err) {
      console.error(err);
      toast.error('Failed to load session details');
    }
  },

  createSession: async (sessionData = { title: 'New Chat' }) => {
    set({ isCreatingSession: true });
    try {
      const response = await chatSessionService.createSession(sessionData);
      const newSession = response.data || response;
      set((state) => ({
        sessions: [newSession, ...state.sessions],
        currentSession: newSession,
        messages: [] // Clear messages for new session
      }));
      return newSession;
    } catch (err) {
      console.error(err);
      toast.error('Failed to create new chat session');
      throw err;
    } finally {
      set({ isCreatingSession: false });
    }
  },

  deleteSession: async (sessionId) => {
    try {
      await chatSessionService.deleteSession(sessionId);
      set((state) => ({
        sessions: state.sessions.filter(s => s.id !== sessionId),
        currentSession: state.currentSession?.id === sessionId ? null : state.currentSession,
        messages: state.currentSession?.id === sessionId ? [] : state.messages
      }));
      toast.success('Chat deleted');
    } catch (err) {
      console.error(err);
      toast.error('Failed to delete session');
    }
  },

  renameSession: async (sessionId, title) => {
    try {
      const response = await chatSessionService.renameSession(sessionId, title);
      const updatedSession = response.data || response;
      set((state) => ({
        sessions: state.sessions.map(s => s.id === sessionId ? { ...s, title: updatedSession.title } : s),
        currentSession: state.currentSession?.id === sessionId ? { ...state.currentSession, title: updatedSession.title } : state.currentSession
      }));
      toast.success('Chat renamed');
    } catch (err) {
      console.error(err);
      toast.error('Failed to rename session');
    }
  },

  attachSources: async (sessionId, sourceIds) => {
    try {
      await chatSessionService.attachSources(sessionId, sourceIds);
      get().fetchSession(sessionId);
      toast.success('Source attached to session');
    } catch (err) {
      console.error(err);
      const errorMessage = err.response?.data?.message || 'Failed to attach source';
      toast.error(errorMessage);
      throw err;
    }
  },

  removeSource: async (sessionId, sourceId) => {
    try {
      await chatSessionService.removeSource(sessionId, sourceId);
      get().fetchSession(sessionId);
      toast.success('Source removed from session');
    } catch (err) {
      console.error(err);
      const errorMessage = err.response?.data?.message || 'Failed to remove source';
      toast.error(errorMessage);
      throw err;
    }
  },

  // --- Message Actions ---

  fetchMessages: async (sessionId, params = { skip: 0, limit: 50 }) => {
    set({ isLoadingMessages: true });
    try {
      const data = await chatMessageService.getMessages(sessionId, params);
      const fetchedMessages = data.data?.messages || [];
      const pagination = data.data?.pagination || {};
      
      set({ 
        messages: fetchedMessages.reverse(),
        hasMoreMessages: pagination.has_more || false,
        messagesSkip: params.skip,
      });
    } catch (err) {
      console.error(err);
      toast.error('Failed to load messages');
    } finally {
      set({ isLoadingMessages: false });
    }
  },

  loadMoreMessages: async (sessionId) => {
    const state = get();
    if (state.isFetchingMore || !state.hasMoreMessages) return;

    set({ isFetchingMore: true });
    const nextSkip = state.messagesSkip + 50;
    
    try {
      const data = await chatMessageService.getMessages(sessionId, { skip: nextSkip, limit: 50 });
      const newMessages = data.data?.messages || [];
      const pagination = data.data?.pagination || {};
      
      set({ 
        messages: [...newMessages.reverse(), ...state.messages],
        hasMoreMessages: pagination.has_more || false,
        messagesSkip: nextSkip,
      });
    } catch (err) {
      console.error(err);
      toast.error('Failed to load older messages');
    } finally {
      set({ isFetchingMore: false });
    }
  },

  sendMessage: async (sessionId, content) => {
    if (!content.trim() || get().isStreaming) return;

    const controller = new AbortController();

    // Optimistically add user message
    const userMessage = {
      id: `temp-user-${Date.now()}`,
      role: 'user',
      content: content,
      created_at: new Date().toISOString()
    };

    const assistantId = `assistant-${Date.now()}`;
    const assistantMessage = {
      id: assistantId,
      role: 'agent',
      content: '',
      status: 'streaming',
      created_at: new Date().toISOString(),
      metadata: {
        phase: 'starting',
        tools: []
      }
    };

    set((state) => ({
      messages: [...state.messages, userMessage, assistantMessage],
      isStreaming: true,
      abortController: controller
    }));

    const { subgraphMode } = get();

    // --- RAF token batching ---
    // Accumulate tokens between animation frames so we call set() at most ~60fps
    // instead of once per token (which can be 20-50+ times per second).
    let pendingTokens = '';
    let rafId = null;

    const flushTokens = () => {
      rafId = null;
      if (!pendingTokens) return;
      const batch = pendingTokens;
      pendingTokens = '';
      set((state) => ({
        messages: state.messages.map(msg =>
          msg.id === assistantId
            ? { ...msg, content: msg.content + batch }
            : msg
        )
      }));
    };

    await chatMessageService.sendMessageStream(
      sessionId,
      { content, subgraph_mode: subgraphMode },
      
      // onChunk handler
      (chunk) => {
        const { event, data } = chunk;

        // Tokens are batched via RAF — never block the main thread per-token
        if (event === 'token' && data.content) {
          pendingTokens += data.content;
          if (!rafId) rafId = requestAnimationFrame(flushTokens);
          return;
        }

        // Flush any buffered tokens immediately before processing a control event
        // so ordering is preserved (e.g. done comes after all tokens are flushed)
        if (rafId) {
          cancelAnimationFrame(rafId);
          flushTokens();
        }
        
        set((state) => ({
          messages: state.messages.map(msg => {
            if (msg.id !== assistantId) return msg;

            let updatedStatus = msg.status;
            let updatedPhase = msg.metadata?.phase || 'processing';
            
            if (event === 'pipeline' && data.type) {
              updatedPhase = data.type;
            } else if (event === 'error') {
              updatedStatus = 'error';
            } else if (event === 'done') {
              updatedStatus = data.status || 'completed';
            }
            
            return {
              ...msg,
              id: (event === 'done' && data.message_id) ? data.message_id : msg.id,
              status: updatedStatus,
              created_at: (event === 'done' && data.created_at) ? data.created_at : msg.created_at,
              metadata: {
                ...msg.metadata,
                phase: updatedPhase
              }
            };
          }),
          // Update graph panel when agent emits a graph_update event
          // Only replace if the new result has actual nodes — preserve previous graph on empty results
          ...(event === 'graph_update' && data?.nodes?.length > 0 ? { graphData: data } : {}),
        }));
      },
      
      // onError handler
      (err) => {
        if (rafId) { cancelAnimationFrame(rafId); flushTokens(); }
        set((state) => ({
          messages: state.messages.map(msg => 
            msg.id === assistantId 
              ? { ...msg, status: 'error', content: msg.content + '\n\n*An error occurred while generating the response.*' }
              : msg
          ),
          isStreaming: false,
          abortController: null
        }));
        toast.error('Failed to send message');
      },
      
      // onComplete handler
      () => {
        if (rafId) { cancelAnimationFrame(rafId); flushTokens(); }
        set((state) => ({
          isStreaming: false,
          abortController: null
        }));
      },
      controller.signal
    );
  }
}));

export default useChatStore;
