/**
 * Application shell — providers and route table (brief §16, §20).
 *
 * Routing rules in one place:
 * * `/login`, `/register` — public (redirect home when already signed in),
 * * everything else — under `AppLayout`, requiring a session (`RequireAuth`).
 *
 * Pages never import the router config; they use `useNavigate`/`useParams`.
 */

import { useEffect } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import { ThemeProvider } from './context/ThemeContext'
import { ToastProvider, useToast } from './context/ToastContext'
import { describeError } from './services'

import ErrorBoundary from './components/ErrorBoundary'
import AppLayout from './layouts/AppLayout'
import LoginPage from './pages/Auth'
import DashboardPage from './pages/Dashboard'
import DocumentsPage from './pages/Documents'
import DocumentDetailPage from './pages/DocumentDetail'
import OcrReviewPage from './pages/OcrReview'
import SearchPage from './pages/Search'
import ChatPage from './pages/Chat'
import GraphPage from './pages/Graph'
import FlashcardsPage from './pages/Flashcards'
import QuizPage from './pages/Quiz'
import AnalyticsPage from './pages/Analytics'
import ComparePage from './pages/Compare'
import ResearchPage from './pages/Research'
import SettingsPage from './pages/Settings'
import { LoadingBlock } from './components/Feedback'

/** Guard for authenticated routes: boot check, redirect, or render. */
function RequireAuth({ children }) {
  const { user, booting } = useAuth()
  if (booting) {
    return (
      <div className="kg-page kg-text-center">
        <LoadingBlock message="Checking your session…" />
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  return children
}

/** Guard the other way: signed-in users skip login/register. */
function PublicOnly({ children }) {
  const { user, booting } = useAuth()
  if (booting) {
    return (
      <div className="kg-page kg-text-center">
        <LoadingBlock message="Checking your session…" />
      </div>
    )
  }
  if (user) return <Navigate to="/" replace />
  return children
}

/** Global safety net: unhandled promise rejections surface as toasts. */
function ErrorBridge({ children }) {
  const toast = useToast()
  const location = useLocation()
  const navigate = useNavigate()

  useEffect(() => {
    function onUnhandled(event) {
      const described = describeError(event?.reason)
      if (described.code === 'unauthorized' && location.pathname !== '/login') {
        navigate('/login', { replace: true })
      }
      toast.error(described.title, described.hint)
    }
    window.addEventListener('unhandledrejection', onUnhandled)
    return () => window.removeEventListener('unhandledrejection', onUnhandled)
  }, [toast, location.pathname, navigate])

  return children
}

export default function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <AuthProvider>
          <ErrorBridge>
            <ErrorBoundary>
            <Routes>
              <Route
                path="/login"
                element={
                  <PublicOnly>
                    <LoginPage />
                  </PublicOnly>
                }
              />
              <Route
                path="/register"
                element={
                  <PublicOnly>
                    <LoginPage mode="register" />
                  </PublicOnly>
                }
              />
              <Route
                element={
                  <RequireAuth>
                    <AppLayout />
                  </RequireAuth>
                }
              >
                <Route index element={<DashboardPage />} />
                <Route path="documents" element={<DocumentsPage />} />
                <Route path="documents/:documentId" element={<DocumentDetailPage />} />
                <Route path="documents/:documentId/ocr" element={<OcrReviewPage />} />
                <Route path="search" element={<SearchPage />} />
                <Route path="chat" element={<ChatPage />} />
                <Route path="graph" element={<GraphPage />} />
                <Route path="flashcards" element={<FlashcardsPage />} />
                <Route path="quiz" element={<QuizPage />} />
                <Route path="analytics" element={<AnalyticsPage />} />
                <Route path="compare" element={<ComparePage />} />
                <Route path="research" element={<ResearchPage />} />
                <Route path="settings" element={<SettingsPage />} />
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
            </ErrorBoundary>
          </ErrorBridge>
        </AuthProvider>
      </ToastProvider>
    </ThemeProvider>
  )
}