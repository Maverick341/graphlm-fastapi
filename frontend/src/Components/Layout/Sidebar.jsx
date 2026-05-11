import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useLocation, useParams } from 'react-router-dom'
import {
  Check,
  ChevronDown,
  ChevronRight,
  LogOut,
  Monitor,
  Moon,
  Settings,
  Sun,
  User as UserIcon,
  Plus,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  MoreHorizontal,
  Edit2,
  Trash2,
  X
} from 'lucide-react'
import { toast } from 'sonner'
import useAuthStore from '@/store/authStore'
import { useThemeStore, useChatStore } from '@/store'
import AvatarUploadModal from '../Common/Modals/AvatarUploadModal'

const getDisplayName = (user) => user?.firstName || user?.username || 'User'
const DEFAULT_AVATAR_URL = 'https://placehold.co/600x400'

function Sidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const { id: currentSessionId } = useParams()
  
  const { user, logout } = useAuthStore()
  const { theme, resolvedTheme, setTheme } = useThemeStore()
  const { sessions, fetchSessions, createSession, deleteSession, renameSession } = useChatStore()

  // Default to collapsed when viewing a specific chat session
  const [isCollapsed, setIsCollapsed] = useState(true)
  
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const [themeSubmenuOpen, setThemeSubmenuOpen] = useState(false)
  const [topLogoHovered, setTopLogoHovered] = useState(false)
  const [recentMenuOpen, setRecentMenuOpen] = useState(false)
  
  // States for session 3-dot menus
  const [openMenuId, setOpenMenuId] = useState(null)
  const [modalConfig, setModalConfig] = useState({ type: null, session: null })
  const [renameInput, setRenameInput] = useState('')

  const menuRootRef = useRef(null)
  const sessionMenuRef = useRef(null)
  const recentMenuRef = useRef(null)

  const avatarUrl = user?.avatar?.url || DEFAULT_AVATAR_URL
  const displayName = useMemo(() => getDisplayName(user), [user])
  
  const themeOptions = [
    { value: 'light', label: 'Light', icon: Sun },
    { value: 'dark', label: 'Dark', icon: Moon },
    { value: 'system', label: 'System', icon: Monitor },
  ]
  const selectedThemeValue = ['light', 'dark', 'system'].includes(theme) ? theme : 'light'

  // Fetch sessions on mount if not already populated
  useEffect(() => {
    fetchSessions()
  }, [fetchSessions])

  useEffect(() => {
    setUserMenuOpen(false)
    setThemeSubmenuOpen(false)
    setRecentMenuOpen(false)
  }, [location.pathname])

  // Handle outside clicks for user menu
  useEffect(() => {
    const handleOutsideClick = (event) => {
      if (menuRootRef.current && !menuRootRef.current.contains(event.target)) {
        setUserMenuOpen(false)
        setThemeSubmenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleOutsideClick)
    return () => document.removeEventListener('mousedown', handleOutsideClick)
  }, [])

  // Handle outside clicks for recent chats popover
  useEffect(() => {
    const handleOutsideClick = (event) => {
      if (recentMenuRef.current && !recentMenuRef.current.contains(event.target)) {
        setRecentMenuOpen(false)
      }
    }
    if (recentMenuOpen) {
      document.addEventListener('mousedown', handleOutsideClick)
    }
    return () => document.removeEventListener('mousedown', handleOutsideClick)
  }, [recentMenuOpen])

  // Handle outside clicks for session 3-dot menus
  useEffect(() => {
    const handleOutsideMenuClick = (e) => {
      if (sessionMenuRef.current && !sessionMenuRef.current.contains(e.target)) {
        setOpenMenuId(null)
      }
    }
    if (openMenuId) {
      document.addEventListener('mousedown', handleOutsideMenuClick)
    }
    return () => {
      document.removeEventListener('mousedown', handleOutsideMenuClick)
    }
  }, [openMenuId])

  const handleLogout = async () => {
    try {
      await logout()
      toast.success('Logged out successfully')
      navigate('/auth')
    } catch (error) {
      toast.error('Logout failed')
    }
  }

  const handleThemeChange = (nextTheme) => {
    setTheme(nextTheme)
    setThemeSubmenuOpen(false)
  }

  const [avatarModalOpen, setAvatarModalOpen] = useState(false)

  const handleManageAccount = () => {
    setAvatarModalOpen(true)
    setUserMenuOpen(false)
  }

  const handleSettings = () => {
    toast.info('Settings coming soon')
    setUserMenuOpen(false)
  }

  const handleNewChat = async () => {
    try {
      const newSession = await createSession({ title: 'New Chat' })
      navigate(`/dashboard/c/${newSession.id}`)
    } catch (err) {
      // error handled in store
    }
  }

  const openRenameModal = (e, session) => {
    e.stopPropagation()
    setRenameInput(session.title || '')
    setModalConfig({ type: 'rename', session })
    setOpenMenuId(null)
  }

  const openDeleteModal = (e, session) => {
    e.stopPropagation()
    setModalConfig({ type: 'delete', session })
    setOpenMenuId(null)
  }

  const closeModals = () => {
    setModalConfig({ type: null, session: null })
  }

  const confirmRename = async () => {
    if (modalConfig.session && renameInput.trim()) {
      await renameSession(modalConfig.session.id, renameInput.trim())
    }
    closeModals()
  }

  const confirmDelete = async () => {
    if (modalConfig.session) {
      await deleteSession(modalConfig.session.id)
      if (currentSessionId === modalConfig.session.id) {
        navigate('/dashboard')
      }
    }
    closeModals()
  }

  const isDark = resolvedTheme === 'dark'
  const sidebarWidth = isCollapsed ? 'w-[64px]' : 'w-[260px]'

  return (
    <aside
      className={`h-screen flex flex-col shrink-0 border-r transition-all duration-300 ease-in-out ${sidebarWidth} ${
        isDark ? 'bg-[#171717] border-gray-800' : 'bg-gray-50 border-gray-200'
      }`}
      ref={menuRootRef}
    >
      {/* Top Header / Collapse Toggle */}
      <div className="p-3 flex items-center justify-between">
        {/* If Collapsed, hovering shows PanelLeftOpen, else Monitor icon */}
        {isCollapsed ? (
          <button
            onMouseEnter={() => setTopLogoHovered(true)}
            onMouseLeave={() => setTopLogoHovered(false)}
            onClick={() => setIsCollapsed(false)}
            className={`w-10 h-10 flex items-center justify-center rounded-lg transition-colors mx-auto ${
              isDark ? 'hover:bg-[#212121] text-gray-200' : 'hover:bg-gray-200 text-gray-700'
            }`}
          >
            {topLogoHovered ? <PanelLeftOpen className="w-5 h-5" /> : <Monitor className="w-5 h-5" />}
          </button>
        ) : (
          <>
            <div className={`flex items-center justify-center rounded-full w-8 h-8 ml-1 ${isDark ? 'text-white' : 'text-gray-800'}`}>
              <Monitor className="w-6 h-6" />
            </div>
            <button
              onClick={() => setIsCollapsed(true)}
              className={`p-2 rounded-lg transition-colors ${
                isDark ? 'hover:bg-[#212121] text-gray-400' : 'hover:bg-gray-200 text-gray-500'
              }`}
            >
              <PanelLeftClose className="w-5 h-5" />
            </button>
          </>
        )}
      </div>

      {/* New Chat Button Area */}
      {isCollapsed ? (
        <div className="px-3 pb-2 flex justify-center">
          <button
            onClick={handleNewChat}
            className={`w-10 h-10 flex items-center justify-center rounded-lg transition-colors ${
              isDark ? 'hover:bg-[#212121] text-gray-300' : 'hover:bg-gray-200 text-gray-700'
            }`}
            title="New Chat"
          >
            <Plus className="w-5 h-5" />
          </button>
        </div>
      ) : (
        <div className="px-3 pb-2">
          <button
            onClick={handleNewChat}
            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors font-medium text-sm ${
              isDark ? 'bg-[#212121] hover:bg-[#2f2f2f] text-gray-200' : 'bg-white border border-gray-200 hover:bg-gray-100 text-gray-800 shadow-sm'
            }`}
          >
            <Plus className="w-4 h-4" />
            New chat
          </button>
        </div>
      )}

      {/* Main Chat List Area */}
      <div className={`flex-1 px-3 py-2 ${isCollapsed ? '' : 'overflow-y-auto overflow-x-hidden'}`}>
        {!isCollapsed && (
          <>
            <div className={`text-xs font-semibold px-3 py-2 mb-1 uppercase tracking-wider ${isDark ? 'text-gray-500' : 'text-gray-400'}`}>
              Recent Chats
            </div>

            <div className="space-y-1 pb-10">
              {sessions.map(session => (
                <div key={session.id} className="relative group">
                  <button
                    onClick={() => navigate(`/dashboard/c/${session.id}`)}
                    className={`flex items-center gap-3 w-full p-2.5 rounded-lg transition-colors text-sm truncate pr-8 ${
                      session.id === currentSessionId 
                        ? (isDark ? 'bg-[#212121] text-gray-100' : 'bg-gray-200 text-gray-900') 
                        : (isDark ? 'hover:bg-[#212121] text-gray-400' : 'hover:bg-gray-200 text-gray-600')
                    }`}
                  >
                    <MessageSquare className="w-4 h-4 shrink-0" />
                    <span className="truncate flex-1 text-left">{session.title || 'Untitled Chat'}</span>
                  </button>

                  {/* 3-dot menu button, visible on hover */}
                  <button
                    onClick={(e) => { e.stopPropagation(); setOpenMenuId(openMenuId === session.id ? null : session.id); }}
                    className={`absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-md transition-opacity ${openMenuId === session.id ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'} ${isDark ? 'hover:bg-[#3c4043] text-gray-400 hover:text-white' : 'hover:bg-gray-300 text-gray-600 hover:text-gray-900'}`}
                  >
                    <MoreHorizontal className="w-4 h-4" />
                  </button>

                  {/* Dropdown Menu */}
                  {openMenuId === session.id && (
                    <div 
                      ref={sessionMenuRef}
                      className="absolute right-0 top-full mt-1 w-32 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-[#3c4043] shadow-lg py-1 z-50 overflow-hidden"
                    >
                      <button 
                        onClick={(e) => openRenameModal(e, session)}
                        className="w-full text-left px-3 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-white/10 flex items-center gap-2"
                      >
                        <Edit2 className="w-4 h-4" /> Rename
                      </button>
                      <button 
                        onClick={(e) => openDeleteModal(e, session)}
                        className="w-full text-left px-3 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-white/10 flex items-center gap-2"
                      >
                        <Trash2 className="w-4 h-4" /> Delete
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </>
        )}

        {isCollapsed && (
          <div className="flex flex-col items-center gap-2 mt-4 relative">
             <button
               onClick={() => setRecentMenuOpen(!recentMenuOpen)}
               className={`w-10 h-10 flex items-center justify-center rounded-lg transition-colors ${
                 isDark ? 'hover:bg-[#212121] text-gray-400' : 'hover:bg-gray-200 text-gray-600'
               } ${recentMenuOpen ? (isDark ? 'bg-[#212121] text-gray-200' : 'bg-gray-200 text-gray-900') : ''}`}
               title="Recent Chats"
             >
               <MessageSquare className="w-5 h-5" />
             </button>

             {recentMenuOpen && (
               <div 
                 ref={recentMenuRef}
                 className={`absolute left-full top-0 ml-3 w-64 rounded-xl shadow-xl border py-2 z-50 flex flex-col ${
                   isDark ? 'bg-[#2f2f2f] border-gray-700' : 'bg-white border-gray-200'
                 }`}
               >
                 <div className={`px-4 py-3 text-xs font-semibold uppercase tracking-wider ${isDark ? 'text-gray-400' : 'text-gray-500'}`}>
                   Recents
                 </div>
                 
                 <div className="space-y-0.5 pb-2">
                   {sessions.slice(0, 10).map(session => (
                     <div key={session.id} className="relative group px-2">
                       <button
                         onClick={() => navigate(`/dashboard/c/${session.id}`)}
                         className={`flex items-center gap-3 w-full p-2.5 rounded-lg transition-colors text-sm truncate pr-8 ${
                           session.id === currentSessionId 
                             ? (isDark ? 'bg-[#3c4043] text-gray-100' : 'bg-gray-100 text-gray-900') 
                             : (isDark ? 'hover:bg-[#3c4043] text-gray-300' : 'hover:bg-gray-100 text-gray-700')
                         }`}
                       >
                         <span className="truncate flex-1 text-left">{session.title || 'Untitled Chat'}</span>
                       </button>

                       {/* 3-dot menu button */}
                       <button
                         onClick={(e) => { e.stopPropagation(); setOpenMenuId(openMenuId === session.id ? null : session.id); }}
                         className={`absolute right-4 top-1/2 -translate-y-1/2 p-1 rounded-md transition-opacity ${openMenuId === session.id ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'} ${isDark ? 'hover:bg-[#4a4d51] text-gray-400 hover:text-white' : 'hover:bg-gray-200 text-gray-600 hover:text-gray-900'}`}
                       >
                         <MoreHorizontal className="w-4 h-4" />
                       </button>

                       {/* Dropdown Menu inside Recents Popover */}
                       {openMenuId === session.id && (
                         <div 
                           ref={sessionMenuRef}
                           className="absolute right-8 top-full -mt-2 w-32 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-[#3c4043] shadow-lg py-1 z-60 overflow-hidden"
                         >
                           <button 
                             onClick={(e) => openRenameModal(e, session)}
                             className="w-full text-left px-3 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-white/10 flex items-center gap-2"
                           >
                             <Edit2 className="w-4 h-4" /> Rename
                           </button>
                           <button 
                             onClick={(e) => openDeleteModal(e, session)}
                             className="w-full text-left px-3 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-white/10 flex items-center gap-2"
                           >
                             <Trash2 className="w-4 h-4" /> Delete
                           </button>
                         </div>
                       )}
                     </div>
                   ))}
                 </div>
               </div>
             )}
          </div>
        )}
      </div>

      {/* Bottom User Menu */}
      <div className="p-3">
        <div className="relative w-full">
          {/* Dropdown Menu (Opens Upward) */}
          {userMenuOpen && (
            <div className={`absolute bottom-full mb-2 rounded-xl shadow-xl border py-1.5 z-50 ${
              isCollapsed ? 'left-full ml-3 w-[240px]' : 'left-0 w-[240px]'
            } ${
              isDark ? 'bg-[#212121] border-gray-700 text-gray-200' : 'bg-white border-gray-200 text-gray-800'
            }`}>
              
              {/* Email Display */}
              <div className={`px-4 py-3 text-sm truncate border-b ${isDark ? 'border-gray-700' : 'border-gray-100'}`}>
                {user?.email || 'No email available'}
              </div>

              {/* Settings */}
              <button
                onClick={handleSettings}
                className={`w-full flex items-center gap-3 px-4 py-3 text-sm transition-colors ${
                  isDark ? 'hover:bg-[#2f2f2f]' : 'hover:bg-gray-100'
                }`}
              >
                <Settings className="w-4 h-4" />
                Settings
              </button>

              {/* Profile */}
              <button
                onClick={handleManageAccount}
                className={`w-full flex items-center gap-3 px-4 py-3 text-sm transition-colors ${
                  isDark ? 'hover:bg-[#2f2f2f]' : 'hover:bg-gray-100'
                }`}
              >
                <UserIcon className="w-4 h-4" />
                Profile
              </button>

              {/* Theme Submenu Toggle */}
              <div 
                className={`relative w-full flex items-center justify-between px-4 py-3 text-sm transition-colors cursor-pointer ${
                  isDark ? 'hover:bg-[#2f2f2f]' : 'hover:bg-gray-100'
                }`}
                onClick={(e) => {
                  e.stopPropagation()
                  setThemeSubmenuOpen(!themeSubmenuOpen)
                }}
              >
                <div className="flex items-center gap-3">
                  <Sun className="w-4 h-4" />
                  Theme
                </div>
                <ChevronRight className="w-4 h-4" />

                {/* Theme Submenu */}
                {themeSubmenuOpen && (
                  <div className={`absolute bottom-0 rounded-xl shadow-xl border py-1.5 z-50 w-[180px] ${
                    isCollapsed ? 'left-full ml-1' : 'left-full ml-1'
                  } ${
                    isDark ? 'bg-[#212121] border-gray-700' : 'bg-white border-gray-200'
                  }`}>
                    {themeOptions.map((option) => {
                      const Icon = option.icon
                      const isSelected = selectedThemeValue === option.value
                      return (
                        <button
                          key={option.value}
                          onClick={() => handleThemeChange(option.value)}
                          className={`w-full flex items-center justify-between px-4 py-2 text-sm transition-colors ${
                            isDark ? 'hover:bg-[#2f2f2f]' : 'hover:bg-gray-100'
                          }`}
                        >
                          <div className="flex items-center gap-3">
                            <Icon className="w-4 h-4" />
                            {option.label}
                          </div>
                          {isSelected && <Check className="w-4 h-4" />}
                        </button>
                      )
                    })}
                  </div>
                )}
              </div>

              {/* Logout */}
              <button
                onClick={handleLogout}
                className={`w-full flex items-center gap-3 px-4 py-3 text-sm transition-colors border-t ${
                  isDark ? 'hover:bg-[#2f2f2f] border-gray-700 text-red-400' : 'hover:bg-gray-100 border-gray-100 text-red-600'
                }`}
              >
                <LogOut className="w-4 h-4" />
                Log out
              </button>
            </div>
          )}

          {/* User Button (Avatar & Name) */}
          <button
            onClick={() => setUserMenuOpen(!userMenuOpen)}
            className={`w-full flex items-center gap-3 p-2 rounded-xl transition-colors ${
              isDark ? 'hover:bg-[#212121]' : 'hover:bg-gray-200'
            } ${isCollapsed ? 'justify-center' : 'justify-start'}`}
          >
            <div className="w-8 h-8 rounded-full overflow-hidden shrink-0 border border-gray-200 dark:border-gray-700">
              <img
                src={avatarUrl}
                alt="Avatar"
                className="w-full h-full object-cover"
              />
            </div>
            {!isCollapsed && (
              <>
                <span className={`text-sm font-medium truncate flex-1 text-left ${isDark ? 'text-gray-200' : 'text-gray-800'}`}>
                  {displayName}
                </span>
                <ChevronDown className="w-4 h-4 text-gray-500" />
              </>
            )}
          </button>
        </div>
      </div>

      <AvatarUploadModal
        isOpen={avatarModalOpen}
        onClose={() => setAvatarModalOpen(false)}
      />

      {/* Rename / Delete Modals */}
      {modalConfig.type && (
        <div className="fixed inset-0 z-100 flex items-center justify-center bg-black/50 p-4">
          <div className="bg-white dark:bg-[#303134] border border-gray-200 dark:border-gray-700 rounded-2xl w-full max-w-md shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-200">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 dark:border-gray-800">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                {modalConfig.type === 'rename' ? 'Rename Chat' : 'Delete Chat'}
              </h3>
              <button onClick={closeModals} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
                <X className="w-5 h-5" />
              </button>
            </div>
            
            <div className="px-6 py-6">
              {modalConfig.type === 'rename' ? (
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    Chat Title
                  </label>
                  <input
                    type="text"
                    value={renameInput}
                    onChange={(e) => setRenameInput(e.target.value)}
                    autoFocus
                    onKeyDown={(e) => e.key === 'Enter' && confirmRename()}
                    className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-gray-50 dark:bg-[#212121] text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:outline-none"
                    placeholder="Enter chat title..."
                  />
                </div>
              ) : (
                <p className="text-gray-600 dark:text-gray-300">
                  Are you sure you want to delete <span className="font-semibold text-gray-900 dark:text-white">"{modalConfig.session.title}"</span>? This action cannot be undone.
                </p>
              )}
            </div>

            <div className="px-6 py-4 bg-gray-50 dark:bg-[#212121] border-t border-gray-100 dark:border-gray-800 flex justify-end gap-3">
              <button
                onClick={closeModals}
                className="px-4 py-2 rounded-lg font-medium text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-[#3c4043] transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={modalConfig.type === 'rename' ? confirmRename : confirmDelete}
                className={`px-4 py-2 rounded-lg font-medium text-sm text-white transition-colors ${
                  modalConfig.type === 'rename'
                    ? 'bg-blue-600 hover:bg-blue-700'
                    : 'bg-red-600 hover:bg-red-700'
                }`}
              >
                {modalConfig.type === 'rename' ? 'Save' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </aside>
  )
}

export default Sidebar
