import Dashboard from '@/pages/dashboard';
import { SettingsPage } from '@/pages/settings';
import {
  Routes,
  Route,
  BrowserRouter as Router,
  Navigate
} from 'react-router-dom';
import { RedirectIfAuthenticated, RequireAuth } from '@/provider/auth';
import { LoginPage } from './pages/login';
import { RegisterPage } from './pages/register';
import { PortalPage } from './pages/portal';
import { ScmOauthCallbackPage } from './pages/scm-oauth-callback';
import { TaskDetailPage } from './pages/task-detail';
import { Toaster } from '@/components/ui/sonner';

export function App() {
  return (
    <Router>
      <Routes>
        <Route element={<RedirectIfAuthenticated />}>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
        </Route>
        <Route element={<RequireAuth />}>
          <Route path="/" element={<Dashboard />}>
            <Route index element={<PortalPage />} />
            <Route path="tasks/:id" element={<TaskDetailPage />} />
          </Route>
          <Route path="/settings" element={<SettingsPage />}></Route>
        </Route>
        <Route path="/oauth/scm/callback" element={<ScmOauthCallbackPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <Toaster />
    </Router>
  );
}

export default App;
