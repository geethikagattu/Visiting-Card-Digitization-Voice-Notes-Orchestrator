import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CreditCard, Image, Mic, Plus, Send, Square, Trash2, Upload } from 'lucide-react'

type ChatMessage = {
  role: 'assistant' | 'user'
  text: string
}

type ChatSession = {
  id: string
  title: string
  messages: ChatMessage[]
  createdAt: number
  updatedAt: number
  lastSheetRowId?: number
}

type SessionResponse = {
  session_id: string
  message: string
}

type RequestResponse = {
  response?: string
  message?: string
  last_card_data?: {
    name?: string
    company?: string
  }
  last_sheet_row_id?: number
  transcript?: string
}

const STORAGE_KEY = 'visiting-card-chat-sessions'
const DEFAULT_API_BASE_URL = 'https://visiting-card-digitization-voice-notes.onrender.com'
const API_BASE_URL = (import.meta.env.VITE_API_URL ?? DEFAULT_API_BASE_URL).replace(/\/$/, '')

function apiUrl(path: string) {
  return `${API_BASE_URL}${path}`
}

function backendConnectionHint(message: string) {
  return /Backend is unavailable|Could not create a session|Failed to fetch|NetworkError/i.test(message)
    ? ` Make sure the backend is reachable at ${API_BASE_URL || DEFAULT_API_BASE_URL}.`
    : ''
}

function errorMessage(message: string) {
  const punctuation = /[.!?]$/.test(message) ? '' : '.'
  return `${message}${punctuation}${backendConnectionHint(message)}`
}

function defaultMessage(): ChatMessage {
  return { role: 'assistant', text: 'Session ready. Upload a visiting card, then record a voice note for that contact.' }
}

function sessionTitle(session: ChatSession) {
  return session.title || `Contact ${session.id.slice(0, 6)}`
}

async function responseBody(response: Response) {
  const text = await response.text()
  if (!text) return {}

  try {
    return JSON.parse(text)
  } catch {
    return { detail: text }
  }
}

function loadStoredSessions() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as ChatSession[]) : []
  } catch {
    return []
  }
}

export default function App() {
  const [sessions, setSessions] = useState<ChatSession[]>(() => loadStoredSessions())
  const [activeSessionId, setActiveSessionId] = useState(() => loadStoredSessions()[0]?.id ?? '')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [recording, setRecording] = useState(false)
  const imageInput = useRef<HTMLInputElement>(null)
  const audioInput = useRef<HTMLInputElement>(null)
  const mediaRecorder = useRef<MediaRecorder | null>(null)
  const audioChunks = useRef<Blob[]>([])

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === activeSessionId) ?? sessions[0],
    [activeSessionId, sessions],
  )
  const messages = activeSession?.messages ?? []
  const connected = Boolean(activeSession?.id)

  function updateSession(sessionId: string, updater: (session: ChatSession) => ChatSession) {
    setSessions((current) =>
      current.map((session) => (session.id === sessionId ? updater({ ...session, updatedAt: Date.now() }) : session)),
    )
  }

  function appendMessage(sessionId: string, message: ChatMessage) {
    updateSession(sessionId, (session) => ({
      ...session,
      messages: [...session.messages, message],
    }))
  }

  const createSession = useCallback(async () => {
    setError('')
    try {
      const response = await fetch(apiUrl('/chat/session'), { method: 'POST' })
      if (!response.ok) throw new Error('Could not create a session')
      const data = (await responseBody(response)) as SessionResponse
      const now = Date.now()
      const newSession: ChatSession = {
        id: data.session_id,
        title: `Contact ${sessions.length + 1}`,
        messages: [defaultMessage()],
        createdAt: now,
        updatedAt: now,
      }
      setSessions((current) => [newSession, ...current])
      setActiveSessionId(data.session_id)
      setText('')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Backend is unavailable')
    }
  }, [sessions.length])

  useEffect(() => {
    if (sessions.length === 0) void createSession()
  }, [createSession, sessions.length])

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions))
  }, [sessions])

  useEffect(() => {
    if (!activeSessionId && sessions[0]) setActiveSessionId(sessions[0].id)
  }, [activeSessionId, sessions])

  function deleteSession(sessionId: string) {
    setSessions((current) => {
      const remaining = current.filter((session) => session.id !== sessionId)
      if (activeSessionId === sessionId) setActiveSessionId(remaining[0]?.id ?? '')
      return remaining
    })
  }

  async function sendMessage(event: FormEvent) {
    event.preventDefault()
    const content = text.trim()
    if (!content || !activeSession?.id || busy) return

    const sessionId = activeSession.id
    setText('')
    appendMessage(sessionId, { role: 'user', text: content })
    await request(sessionId, `/chat/${sessionId}/message`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: content }),
    })
  }

  async function upload(kind: 'image' | 'audio', file?: File) {
    if (!file || !activeSession?.id || busy) return
    const sessionId = activeSession.id
    const form = new FormData()
    form.append(kind, file)
    appendMessage(sessionId, { role: 'user', text: `Uploaded ${file.name}` })
    await request(sessionId, `/chat/${sessionId}/upload-${kind}`, { method: 'POST', body: form })
  }

  async function startRecording() {
    if (!activeSession?.id || busy || recording) return
    setError('')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream)
      audioChunks.current = []
      mediaRecorder.current = recorder

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunks.current.push(event.data)
      }

      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop())
        const blob = new Blob(audioChunks.current, { type: recorder.mimeType || 'audio/webm' })
        const file = new File([blob], `voice-note-${Date.now()}.webm`, { type: blob.type })
        void upload('audio', file)
      }

      recorder.start()
      setRecording(true)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Microphone access failed')
    }
  }

  function stopRecording() {
    if (mediaRecorder.current?.state === 'recording') {
      mediaRecorder.current.stop()
      setRecording(false)
    }
  }

  async function request(sessionId: string, url: string, options: RequestInit) {
    setBusy(true)
    setError('')
    try {
      const response = await fetch(apiUrl(url), options)
      const data = (await responseBody(response)) as RequestResponse & { detail?: string }
      if (!response.ok) throw new Error(data.detail ?? 'Request failed')

      const reply = data.response ?? data.message ?? 'Done.'
      updateSession(sessionId, (session) => {
        const cardTitle = data.last_card_data?.name || data.last_card_data?.company
        return {
          ...session,
          title: cardTitle || session.title,
          lastSheetRowId: data.last_sheet_row_id ?? session.lastSheetRowId,
          messages: [...session.messages, { role: 'assistant', text: String(reply) }],
        }
      })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Request failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar" aria-label="Chat sessions">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            <CreditCard size={24} />
          </div>
          <div>
            <p>Visiting Card Digitization &</p>
            <h1>Voice Notes Orchestrator</h1>
          </div>
        </div>

        <button className="new-session" onClick={() => void createSession()} type="button">
          <Plus size={18} />
          <span>New session</span>
        </button>

        <nav className="session-list">
          {sessions.map((session) => (
            <button
              className={`session-item ${session.id === activeSession?.id ? 'active' : ''}`}
              key={session.id}
              onClick={() => setActiveSessionId(session.id)}
              type="button"
            >
              <span>
                <strong>{sessionTitle(session)}</strong>
                <small>{session.lastSheetRowId ? `Sheet row ${session.lastSheetRowId}` : 'No card linked yet'}</small>
              </span>
              <Trash2
                aria-label={`Delete ${sessionTitle(session)}`}
                onClick={(event) => {
                  event.stopPropagation()
                  deleteSession(session.id)
                }}
                role="button"
                size={16}
                tabIndex={0}
              />
            </button>
          ))}
        </nav>
      </aside>

      <section className="chat">
        <header className="chat-header">
          <div>
            <p className="eyebrow">Contact assistant</p>
            <h2>{activeSession ? sessionTitle(activeSession) : 'Starting session'}</h2>
          </div>
          <span className={connected ? 'status online' : 'status'}>{connected ? 'Connected' : 'Connecting'}</span>
        </header>

        <div className="messages" aria-live="polite">
          {messages.map((message, index) => (
            <div className={`message ${message.role}`} key={`${message.role}-${index}`}>
              {message.text}
            </div>
          ))}
          {busy && <div className="message assistant">Working...</div>}
        </div>

        {error && <div className="error">{errorMessage(error)}</div>}

        <form onSubmit={sendMessage}>
          <input
            aria-label="Message"
            disabled={!connected || busy}
            onChange={(event) => setText(event.target.value)}
            placeholder="Type a message..."
            type="text"
            value={text}
          />
          <input
            accept="image/*"
            hidden
            onChange={(event) => {
              void upload('image', event.target.files?.[0])
              event.currentTarget.value = ''
            }}
            ref={imageInput}
            type="file"
          />
          <input
            accept="audio/*"
            hidden
            onChange={(event) => {
              void upload('audio', event.target.files?.[0])
              event.currentTarget.value = ''
            }}
            ref={audioInput}
            type="file"
          />
          <button aria-label="Upload card image" disabled={!connected || busy} onClick={() => imageInput.current?.click()} type="button">
            <Image size={20} />
          </button>
          <button aria-label="Upload audio file" disabled={!connected || busy} onClick={() => audioInput.current?.click()} type="button">
            <Upload size={20} />
          </button>
          <button
            aria-label={recording ? 'Stop recording' : 'Record voice note'}
            className={recording ? 'recording' : ''}
            disabled={!connected || busy}
            onClick={recording ? stopRecording : () => void startRecording()}
            type="button"
          >
            {recording ? <Square size={20} /> : <Mic size={20} />}
          </button>
          <button aria-label="Send message" className="primary" disabled={!text.trim() || busy} type="submit">
            <Send size={20} />
          </button>
        </form>
      </section>
    </main>
  )
}
