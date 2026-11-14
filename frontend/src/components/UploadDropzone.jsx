/**
 * UploadDropzone — drag-and-drop file upload with real progress (brief §4).
 *
 * Reports *upload* progress first (bytes sent) and then hands the created
 * document to the caller, which polls the backend for *processing* progress.
 * Accepted file types come from the backend (`/api/system/supported-types`), so
 * the drop zone never disagrees with the server about what can be uploaded.
 */

import { useRef, useState } from 'react'
import Button from './Button'
import ProgressBar from './ProgressBar'
import { Input } from './Input'
import { documentsApi } from '../services'
import { useToast } from '../context/ToastContext'
import './UploadDropzone.css'

export default function UploadDropzone({ onUploaded, supportedTypes = [], subject: defaultSubject = '' }) {
  const fileRef = useRef(null)
  const { fromError, success } = useToast()
  const [dragging, setDragging] = useState(false)
  const [subject, setSubject] = useState(defaultSubject)
  const [uploads, setUploads] = useState([]) // [{ id, name, progress, state, error }]

  function startUpload(file) {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    setUploads((current) => [...current, { id, name: file.name, progress: 0, state: 'uploading' }])

    documentsApi
      .upload(file, {
        subject,
        onProgress: (progress) =>
          setUploads((current) =>
            current.map((item) => (item.id === id ? { ...item, progress } : item)),
          ),
      })
      .then(({ data }) => {
        setUploads((current) =>
          current.map((item) =>
            item.id === id ? { ...item, progress: 100, state: 'queued', document: data } : item,
          ),
        )
        success(`"${file.name}" uploaded — processing started.`)
        onUploaded?.(data)
      })
      .catch((error) => {
        setUploads((current) =>
          current.map((item) =>
            item.id === id ? { ...item, state: 'failed', error: error?.message } : item,
          ),
        )
        fromError(error, `Could not upload "${file.name}"`)
      })
  }

  function handleFiles(fileList) {
    const files = Array.from(fileList || [])
    if (!files.length) return
    files.forEach(startUpload)
  }

  const acceptHint = supportedTypes.length
    ? supportedTypes.map((type) => `.${type.extension || type}`).join(', ')
    : '.pdf, .png, .jpg, .jpeg, .webp, .docx, .txt, .md'

  return (
    <div className="kg-upload">
      <div className="kg-row-wrap">
        <div className="kg-grow" style={{ minWidth: 220 }}>
          <Input
            label="Subject (optional)"
            name="upload-subject"
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
            placeholder="e.g. DBMS, Computer Networks"
            help="Tags every uploaded file so “Chat With Subject” can use it."
          />
        </div>
      </div>

      <div
        className={`kg-upload__zone${dragging ? ' kg-upload__zone--dragging' : ''}`}
        role="button"
        tabIndex={0}
        aria-label="Upload documents"
        onClick={() => fileRef.current?.click()}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') fileRef.current?.click()
        }}
        onDragOver={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragging(false)
          handleFiles(event.dataTransfer.files)
        }}
      >
        <input
          ref={fileRef}
          type="file"
          multiple
          className="kg-visually-hidden"
          aria-hidden="true"
          tabIndex={-1}
          onChange={(event) => {
            handleFiles(event.target.files)
            event.target.value = ''
          }}
        />
        <div className="kg-upload__icon" aria-hidden="true">
          ⬆
        </div>
        <div>
          <strong>Drag &amp; drop files here, or click to browse</strong>
          <div className="kg-text-xs kg-text-muted">Accepted: {acceptHint}</div>
        </div>
        <Button variant="secondary" size="sm">
          Choose files
        </Button>
      </div>

      {uploads.length ? (
        <div className="kg-upload__list kg-stack-sm">
          {uploads.map((item) => (
            <div key={item.id} className="kg-upload__item">
              <div className="kg-row-between">
                <span className="kg-text-sm kg-truncate kg-grow">{item.name}</span>
                <span className="kg-text-xs kg-text-muted">
                  {item.state === 'failed'
                    ? 'failed'
                    : item.state === 'queued'
                      ? 'uploaded — processing'
                      : `${item.progress}%`}
                </span>
              </div>
              <ProgressBar
                value={item.progress}
                tone={item.state === 'failed' ? 'danger' : item.state === 'queued' ? 'success' : 'primary'}
                label={false}
              />
              {item.state === 'failed' && item.error ? (
                <div className="kg-text-xs" style={{ color: 'var(--kg-danger)' }}>
                  {item.error}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}