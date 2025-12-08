import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { settingsApi } from '../services/api';

type Theme = 'light' | 'dark';

interface ThemeContextType {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  isLoading: boolean;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

interface ThemeProviderProps {
  children: ReactNode;
}

export function ThemeProvider({ children }: ThemeProviderProps) {
  const [theme, setThemeState] = useState<Theme>('dark');
  const [isLoading, setIsLoading] = useState(true);

  // Initialize theme on mount
  useEffect(() => {
    const initializeTheme = async () => {
      try {
        // 1. Check localStorage first (instant)
        const localTheme = localStorage.getItem('theme') as Theme | null;

        if (localTheme && (localTheme === 'light' || localTheme === 'dark')) {
          applyTheme(localTheme);
          setThemeState(localTheme);
        }

        // 2. Sync with database (for cross-device consistency)
        const data = await settingsApi.get('theme');
        const dbTheme = data.value as Theme;

        // If database theme differs from local, use database (cross-device sync)
        if (dbTheme && dbTheme !== localTheme) {
          applyTheme(dbTheme);
          setThemeState(dbTheme);
          localStorage.setItem('theme', dbTheme);
        }
      } catch (error) {
        console.warn('Failed to load theme from database:', error);
        // Continue with localStorage or default theme
      } finally {
        setIsLoading(false);
      }
    };

    initializeTheme();
  }, []);

  // Apply theme to DOM
  const applyTheme = (newTheme: Theme) => {
    const html = document.documentElement;

    if (newTheme === 'light') {
      html.classList.add('light');
      html.classList.remove('dark');
    } else {
      html.classList.add('dark');
      html.classList.remove('light');
    }
  };

  // Set theme with dual persistence
  const setTheme = async (newTheme: Theme) => {
    // 1. Apply immediately to DOM
    applyTheme(newTheme);
    setThemeState(newTheme);

    // 2. Save to localStorage (instant)
    localStorage.setItem('theme', newTheme);

    // 3. Save to database (async, for cross-device sync)
    try {
      await settingsApi.update('theme', newTheme);
    } catch (error) {
      console.warn('Failed to save theme to database:', error);
      // Not critical - theme is still saved locally
    }
  };

  const value: ThemeContextType = {
    theme,
    setTheme,
    isLoading,
  };

  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useTheme(): ThemeContextType {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}
