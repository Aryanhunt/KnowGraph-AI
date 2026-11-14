/**
 * Auth page — login and registration on one screen (mode prop).
 *
 * Shows backend validation and auth errors verbatim (never genericised away),
 * including the password policy explanation.
 */

import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../context/ToastContext'
import Button from '../components/Button'
import Card, { CardHeader } from '../components/Card'
import { Input } from '../components/Input'
import { Alert } from '../components/Feedback'
import './Auth.css'

export default function Auth({ mode = 'login' }) {
  const isRegister = mode === 'register'
  const navigate = useNavigate()
  const { login, register } = useAuth()
  const { fromError } = useToast()

  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState(null)

  async function onSubmit(event) {
    event.preventDefault()
    setBusy(true)
    setProblem(null)
    try {
      if (isRegister) {
        await register({ full_name: fullName, email, password })
      } else {
        await login({ email, password })
      }
      navigate('/', { replace: true })
    } catch (error) {
      setProblem(error)
      fromError(error)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="kg-auth">
      <div className="kg-auth__card">
        <div className="kg-auth__brand">
          <span className="kg-navbar__logo" aria-hidden="true">
            ◉
          </span>
          <span className="kg-navbar__name">KnowGraph AI</span>
        </div>

        <Card large>
          <CardHeader
            title={isRegister ? 'Create your account' : 'Welcome back'}
            subtitle={
              isRegister
                ? 'Your documents stay on your machine — always.'
                : 'Sign in to continue studying your own knowledge.'
            }
          />

          <form className="kg-stack" onSubmit={onSubmit} noValidate>
            {isRegister ? (
              <Input
                label="Full name"
                name="fullName"
                value={fullName}
                onChange={(event) => setFullName(event.target.value)}
                autoComplete="name"
                required
              />
            ) : null}

            <Input
              label="Email"
              name="email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
              required
            />

            <Input
              label="Password"
              name="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete={isRegister ? 'new-password' : 'current-password'}
              help={isRegister ? 'At least 8 characters, and not a common password.' : undefined}
              required
            />

            {problem?.hint ? <Alert tone="danger" title={problem.message} hint={problem.hint} /> : null}
            {!problem?.hint && problem?.message ? (
              <Alert tone="danger" title={problem.message} />
            ) : null}

            <Button type="submit" size="lg" block loading={busy} disabled={busy}>
              {isRegister ? 'Create account' : 'Sign in'}
            </Button>
          </form>

          <p className="kg-text-sm kg-text-center" style={{ marginTop: 'var(--kg-space-4)' }}>
            {isRegister ? (
              <>
                Already registered? <Link to="/login">Sign in</Link>
              </>
            ) : (
              <>
                New to KnowGraph AI? <Link to="/register">Create an account</Link>
              </>
            )}
          </p>
        </Card>
      </div>
    </div>
  )
}