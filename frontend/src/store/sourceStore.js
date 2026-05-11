import { create } from 'zustand';
import sourceService from '@/api/sourceService';
import { toast } from 'sonner';

const useSourceStore = create((set, get) => ({
  sources: [],
  isLoadingSources: false,
  isUploading: false,
  error: null,
  hasMore: false,
  total: 0,
  page: 0,
  limit: 10,
  autoAttach: true,
  setAutoAttach: (value) => set({ autoAttach: value }),

  // Fetch sources
  fetchSources: async (skip = 0, limit = 10, append = false) => {
    set({ isLoadingSources: true, error: null });
    try {
      const response = await sourceService.getSources({ skip, limit });
      const data = response.data;
      
      set((state) => ({
        sources: append ? [...state.sources, ...data.items] : data.items,
        total: data.total,
        hasMore: data.has_more,
        page: Math.floor(skip / limit),
        limit,
      }));
    } catch (err) {
      console.error(err);
      set({ error: err.message || 'Failed to fetch sources' });
      toast.error('Failed to load sources');
    } finally {
      set({ isLoadingSources: false });
    }
  },

  // Upload a document
  uploadDocument: async (file, title) => {
    set({ isUploading: true, error: null });
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('title', title);
      
      const response = await sourceService.uploadDocument(formData);
      const newSourceData = response.data;
      
      // We don't automatically add it to the list yet unless we want to poll/refresh
      // or we can optimistically prepend it
      toast.success('Document uploaded successfully. Indexing started.');
      
      // Background subscribe to show toasts even if not attached to current session
      const sourceId = newSourceData.source_id || newSourceData.id;
      if (sourceId) {
        sourceService.subscribeToSourceStatus(sourceId, {}, title || file.name);
      }
      
      return newSourceData;
    } catch (err) {
      console.error(err);
      toast.error(err?.response?.data?.message || 'Failed to upload document');
      throw err;
    } finally {
      set({ isUploading: false });
    }
  },

  // Add a GitHub repo
  addGithub: async (repoUrl, title, branch = 'main', includeExtensions = []) => {
    set({ isUploading: true, error: null });
    try {
      const data = {
        repo_url: repoUrl,
        title,
        branch,
        include_extensions: includeExtensions,
      };
      
      const response = await sourceService.addGithub(data);
      toast.success('GitHub repository added. Indexing started.');
      
      // Background subscribe to show toasts even if not attached to current session
      const sourceId = response.data.source_id || response.data.id;
      if (sourceId) {
        sourceService.subscribeToSourceStatus(sourceId, {}, title || 'GitHub Repo');
      }
      
      return response.data;
    } catch (err) {
      console.error(err);
      toast.error(err?.response?.data?.message || 'Failed to add GitHub repository');
      throw err;
    } finally {
      set({ isUploading: false });
    }
  },

  // Delete a source
  deleteSource: async (sourceId) => {
    try {
      await sourceService.deleteSource(sourceId);
      
      // Optimistically remove from state
      set((state) => ({
        sources: state.sources.filter(s => s.id !== sourceId),
        total: state.total - 1
      }));
      
      toast.success('Source deleted successfully');
    } catch (err) {
      console.error(err);
      toast.error(err?.response?.data?.message || 'Failed to delete source');
      throw err;
    }
  },
  
  // Refresh a single source in the list (useful after SSE completion)
  refreshSingleSource: async (sourceId) => {
    try {
      const response = await sourceService.getSourceById(sourceId);
      const updatedSource = response.data;
      
      set((state) => ({
        sources: state.sources.map(s => s.id === sourceId ? { ...s, ...updatedSource } : s)
      }));
    } catch (err) {
      console.error("Failed to refresh source", err);
    }
  }
}));

export default useSourceStore;
