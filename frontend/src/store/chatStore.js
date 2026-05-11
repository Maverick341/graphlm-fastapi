import { create } from 'zustand';
import chatSessionService from '@/api/chatSessionService';
import chatMessageService from '@/api/chatMessageService';
import { toast } from 'sonner';

const useChatStore = create((set, get) => ({
  sessions: [],
  currentSession: null,
  messages: [],
  
  // Streaming states
  isStreaming: false,
  streamingMessage: null,
  
  // Loading states
  isLoadingSessions: false,
  isLoadingMessages: false,
  isCreatingSession: false,
  
  error: null,

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

  fetchMessages: async (sessionId, params = {}) => {
    set({ isLoadingMessages: true });
    try {
      const data = await chatMessageService.getMessages(sessionId, params);
      // Assuming pagination returns oldest last, reverse if needed based on API
      // Usually chat interfaces want oldest first in the UI
      set({ messages: data.data?.items?.reverse() || [] });
    } catch (err) {
      console.error(err);
      toast.error('Failed to load messages');
    } finally {
      set({ isLoadingMessages: false });
    }
  },

  sendMessage: async (sessionId, content) => {
    if (!content.trim() || get().isStreaming) return;

    // Optimistically add user message
    const userMessage = {
      id: `temp-${Date.now()}`,
      role: 'user',
      content: content,
      created_at: new Date().toISOString()
    };

    set((state) => ({
      messages: [...state.messages, userMessage],
      isStreaming: true,
      streamingMessage: {
        id: `stream-${Date.now()}`,
        role: 'agent',
        content: '',
        status: 'processing'
      }
    }));

    await chatMessageService.sendMessageStream(
      sessionId,
      { content },
      
      // onChunk handler
      (chunk) => {
        const { event, data } = chunk;
        
        set((state) => {
          if (!state.streamingMessage) return state;
          
          let updatedContent = state.streamingMessage.content;
          let updatedStatus = state.streamingMessage.status;
          
          if (event === 'token' && data.token) {
            updatedContent += data.token;
          } else if (event === 'status') {
             // Handle intermediate pipeline statuses (e.g. searching, indexing)
             updatedStatus = data.status || updatedStatus;
          } else if (event === 'error') {
            updatedStatus = 'error';
          }
          
          return {
            streamingMessage: {
              ...state.streamingMessage,
              content: updatedContent,
              status: updatedStatus
            }
          };
        });
      },
      
      // onError handler
      (err) => {
        set((state) => {
          if (!state.streamingMessage) return state;
          return {
            streamingMessage: {
              ...state.streamingMessage,
              status: 'error',
              content: state.streamingMessage.content + '\\n\\n*An error occurred while generating the response.*'
            },
            isStreaming: false
          };
        });
        toast.error('Failed to send message');
      },
      
      // onComplete handler
      () => {
        set((state) => {
          if (!state.streamingMessage) return { isStreaming: false };
          
          // Move the completed streaming message to the permanent message list
          return {
            messages: [...state.messages, { ...state.streamingMessage, status: 'completed' }],
            streamingMessage: null,
            isStreaming: false
          };
        });
      }
    );
  }
}));

export default useChatStore;
