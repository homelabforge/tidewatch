import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Home, RefreshCw, History, Settings, Info, Waves, User, LogOut } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';

export default function Navigation() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, isAuthenticated, authMode, logout } = useAuth();

  const navItems = [
    { path: '/', label: 'Dashboard', icon: Home },
    { path: '/updates', label: 'Updates', icon: RefreshCw },
    { path: '/history', label: 'History', icon: History },
    { path: '/settings', label: 'Settings', icon: Settings },
    { path: '/about', label: 'About', icon: Info },
  ];

  const handleLogout = async () => {
    await logout();
    navigate('/login', { replace: true });
  };

  // Show user menu only when authenticated AND auth is enabled
  const showUserMenu = isAuthenticated && authMode !== 'none';

  return (
    <nav className="bg-tide-surface border-b border-tide-border">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center">
            <Link to="/" className="flex items-center gap-2">
              <Waves className="w-8 h-8 text-primary" />
              <span className="text-2xl font-bold text-tide-text">
                Tide<span className="text-primary">Watch</span>
              </span>
            </Link>
            <div className="hidden md:block ml-10">
              <div className="flex items-baseline space-x-4">
                {navItems.map((item) => {
                  const Icon = item.icon;
                  const isActive = location.pathname === item.path;

                  return (
                    <Link
                      key={item.path}
                      to={item.path}
                      className={`px-3 py-2 rounded-md text-base font-medium flex items-center gap-2 transition-colors ${
                        isActive
                          ? 'bg-tide-surface-light text-primary'
                          : 'text-tide-text-muted hover:bg-tide-surface-light hover:text-tide-text'
                      }`}
                    >
                      <Icon size={18} />
                      {item.label}
                    </Link>
                  );
                })}
              </div>
            </div>
          </div>

          {/* User Menu - Desktop */}
          {showUserMenu && (
            <div className="hidden md:flex items-center gap-3">
              <div className="flex items-center gap-2 px-3 py-2 text-base font-medium text-tide-text-muted">
                <User size={18} />
                <span>{user?.username}</span>
              </div>
              <button
                onClick={handleLogout}
                className="flex items-center gap-2 px-3 py-2 rounded-md text-base font-medium text-tide-text-muted hover:bg-tide-surface-light hover:text-tide-text transition-colors"
              >
                <LogOut size={18} />
                Logout
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Mobile menu */}
      <div className="md:hidden">
        <div className="px-2 pt-2 pb-3 space-y-1 sm:px-3">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = location.pathname === item.path;

            return (
              <Link
                key={item.path}
                to={item.path}
                className={`block px-3 py-2 rounded-md text-lg font-medium flex items-center gap-2 ${
                  isActive
                    ? 'bg-tide-surface-light text-primary'
                    : 'text-tide-text-muted hover:bg-tide-surface-light hover:text-tide-text'
                }`}
              >
                <Icon size={20} />
                {item.label}
              </Link>
            );
          })}

          {/* User Menu - Mobile */}
          {showUserMenu && (
            <>
              <div className="border-t border-tide-border mt-3 pt-3">
                <div className="px-3 py-2 text-sm text-tide-text-muted flex items-center gap-2">
                  <User size={18} />
                  <span className="font-medium">{user?.username}</span>
                </div>
                <button
                  onClick={handleLogout}
                  className="w-full flex items-center gap-2 px-3 py-2 rounded-md text-lg font-medium text-tide-text-muted hover:bg-tide-surface-light hover:text-tide-text"
                >
                  <LogOut size={20} />
                  Logout
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}
