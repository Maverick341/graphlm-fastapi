import React, { useState, useEffect, useRef } from 'react';
import { X, UploadCloud, Library, FileText, FileUp, Loader2, GitBranch, Database, File } from 'lucide-react';
import useSourceStore from '@/store/sourceStore';
import useChatStore from '@/store/chatStore';

export default function AddSourceModal({ isOpen, onClose, currentSession }) {
  const { attachSources } = useChatStore();
  const [activeTab, setActiveTab] = useState('upload'); // 'upload', 'github', 'library'

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
  
  // Store
  const { uploadDocument, addGithub, fetchSources, sources, isLoadingSources, isUploading, autoAttach, setAutoAttach } = useSourceStore();

  // Upload State
  const [selectedFile, setSelectedFile] = useState(null);
  const [uploadTitle, setUploadTitle] = useState('');
  const fileInputRef = useRef(null);

  // GitHub State
  const [repoUrl, setRepoUrl] = useState('');
  const [repoTitle, setRepoTitle] = useState('');
  const [branch, setBranch] = useState('main');

  // Fetch sources when library tab is opened
  useEffect(() => {
    if (isOpen && activeTab === 'library') {
      fetchSources(0, 50);
    }
  }, [isOpen, activeTab, fetchSources]);

  // Reset state when modal closes
  useEffect(() => {
    if (!isOpen) {
      setSelectedFile(null);
      setUploadTitle('');
      setRepoUrl('');
      setRepoTitle('');
      setBranch('main');
      setActiveTab('upload');
    }
  }, [isOpen]);

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (file) {
      setSelectedFile(file);
      if (!uploadTitle) {
        // Auto-fill title with extension
        setUploadTitle(file.name);
      }
    }
  };

  const handleUploadSubmit = async (e) => {
    e.preventDefault();
    if (!selectedFile) return;
    try {
      const res = await uploadDocument(selectedFile, uploadTitle || selectedFile.name);
      if (autoAttach && currentSession) {
        const sourceId = res.data?.source_id || res.source_id;
        if (sourceId) {
          await attachSources(currentSession.id, [sourceId]);
        }
      }
      onClose();
    } catch (error) {
      // Error is handled by store toast
    }
  };

  const handleGithubSubmit = async (e) => {
    e.preventDefault();
    if (!repoUrl) return;
    try {
      // Extract title from URL if not provided
      let finalTitle = repoTitle;
      if (!finalTitle) {
        const parts = repoUrl.split('/');
        finalTitle = parts[parts.length - 1] || 'GitHub Repo';
      }
      const res = await addGithub(repoUrl, finalTitle, branch, []);
      if (autoAttach && currentSession) {
        const sourceId = res.data?.source_id || res.source_id;
        if (sourceId) {
          await attachSources(currentSession.id, [sourceId]);
        }
      }
      onClose();
    } catch (error) {
      // Error is handled by store toast
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="w-full max-w-2xl bg-white dark:bg-[#141414] border border-gray-200 dark:border-gray-800 rounded-2xl shadow-[0_0_50px_-12px_rgba(0,0,0,0.8)] dark:shadow-[0_0_50px_-12px_rgba(0,0,0,0.8)] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-[#1a1a1a]">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-50 dark:bg-blue-500/10 text-blue-500 dark:text-blue-400 rounded-lg">
              <Database className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Add Knowledge Source</h2>
              <p className="text-xs text-gray-500 dark:text-gray-400">Connect documents and repositories to the graph</p>
            </div>
          </div>
          <button 
            onClick={onClose}
            className="p-2 text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-white rounded-lg hover:bg-gray-200 dark:hover:bg-gray-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Navigation */}
        <div className="flex px-6 border-b border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-[#1a1a1a]">
          <button
            onClick={() => setActiveTab('upload')}
            className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'upload' ? 'border-blue-500 text-blue-600 dark:text-blue-400' : 'border-transparent text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200'
            }`}
          >
            <FileUp className="w-4 h-4" /> Upload Document
          </button>
          <button
            onClick={() => setActiveTab('github')}
            className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'github' ? 'border-blue-500 text-blue-600 dark:text-blue-400' : 'border-transparent text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200'
            }`}
          >
            <GitBranch className="w-4 h-4" /> GitHub Repository
          </button>
          <button
            onClick={() => setActiveTab('library')}
            className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'library' ? 'border-blue-500 text-blue-600 dark:text-blue-400' : 'border-transparent text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200'
            }`}
          >
            <Library className="w-4 h-4" /> Your Library
          </button>
        </div>

        {/* Auto-Attach Toggle */}
        <div className="flex items-center justify-end px-6 py-2 bg-gray-50 dark:bg-[#1a1a1a] border-b border-gray-200 dark:border-gray-800">
          <label className="flex items-center gap-2 cursor-pointer text-sm text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-white transition-colors">
            <input 
              type="checkbox" 
              checked={autoAttach} 
              onChange={(e) => setAutoAttach(e.target.checked)} 
              className="rounded border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 text-blue-500 focus:ring-blue-500 focus:ring-offset-white dark:focus:ring-offset-gray-900" 
            />
            Auto-attach to current chat
          </label>
        </div>

        {/* Content Area */}
        <div className="p-6 bg-white dark:bg-[#141414] min-h-[320px]">
          {/* TAB: UPLOAD */}
          {activeTab === 'upload' && (
            <form onSubmit={handleUploadSubmit} className="flex flex-col h-full animate-in slide-in-from-right-4 duration-300">
              {!selectedFile ? (
                <div 
                  className="flex-1 border-2 border-dashed border-gray-300 dark:border-gray-700 rounded-xl flex flex-col items-center justify-center p-8 hover:border-blue-500/50 hover:bg-blue-50 dark:hover:bg-blue-500/5 transition-all cursor-pointer group"
                  onClick={() => fileInputRef.current?.click()}
                >
                  <div className="w-16 h-16 bg-gray-100 dark:bg-gray-800 group-hover:bg-blue-100 dark:group-hover:bg-blue-500/20 rounded-full flex items-center justify-center mb-4 transition-colors">
                    <UploadCloud className="w-8 h-8 text-gray-500 dark:text-gray-400 group-hover:text-blue-500 dark:group-hover:text-blue-400 transition-colors" />
                  </div>
                  <h3 className="text-gray-900 dark:text-white font-medium mb-1">Click or drag file to upload</h3>
                  <p className="text-sm text-gray-500 text-center max-w-xs">
                    Supported formats: PDF, DOCX, TXT, MD. Maximum file size 50MB.
                  </p>
                  <input 
                    type="file" 
                    className="hidden" 
                    ref={fileInputRef}
                    accept=".pdf,.docx,.txt,.md"
                    onChange={handleFileChange}
                  />
                </div>
              ) : (
                <div className="flex-1 flex flex-col gap-5">
                  <div className="p-4 border border-blue-200 dark:border-blue-500/30 bg-blue-50 dark:bg-blue-500/5 rounded-xl flex items-start gap-4">
                    <div className="p-3 bg-white dark:bg-gray-800 rounded-lg flex items-center justify-center border border-gray-100 dark:border-transparent">
                      <FileIcon filename={selectedFile.name} className="w-8 h-8 shrink-0" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-gray-500 dark:text-gray-400 mb-1">Selected File</p>
                      <p className="text-gray-900 dark:text-white font-medium truncate">{selectedFile.name}</p>
                      <p className="text-xs text-gray-500 mt-1">{(selectedFile.size / 1024 / 1024).toFixed(2)} MB</p>
                    </div>
                    <button 
                      type="button"
                      onClick={() => setSelectedFile(null)}
                      className="text-gray-500 hover:text-red-500 dark:text-gray-400 dark:hover:text-red-400 p-1"
                    >
                      <X className="w-5 h-5" />
                    </button>
                  </div>
                  
                  {/* <div className="flex flex-col gap-2">
                    <label className="text-sm font-medium text-gray-300">Document Title</label>
                    <input 
                      type="text" 
                      value={uploadTitle}
                      onChange={(e) => setUploadTitle(e.target.value)}
                      placeholder="Give this document a readable name"
                      className="w-full bg-[#1a1a1a] border border-gray-700 focus:border-blue-500 rounded-lg px-4 py-2.5 text-white outline-none transition-colors"
                      required
                    />
                  </div> */}
                </div>
              )}

              <div className="mt-6 flex justify-end gap-3 pt-4 border-t border-gray-200 dark:border-gray-800/50">
                <button 
                  type="button" 
                  onClick={onClose}
                  className="px-5 py-2.5 text-sm font-medium text-gray-600 hover:text-gray-900 hover:bg-gray-100 dark:text-gray-300 dark:hover:text-white dark:hover:bg-gray-800 rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button 
                  type="submit"
                  disabled={!selectedFile || isUploading}
                  className="flex items-center gap-2 px-6 py-2.5 text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                >
                  {isUploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <UploadCloud className="w-4 h-4" />}
                  {isUploading ? 'Uploading...' : 'Upload & Index'}
                </button>
              </div>
            </form>
          )}

          {/* TAB: GITHUB */}
          {activeTab === 'github' && (
            <form onSubmit={handleGithubSubmit} className="flex flex-col h-full animate-in slide-in-from-right-4 duration-300">
              <div className="flex-1 flex flex-col gap-4">
                <div className="flex flex-col gap-2">
                  <label className="text-sm font-medium text-gray-700 dark:text-gray-300">Repository URL</label>
                  <div className="relative">
                    <GitBranch className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400 dark:text-gray-500" />
                    <input 
                      type="url" 
                      value={repoUrl}
                      onChange={(e) => setRepoUrl(e.target.value)}
                      placeholder="https://github.com/owner/repo"
                      className="w-full bg-gray-50 dark:bg-[#1a1a1a] border border-gray-300 dark:border-gray-700 focus:border-blue-500 rounded-lg pl-10 pr-4 py-2.5 text-gray-900 dark:text-white outline-none transition-colors placeholder:text-gray-400"
                      required
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div className="flex flex-col gap-2">
                    <label className="text-sm font-medium text-gray-700 dark:text-gray-300">Title (Optional)</label>
                    <input 
                      type="text" 
                      value={repoTitle}
                      onChange={(e) => setRepoTitle(e.target.value)}
                      placeholder="Custom name"
                      className="w-full bg-gray-50 dark:bg-[#1a1a1a] border border-gray-300 dark:border-gray-700 focus:border-blue-500 rounded-lg px-4 py-2.5 text-gray-900 dark:text-white outline-none transition-colors placeholder:text-gray-400"
                    />
                  </div>
                  <div className="flex flex-col gap-2">
                    <label className="text-sm font-medium text-gray-700 dark:text-gray-300">Branch</label>
                    <div className="relative">
                      <GitBranch className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 dark:text-gray-500" />
                      <input 
                        type="text" 
                        value={branch}
                        onChange={(e) => setBranch(e.target.value)}
                        placeholder="main"
                        className="w-full bg-gray-50 dark:bg-[#1a1a1a] border border-gray-300 dark:border-gray-700 focus:border-blue-500 rounded-lg pl-9 pr-4 py-2.5 text-gray-900 dark:text-white outline-none transition-colors placeholder:text-gray-400"
                      />
                    </div>
                  </div>
                </div>
              </div>

              <div className="mt-6 flex justify-end gap-3 pt-4 border-t border-gray-200 dark:border-gray-800/50">
                <button 
                  type="button" 
                  onClick={onClose}
                  className="px-5 py-2.5 text-sm font-medium text-gray-600 hover:text-gray-900 hover:bg-gray-100 dark:text-gray-300 dark:hover:text-white dark:hover:bg-gray-800 rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button 
                  type="submit"
                  disabled={!repoUrl || isUploading}
                  className="flex items-center gap-2 px-6 py-2.5 text-sm font-medium bg-gray-900 dark:bg-white text-white dark:text-black hover:bg-gray-800 dark:hover:bg-gray-200 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                >
                  {isUploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <GitBranch className="w-4 h-4" />}
                  {isUploading ? 'Connecting...' : 'Connect Repository'}
                </button>
              </div>
            </form>
          )}

          {/* TAB: LIBRARY */}
          {activeTab === 'library' && (
            <div className="flex flex-col h-full animate-in slide-in-from-right-4 duration-300 max-h-[400px]">
              {isLoadingSources ? (
                <div className="flex-1 flex items-center justify-center py-12">
                  <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
                </div>
              ) : sources.length === 0 ? (
                <div className="flex-1 flex flex-col items-center justify-center py-12 text-center">
                  <Library className="w-12 h-12 text-gray-400 dark:text-gray-600 mb-3" />
                  <h3 className="text-gray-900 dark:text-white font-medium mb-1">Your library is empty</h3>
                  <p className="text-sm text-gray-500 max-w-sm">
                    You haven't uploaded any documents or connected any repositories yet.
                  </p>
                </div>
              ) : (
                <div className="flex-1 overflow-y-auto pr-2 space-y-2 custom-scrollbar">
                  {sources.map(source => {
                    const isAttached = currentSession?.sources?.some(s => s.id === source.id);
                    return (
                    <div key={source.id} className="flex items-center justify-between p-3 bg-gray-50 dark:bg-[#1a1a1a] border border-gray-200 dark:border-gray-800 rounded-xl hover:border-gray-300 dark:hover:border-gray-600 transition-colors">
                      <div className="flex items-center gap-3">
                        <div className="p-2 bg-white dark:bg-gray-800 rounded-lg border border-gray-100 dark:border-transparent">
                          {source.type === 'github' ? (
                            <GitBranch className="w-5 h-5 text-gray-500 dark:text-gray-300" />
                          ) : (
                            <File className="w-5 h-5 text-blue-500 dark:text-blue-400" />
                          )}
                        </div>
                        <div>
                          <p className="text-sm font-medium text-gray-900 dark:text-white">{source.title}</p>
                          <p className="text-xs text-gray-500 capitalize">{source.type} • {source.status}</p>
                        </div>
                      </div>
                      <button 
                        onClick={async () => {
                          if (currentSession && !isAttached) {
                            await attachSources(currentSession.id, [source.id]);
                            onClose();
                          }
                        }}
                        disabled={isAttached}
                        className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                          isAttached 
                            ? 'text-gray-400 dark:text-gray-500 bg-gray-100 dark:bg-gray-800/50 cursor-not-allowed' 
                            : 'text-gray-700 bg-white border border-gray-200 hover:bg-gray-50 dark:border-transparent dark:text-gray-300 dark:bg-gray-800 dark:hover:bg-gray-700 dark:hover:text-white'
                        }`}
                      >
                        {isAttached ? 'Attached' : 'Attach'}
                      </button>
                    </div>
                  )})}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
