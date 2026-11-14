/**
 * Notebook — scroll-driven paper animation (ported from improve-UI prototype).
 *
 * Ported from improve-know-graph-ai-ui/components/notebook.tsx.
 * Replaces next/image with standard <img> for the Vite/React 18 frontend.
 * Shows a 3D book that opens as you scroll, with a cover, paper leaves, and
 * an overlay cover that flips open.
 *
 * For the Vite/React 18 frontend — adapted from Next.js version.
 */

import { useEffect, useRef, useState } from 'react'
import { ArrowDown, ArrowUpRight, Network, Sparkles } from 'lucide-react'

const coverImage = '/images/notebook-cover.png'
const paperImage = '/images/notebook-paper.png'

export default function Notebook() {
  const stage = useRef(null)
  const toggle = useRef(() => {})
  const [opened, setOpened] = useState(false)

  useEffect(() => {
    const el = stage.current
    if (!el) return
    const book = el.querySelector('.notebook')
    const cover = el.querySelector('.book-cover')
    const leaves = Array.from(el.querySelectorAll('.paper-leaf'))
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
    let progress = 0
    let target = 0
    let frame = 0
    let previousTime = 0
    let openState = false
    let manual = null

    const draw = (time) => {
      const elapsed = previousTime ? Math.min(time - previousTime, 40) : 16
      previousTime = time
      progress = reduced.matches
        ? target
        : progress + (target - progress) * (1 - Math.exp(-elapsed / 95))
      if (Math.abs(target - progress) < 0.001) progress = target
      const scale = 1
      if (book) {
        book.style.transform = `translateX(${20 + progress * 75}px) rotateX(${12 - progress * 7}deg) rotateY(${-17 + progress * 22}deg) rotateZ(${-9 + progress * 10}deg) scale(${scale})`
      }
      if (cover) {
        cover.style.transform = `translateZ(10px) rotateY(${-153 * progress}deg)`
      }
      leaves.forEach((leaf, index) => {
        const leafProgress = Math.max(0, (progress - (index + 1) * 0.14) / (1 - (index + 1) * 0.14))
        leaf.style.transform = `translateZ(${7 - index * 2}px) rotateY(${-leafProgress * (24 - index * 7)}deg)`
      })
      const nextOpen = progress > 0.5
      if (nextOpen !== openState) {
        openState = nextOpen
        setOpened(nextOpen)
      }
      frame = progress !== target ? requestAnimationFrame(draw) : 0
      if (!frame) previousTime = 0
    }
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(draw)
    }
    const fromScroll = () => {
      const track = el.closest('.notebook-track')
      const start = track
        ? track.getBoundingClientRect().top + window.scrollY - 155
        : 20
      target = manual ?? (reduced.matches
        ? 0
        : Math.max(0, Math.min(1, (window.scrollY - start) / 280)))
      schedule()
    }
    const onScroll = () => {
      manual = null
      fromScroll()
    }
    toggle.current = () => {
      manual = target > 0.5 ? 0 : 1
      target = manual
      schedule()
    }
    fromScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', fromScroll)
    reduced.addEventListener('change', fromScroll)
    return () => {
      cancelAnimationFrame(frame)
      toggle.current = () => {}
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', fromScroll)
      reduced.removeEventListener('change', fromScroll)
    }
  }, [])

  return (
    <div className="notebook-stage" ref={stage}>
      <span className="floating-note note-top">
        <Sparkles size={14} /> A little room for big ideas
      </span>
      <div className="book-shadow" aria-hidden="true" />
      <button
        className="notebook"
        aria-label={opened ? 'Close notebook' : 'Open notebook'}
        aria-pressed={opened}
        onClick={() => toggle.current()}
      >
        <span className="book-base" aria-hidden="true">
          <img src={coverImage} alt="" className="cover-img" />
        </span>
        <span className="page-stack" aria-hidden="true" />
        {[0, 1, 2].map((index) => (
          <span key={index} className="paper-leaf" aria-hidden="true">
            <img src={paperImage} alt="" className="paper-img" />
            {index === 0 && (
              <span className="notebook-page-content">
                <span className="page-eyebrow">A NOTE TO SELF</span>
                <span className="page-heading">Everything<br />is connected.</span>
                <span className="page-copy">
                  Collect what moves you.<br />
                  Connect what you learn.<br />
                  See what grows.
                </span>
                <Network size={46} strokeWidth={1} />
                <span className="page-number">YOUR NEXT CHAPTER · 01</span>
              </span>
            )}
          </span>
        ))}
        <span className="book-cover" aria-hidden="true">
          <span className="cover-front">
            <img src={coverImage} alt="" className="cover-img" />
            <span className="cover-edition">THE PERSONAL KNOWLEDGE SERIES</span>
            <span className="cover-label">
              <Network size={32} strokeWidth={1} />
              <span>
                My knowledge<br />
                <strong>notebook.</strong>
              </span>
              <span className="cover-line" />
              <small>A collection of things<br />worth knowing.</small>
            </span>
            <span className="cover-footer">
              KNOWGRAPH <ArrowUpRight size={13} />
            </span>
          </span>
          <span className="cover-back">
            <img src={paperImage} alt="" className="paper-img" />
            <span>
              Stay<br />
              <i>curious.</i>
              <Sparkles size={24} strokeWidth={1} />
            </span>
          </span>
        </span>
      </button>
      <span className="floating-note note-bottom">
        Good things start with a blank page.
      </span>
      <span className="scroll-cue">
        <ArrowDown size={13} /> Scroll to open · or click the notebook
      </span>
    </div>
  )
}
