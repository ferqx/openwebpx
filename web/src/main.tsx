import { createRoot } from 'react-dom/client';
import { scan } from 'react-scan';

import './index.css';
import App from './App.tsx';
import { AuthProvider } from './provider/auth.tsx';
import { ThemeProvider } from './components/theme-provider.tsx';
import { TooltipProvider } from './components/ui/tooltip.tsx';

if (import.meta.env.DEV) {
  scan({
    enabled: true
  });
}

createRoot(document.getElementById('root')!).render(
  <ThemeProvider
    attribute="class"
    defaultTheme="system"
    enableSystem
    disableTransitionOnChange
  >
    <TooltipProvider>
      <AuthProvider>
        <App />
      </AuthProvider>
    </TooltipProvider>
  </ThemeProvider>
);
