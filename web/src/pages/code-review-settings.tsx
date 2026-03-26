import { Navigate } from 'react-router-dom';

export default function CodeReviewSettingsPage() {
  return <Navigate to="/settings?tab=code-review" replace />;
}
