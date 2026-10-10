import { useQuery } from '@tanstack/react-query'
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  LoaderCircle,
  Maximize2,
  Minus,
  Plus,
  RefreshCw,
  Search,
} from 'lucide-react'
import {
  GlobalWorkerOptions,
  getDocument,
  type PDFDocumentProxy,
  type PDFPageProxy,
  type RenderTask,
} from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import {
  type ButtonHTMLAttributes,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import { api, apiData, getErrorMessage } from '../../api/client'
import type { components } from '../../api/schema'

GlobalWorkerOptions.workerSrc = workerUrl

type Finding = components['schemas']['FindingResponse']
type BBox = components['schemas']['BBox']

export type MarkerPresentation = {
  themeName: string
  symbol: string
  borderColor: string
  borderSelectedColor: string
  borderStyle: 'solid' | 'dashed' | 'double'
  bgColor: string
  bgSelectedColor: string
  badgeBg: string
  badgeText: string
  ringColor: string
  chipClass: string
}

export const MARKER_PALETTES: MarkerPresentation[] = [
  {
    themeName: 'indigo',
    symbol: '■',
    borderColor: '#4f46e5',
    borderSelectedColor: '#3730a3',
    borderStyle: 'solid',
    bgColor: 'transparent',
    bgSelectedColor: 'rgba(79, 70, 229, 0.10)',
    badgeBg: '#312e81',
    badgeText: '#ffffff',
    ringColor: '#818cf8',
    chipClass: 'border-indigo-300 bg-indigo-50 text-indigo-900',
  },
  {
    themeName: 'emerald',
    symbol: '▲',
    borderColor: '#059669',
    borderSelectedColor: '#065f46',
    borderStyle: 'dashed',
    bgColor: 'transparent',
    bgSelectedColor: 'rgba(5, 150, 105, 0.10)',
    badgeBg: '#064e3b',
    badgeText: '#ffffff',
    ringColor: '#34d399',
    chipClass: 'border-emerald-300 bg-emerald-50 text-emerald-900',
  },
  {
    themeName: 'amber',
    symbol: '◆',
    borderColor: '#d97706',
    borderSelectedColor: '#92400e',
    borderStyle: 'double',
    bgColor: 'transparent',
    bgSelectedColor: 'rgba(217, 119, 6, 0.10)',
    badgeBg: '#78350f',
    badgeText: '#ffffff',
    ringColor: '#fbbf24',
    chipClass: 'border-amber-300 bg-amber-50 text-amber-900',
  },
  {
    themeName: 'purple',
    symbol: '●',
    borderColor: '#9333ea',
    borderSelectedColor: '#6b21a8',
    borderStyle: 'solid',
    bgColor: 'transparent',
    bgSelectedColor: 'rgba(147, 51, 234, 0.10)',
    badgeBg: '#581c87',
    badgeText: '#ffffff',
    ringColor: '#c084fc',
    chipClass: 'border-purple-300 bg-purple-50 text-purple-900',
  },
  {
    themeName: 'teal',
    symbol: '✦',
    borderColor: '#0d9488',
    borderSelectedColor: '#115e59',
    borderStyle: 'dashed',
    bgColor: 'transparent',
    bgSelectedColor: 'rgba(13, 148, 136, 0.10)',
    badgeBg: '#134e4a',
    badgeText: '#ffffff',
    ringColor: '#2dd4bf',
    chipClass: 'border-teal-300 bg-teal-50 text-teal-900',
  },
  {
    themeName: 'rose',
    symbol: '★',
    borderColor: '#e11d48',
    borderSelectedColor: '#9f1239',
    borderStyle: 'double',
    bgColor: 'transparent',
    bgSelectedColor: 'rgba(225, 29, 72, 0.10)',
    badgeBg: '#881337',
    badgeText: '#ffffff',
    ringColor: '#fb7185',
    chipClass: 'border-rose-300 bg-rose-50 text-rose-900',
  },
]

export function getFindingPresentation(findingId: string): MarkerPresentation {
  let hash = 0
  for (let i = 0; i < findingId.length; i += 1) {
    hash = (hash * 31 + findingId.charCodeAt(i)) >>> 0
  }
  return MARKER_PALETTES[hash % MARKER_PALETTES.length]
}

export type PdfMarker = {
  id: string
  label: string
  pageNumber: number
  bbox?: BBox
  focusText?: string
  findingId?: string
  presentation?: MarkerPresentation
  findingTitle?: string
  severity?: string
}

type SearchResult = {
  page: number
  count: number
}

const EMPTY_MARKERS: PdfMarker[] = []

type Rect = {
  left: number
  top: number
  width: number
  height: number
}

type TextItem = {
  str: string
  dir: string
  transform: number[]
  width: number
  height: number
  fontName: string
  hasEOL: boolean
}

type ResolvedGeometry = {
  isExact: boolean
  rects: Rect[]
}

function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

type PageSurface = {
  width: number
  height: number
  markers: Array<
    PdfMarker & {
      left: number
      top: number
      width: number
      height: number
      isExact: boolean
      rects: Rect[]
    }
  >
}

type SurfaceMarker = PageSurface['markers'][number]

function markersOverlap(first: SurfaceMarker, second: SurfaceMarker): boolean {
  return first.rects.some((firstRect) =>
    second.rects.some((secondRect) => doBoxesIntersect(firstRect, secondRect)),
  )
}

function buildOverlapClusters(markers: SurfaceMarker[]): Map<string, SurfaceMarker[]> {
  const clusters = new Map<string, SurfaceMarker[]>()
  const remaining = new Set(markers.map((marker) => marker.id))

  for (const marker of markers) {
    if (!remaining.delete(marker.id)) continue

    const component: SurfaceMarker[] = []
    const queue = [marker]
    while (queue.length > 0) {
      const current = queue.pop()
      if (!current) continue
      component.push(current)

      for (const candidate of markers) {
        if (remaining.has(candidate.id) && markersOverlap(current, candidate)) {
          remaining.delete(candidate.id)
          queue.push(candidate)
        }
      }
    }

    component.sort((first, second) => first.id.localeCompare(second.id))
    for (const member of component) {
      clusters.set(member.id, component)
    }
  }

  return clusters
}

type PdfMarkerViewerProps = {
  documentVersionId: string
  markers: PdfMarker[]
  selectedMarkerId?: string
  onSelectMarker?: (markerId: string) => void
  ariaLabel?: string
}

type PdfEvidenceViewerProps = {
  documentVersionId: string
  findings: Finding[]
  selectedFindingId?: string
  onSelectFinding: (findingId: string) => void
  focusTexts?: Record<string, string>
}
function Button({
  variant = 'default',
  size = 'default',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'default' | 'outline'
  size?: 'default' | 'sm' | 'icon'
}) {
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center rounded-lg font-semibold transition disabled:cursor-not-allowed disabled:opacity-40 ${
        variant === 'outline'
          ? 'border border-slate-300 bg-white text-slate-700 hover:bg-slate-50'
          : 'bg-slate-900 text-white hover:bg-slate-800'
      } ${size === 'icon' ? 'h-9 w-9' : size === 'sm' ? 'h-9 px-3 text-xs' : 'px-3 py-2 text-sm'} ${className}`}
    />
  )
}


const clampScale = (scale: number) => Math.min(4, Math.max(0.25, scale))

const countOccurrences = (text: string, query: string) => {
  let count = 0
  let offset = 0

  while ((offset = text.indexOf(query, offset)) !== -1) {
    count += 1
    offset += query.length
  }

  return count
}

const startPageRender = (
  page: PDFPageProxy,
  canvas: HTMLCanvasElement,
  scale: number,
) => {
  const viewport = page.getViewport({ scale })
  const outputScale = window.devicePixelRatio || 1
  const context = canvas.getContext('2d')

  if (!context) {
    throw new Error('Canvas 2D context is unavailable.')
  }

  canvas.width = Math.floor(viewport.width * outputScale)
  canvas.height = Math.floor(viewport.height * outputScale)
  canvas.style.width = `${Math.floor(viewport.width)}px`
  canvas.style.height = `${Math.floor(viewport.height)}px`

  const task = page.render({
    canvas,
    canvasContext: context,
    viewport,
    transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0],
  })

  return { task, viewport }
}

function PdfThumbnail({
  pdf,
  pageNumber,
  selected,
  onSelect,
}: {
  pdf: PDFDocumentProxy
  pageNumber: number
  selected: boolean
  onSelect: () => void
}) {
  const hostRef = useRef<HTMLButtonElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [visible, setVisible] = useState(pageNumber <= 2)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (visible || !hostRef.current) return

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true)
          observer.disconnect()
        }
      },
      { rootMargin: '240px' },
    )
    observer.observe(hostRef.current)
    return () => observer.disconnect()
  }, [visible])

  useEffect(() => {
    if (!visible || !canvasRef.current) return

    let cancelled = false
    let renderTask: RenderTask | undefined

    void pdf
      .getPage(pageNumber)
      .then(async (page) => {
        if (cancelled || !canvasRef.current) return
        const baseViewport = page.getViewport({ scale: 1 })
        const result = startPageRender(page, canvasRef.current, 96 / baseViewport.width)
        renderTask = result.task
        await renderTask.promise
      })
      .catch(() => {
        if (!cancelled) setFailed(true)
      })

    return () => {
      cancelled = true
      renderTask?.cancel()
    }
  }, [pageNumber, pdf, visible])

  return (
    <button
      ref={hostRef}
      type="button"
      aria-label={`Go to PDF page ${pageNumber}`}
      aria-current={selected ? 'page' : undefined}
      onClick={onSelect}
      className={`mx-auto block w-[112px] rounded-lg border p-2 text-center text-xs font-medium transition ${
        selected
          ? 'border-sky-500 bg-sky-50 text-sky-700 ring-2 ring-sky-200'
          : 'border-slate-200 bg-white text-slate-600 hover:border-sky-300'
      }`}
    >
      <span className="flex min-h-[124px] items-center justify-center bg-slate-100">
        {failed ? (
          <span className="px-2 text-rose-600">Preview unavailable</span>
        ) : visible ? (
          <canvas ref={canvasRef} className="max-w-full shadow-sm" />
        ) : (
          <span>Loading</span>
        )}
      </span>
      <span className="mt-1 block">Page {pageNumber}</span>
    </button>
  )
}

function doBoxesIntersect(
  a: { left: number; top: number; width: number; height: number },
  b: { left: number; top: number; width: number; height: number },
): boolean {
  return (
    a.left < b.left + b.width &&
    a.left + a.width > b.left &&
    a.top < b.top + b.height &&
    a.top + a.height > b.top
  )
}

let measureCtx: CanvasRenderingContext2D | null = null
function getMeasureContext(): CanvasRenderingContext2D | null {
  if (!measureCtx && typeof document !== 'undefined') {
    const c = document.createElement('canvas')
    measureCtx = c.getContext('2d')
  }
  return measureCtx
}

function resolveMarkerGeometry(
  items: TextItem[],
  focusText: string | undefined,
  bbox: BBox | undefined,
  pageView: number[],
  viewport: ReturnType<PDFPageProxy['getViewport']>,
): ResolvedGeometry {
  const [xMin, , , yMax] = pageView
  let fallbackRect: Rect | null = null

  if (bbox) {
    const first = viewport.convertToViewportPoint(xMin + bbox.x0, yMax - bbox.top)
    const second = viewport.convertToViewportPoint(xMin + bbox.x1, yMax - bbox.bottom)
    fallbackRect = {
      left: Math.min(first[0], second[0]),
      top: Math.min(first[1], second[1]),
      width: Math.abs(second[0] - first[0]),
      height: Math.abs(second[1] - first[1]),
    }
  }

  const trimmedFocus = focusText?.trim()
  if (!trimmedFocus || items.length === 0) {
    return {
      isExact: false,
      rects: fallbackRect ? [fallbackRect] : [],
    }
  }

  type StreamChar = {
    itemIndex: number
    charIndex: number
    char: string
  }

  const stream: StreamChar[] = []
  for (let i = 0; i < items.length; i += 1) {
    const item = items[i]
    for (let j = 0; j < item.str.length; j += 1) {
      stream.push({
        itemIndex: i,
        charIndex: j,
        char: item.str[j],
      })
    }
    if (i < items.length - 1) {
      const next = items[i + 1]
      const endsWithSpace = /\s$/.test(item.str)
      const startsWithSpace = /^\s/.test(next.str)
      if (!endsWithSpace && !startsWithSpace) {
        stream.push({
          itemIndex: -1,
          charIndex: -1,
          char: ' ',
        })
      }
    }
  }

  const fullText = stream.map((s) => s.char).join('')
  let matchingStream = stream

  type MatchCandidate = {
    startIndex: number
    endIndex: number
  }
  const matches: MatchCandidate[] = []

  let searchPos = 0
  while (searchPos < fullText.length) {
    const foundIdx = fullText.indexOf(trimmedFocus, searchPos)
    if (foundIdx === -1) break
    matches.push({ startIndex: foundIdx, endIndex: foundIdx + trimmedFocus.length })
    searchPos = foundIdx + Math.max(1, trimmedFocus.length)
  }

  if (matches.length === 0) {
    try {
      const escaped = escapeRegex(trimmedFocus).replace(/\s+/g, '\\s+')
      const regex = new RegExp(escaped, 'g')
      let match: RegExpExecArray | null
      while ((match = regex.exec(fullText)) !== null) {
        matches.push({ startIndex: match.index, endIndex: match.index + match[0].length })
        if (!regex.global) break
      }
    } catch {
      // Ignore regex parsing error
    }
  }

  if (matches.length === 0) {
    try {
      const escaped = escapeRegex(trimmedFocus).replace(/\s+/g, '\\s+')
      const regex = new RegExp(escaped, 'gi')
      let match: RegExpExecArray | null
      while ((match = regex.exec(fullText)) !== null) {
        matches.push({ startIndex: match.index, endIndex: match.index + match[0].length })
        if (!regex.global) break
      }
    } catch {
      // Ignore regex parsing error
    }
  }

  if (matches.length === 0) {
    const compactStream = stream.filter(
      (entry) => entry.itemIndex >= 0 && !/\s/.test(entry.char),
    )
    const compactText = compactStream.map((entry) => entry.char).join('').toLowerCase()
    const compactFocus = trimmedFocus.replace(/\s+/g, '').toLowerCase()
    let compactOffset = 0

    while (compactFocus && compactOffset < compactText.length) {
      const foundIndex = compactText.indexOf(compactFocus, compactOffset)
      if (foundIndex === -1) break
      matches.push({
        startIndex: foundIndex,
        endIndex: foundIndex + compactFocus.length,
      })
      compactOffset = foundIndex + Math.max(1, compactFocus.length)
    }

    if (matches.length > 0) {
      matchingStream = compactStream
    }
  }

  if (matches.length === 0) {
    return {
      isExact: false,
      rects: fallbackRect ? [fallbackRect] : [],
    }
  }

  type ResolvedCandidate = {
    rects: Rect[]
    bounding: Rect
  }

  const resolvedCandidates: ResolvedCandidate[] = []
  const ctx = getMeasureContext()

  for (const m of matches) {
    const itemCharRanges = new Map<number, { start: number; end: number }>()
    for (let k = m.startIndex; k < m.endIndex; k += 1) {
      const entry = matchingStream[k]
      if (entry && entry.itemIndex >= 0) {
        const existing = itemCharRanges.get(entry.itemIndex)
        if (existing) {
          existing.end = Math.max(existing.end, entry.charIndex + 1)
        } else {
          itemCharRanges.set(entry.itemIndex, {
            start: entry.charIndex,
            end: entry.charIndex + 1,
          })
        }
      }
    }

    const segmentRects: Rect[] = []

    for (const [itemIndex, range] of itemCharRanges.entries()) {
      const item = items[itemIndex]
      const [a, b, c, d, e, f] = item.transform
      const fontHeight = item.height > 0
        ? item.height
        : Math.hypot(c, d) || Math.abs(d) || Math.abs(a) || 10
      const strLen = item.str.length

      let startOffset = 0
      let spanWidth = item.width

      if (strLen > 0 && (range.start > 0 || range.end < strLen)) {
        let prefixRatio = range.start / strLen
        let spanRatio = (range.end - range.start) / strLen

        if (ctx) {
          ctx.font = `${Math.round(fontHeight)}px sans-serif`
          const fullM = ctx.measureText(item.str).width
          const preM = ctx.measureText(item.str.slice(0, range.start)).width
          const spanM = ctx.measureText(item.str.slice(range.start, range.end)).width
          if (fullM > 0) {
            prefixRatio = preM / fullM
            spanRatio = spanM / fullM
          }
        }
        startOffset = item.width * prefixRatio
        spanWidth = item.width * spanRatio
      }

      const norm = Math.hypot(a, b) || 1
      const ux = a / norm
      const uy = b / norm
      const vx = -uy
      const vy = ux

      const p1x = e + ux * startOffset
      const p1y = f + uy * startOffset

      const p2x = p1x + ux * spanWidth
      const p2y = p1y + uy * spanWidth

      const p3x = p2x + vx * fontHeight
      const p3y = p2y + vy * fontHeight

      const p4x = p1x + vx * fontHeight
      const p4y = p1y + vy * fontHeight

      const v1 = viewport.convertToViewportPoint(p1x, p1y)
      const v2 = viewport.convertToViewportPoint(p2x, p2y)
      const v3 = viewport.convertToViewportPoint(p3x, p3y)
      const v4 = viewport.convertToViewportPoint(p4x, p4y)

      const rLeft = Math.min(v1[0], v2[0], v3[0], v4[0])
      const rRight = Math.max(v1[0], v2[0], v3[0], v4[0])
      const rTop = Math.min(v1[1], v2[1], v3[1], v4[1])
      const rBottom = Math.max(v1[1], v2[1], v3[1], v4[1])

      segmentRects.push({
        left: rLeft,
        top: rTop,
        width: Math.max(rRight - rLeft, 2),
        height: Math.max(rBottom - rTop, 2),
      })
    }

    if (segmentRects.length === 0) continue

    segmentRects.sort((s1, s2) => s1.top - s2.top || s1.left - s2.left)
    const lineRects: Rect[] = []
    let currentLine: Rect = { ...segmentRects[0] }

    for (let s = 1; s < segmentRects.length; s += 1) {
      const seg = segmentRects[s]
      const lineMidY = currentLine.top + currentLine.height / 2
      const segMidY = seg.top + seg.height / 2
      const isSameLine = Math.abs(lineMidY - segMidY) < Math.max(currentLine.height, seg.height) * 0.6

      if (isSameLine) {
        const left = Math.min(currentLine.left, seg.left)
        const top = Math.min(currentLine.top, seg.top)
        const right = Math.max(currentLine.left + currentLine.width, seg.left + seg.width)
        const bottom = Math.max(currentLine.top + currentLine.height, seg.top + seg.height)
        currentLine = { left, top, width: right - left, height: bottom - top }
      } else {
        lineRects.push(currentLine)
        currentLine = { ...seg }
      }
    }
    lineRects.push(currentLine)

    const bLeft = Math.min(...lineRects.map((r) => r.left))
    const bTop = Math.min(...lineRects.map((r) => r.top))
    const bRight = Math.max(...lineRects.map((r) => r.left + r.width))
    const bBottom = Math.max(...lineRects.map((r) => r.top + r.height))

    resolvedCandidates.push({
      rects: lineRects,
      bounding: { left: bLeft, top: bTop, width: bRight - bLeft, height: bBottom - bTop },
    })
  }

  if (resolvedCandidates.length === 0) {
    return {
      isExact: false,
      rects: fallbackRect ? [fallbackRect] : [],
    }
  }

  let bestCandidate = resolvedCandidates[0]
  if (fallbackRect && resolvedCandidates.length > 1) {
    const fbCenterX = fallbackRect.left + fallbackRect.width / 2
    const fbCenterY = fallbackRect.top + fallbackRect.height / 2

    let minScore = Number.POSITIVE_INFINITY
    for (const cand of resolvedCandidates) {
      const candCenterX = cand.bounding.left + cand.bounding.width / 2
      const candCenterY = cand.bounding.top + cand.bounding.height / 2
      const dist = Math.hypot(candCenterX - fbCenterX, candCenterY - fbCenterY)

      const intersects = doBoxesIntersect(cand.bounding, fallbackRect)
      const score = intersects ? dist - 100_000 : dist
      if (score < minScore) {
        minScore = score
        bestCandidate = cand
      }
    }
  }

  return {
    isExact: true,
    rects: bestCandidate.rects,
  }
}

function PdfPageSurface({
  pdf,
  pageNumber,
  zoom,
  fitWidth,
  availableWidth,
  markers,
  selectedMarkerId,
  onSelectMarker,
  onScaleResolved,
}: {
  pdf: PDFDocumentProxy
  pageNumber: number
  zoom: number
  fitWidth: boolean
  availableWidth: number
  markers: PdfMarker[]
  selectedMarkerId?: string
  onSelectMarker?: (markerId: string) => void
  onScaleResolved: (scale: number) => void
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const selectedMarkerRef = useRef<HTMLButtonElement>(null)
  const [surface, setSurface] = useState<PageSurface>()
  const [rendering, setRendering] = useState(true)
  const [error, setError] = useState<string>()

  useEffect(() => {
    if (!canvasRef.current) return

    let cancelled = false
    let renderTask: RenderTask | undefined
    setRendering(true)
    setError(undefined)

    void pdf
      .getPage(pageNumber)
      .then(async (page) => {
        if (cancelled || !canvasRef.current) return

        const baseViewport = page.getViewport({ scale: 1 })
        const scale = fitWidth
          ? clampScale((availableWidth - 32) / baseViewport.width)
          : zoom
        const renderResult = startPageRender(page, canvasRef.current, scale)
        renderTask = renderResult.task
        const [, textContent] = await Promise.all([
          renderTask.promise,
          page.getTextContent(),
        ])
        if (cancelled) return

        const textItems = textContent.items.filter(
          (item): item is TextItem => 'str' in item && typeof item.str === 'string',
        )

        const resolvedMarkers = markers.flatMap((marker) => {
          const geom = resolveMarkerGeometry(
            textItems,
            marker.focusText,
            marker.bbox,
            page.view,
            renderResult.viewport,
          )
          if (geom.rects.length === 0) return []
          const bLeft = Math.min(...geom.rects.map((r) => r.left))
          const bTop = Math.min(...geom.rects.map((r) => r.top))
          const bRight = Math.max(...geom.rects.map((r) => r.left + r.width))
          const bBottom = Math.max(...geom.rects.map((r) => r.top + r.height))

          return [{
            ...marker,
            left: bLeft,
            top: bTop,
            width: bRight - bLeft,
            height: bBottom - bTop,
            isExact: geom.isExact,
            rects: geom.rects,
          }]
        })

        setSurface({
          width: renderResult.viewport.width,
          height: renderResult.viewport.height,
          markers: resolvedMarkers,
        })
        onScaleResolved(scale)
        setRendering(false)
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : 'Could not render PDF page.')
          setRendering(false)
        }
      })

    return () => {
      cancelled = true
      renderTask?.cancel()
    }
  }, [availableWidth, fitWidth, markers, onScaleResolved, pageNumber, pdf, zoom])

  const overlapClusterByMarkerId = useMemo(
    () => buildOverlapClusters(surface?.markers ?? []),
    [surface],
  )

  useEffect(() => {
    selectedMarkerRef.current?.scrollIntoView({
      behavior: 'smooth',
      block: 'center',
      inline: 'center',
    })
  }, [selectedMarkerId, surface])

  return (
    <div
      className="relative mx-auto bg-white shadow-xl"
      style={{ width: surface?.width, height: surface?.height }}
    >
      <canvas ref={canvasRef} role="img" aria-label={`PDF page ${pageNumber}`} />

      {surface?.markers.map((marker) => {
        const selected = marker.id === selectedMarkerId
        const pres = marker.presentation
        const borderStyle = pres?.borderStyle ?? 'solid'
        const borderColor = selected
          ? (pres?.borderSelectedColor ?? '#0284c7')
          : (pres?.borderColor ?? '#d97706')
        const bgColor = marker.isExact
          ? (selected ? (pres?.bgSelectedColor ?? 'rgba(14, 165, 233, 0.10)') : 'transparent')
          : 'transparent'

        const overlapCluster = overlapClusterByMarkerId.get(marker.id) ?? [marker]
        const hasOverlap = overlapCluster.length > 1

        const handleClick = () => {
          if (selected && hasOverlap) {
            const currentIndex = overlapCluster.findIndex((item) => item.id === marker.id)
            const nextIndex = (currentIndex + 1) % overlapCluster.length
            onSelectMarker?.(overlapCluster[nextIndex].id)
            return
          }
          onSelectMarker?.(marker.id)
        }

        return (
          <div key={marker.id} className="contents">
            {marker.rects.map((rect, rectIndex) => (
              <button
                key={`${marker.id}-${rectIndex}`}
                ref={selected && rectIndex === 0 ? selectedMarkerRef : undefined}
                type="button"
                aria-label={`Evidence ${marker.label} at page ${pageNumber}${hasOverlap ? ' (overlapping)' : ''}`}
                title={`Evidence ${marker.label}${hasOverlap ? ' (click to cycle overlapping)' : ''}`}
                onClick={handleClick}
                className={`group absolute transition focus:outline-none ${
                  selected ? 'z-30 ring-2 ring-sky-400 ring-offset-1' : 'z-10 hover:z-20'
                }`}
                style={{
                  left: rect.left,
                  top: rect.top,
                  width: Math.max(rect.width, 8),
                  height: Math.max(rect.height, 8),
                  borderWidth: selected ? '2.5px' : '2px',
                  borderStyle,
                  borderColor,
                  backgroundColor: bgColor,
                }}
              >
                {rectIndex === 0 && (
                  <span
                    className={`pointer-events-none absolute -top-6 left-0 flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold shadow transition-opacity ${
                      selected ? 'opacity-100 z-40' : 'opacity-0 group-hover:opacity-100 group-focus:opacity-100 z-30'
                    }`}
                    style={{
                      backgroundColor: pres?.badgeBg ?? '#0f172a',
                      color: pres?.badgeText ?? '#ffffff',
                    }}
                  >
                    {pres?.symbol && <span aria-hidden="true">{pres.symbol}</span>}
                    <span>{marker.label}</span>
                    {selected && hasOverlap && (
                      <span className="text-[9px] font-normal opacity-80">(cycle ⇄)</span>
                    )}
                  </span>
                )}
              </button>
            ))}
          </div>
        )
      })}

      {rendering ? (
        <div className="absolute inset-0 flex items-center justify-center bg-white/80 text-sm font-medium text-slate-600">
          <LoaderCircle className="mr-2 h-4 w-4 animate-spin" />
          Rendering page
        </div>
      ) : null}
      {error ? (
        <div role="alert" className="absolute inset-0 grid place-items-center bg-white p-6 text-rose-700">
          {error}
        </div>
      ) : null}
    </div>
  )
}

export function PdfMarkerViewer({
  documentVersionId,
  markers,
  selectedMarkerId,
  onSelectMarker,
  ariaLabel = 'PDF evidence viewer',
}: PdfMarkerViewerProps) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const searchRunRef = useRef(0)
  const [pdf, setPdf] = useState<PDFDocumentProxy>()
  const [loadError, setLoadError] = useState<string>()
  const [reloadNonce, setReloadNonce] = useState(0)
  const [pageNumber, setPageNumber] = useState(1)
  const [zoom, setZoom] = useState(1)
  const [fitWidth, setFitWidth] = useState(true)
  const [effectiveScale, setEffectiveScale] = useState(1)
  const [availableWidth, setAvailableWidth] = useState(800)
  const [searchInput, setSearchInput] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[]>([])
  const [searchIndex, setSearchIndex] = useState(0)
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<string>()

  const downloadQuery = useQuery({
    queryKey: ['document-download', documentVersionId],
    queryFn: () =>
      apiData(
        api.GET('/api/v1/document-versions/{version_id}/download', {
          params: { path: { version_id: documentVersionId } },
        }),
      ),
    staleTime: 0,
    gcTime: 0,
    refetchOnMount: 'always',
    refetchOnWindowFocus: false,
    retry: false,
  })

  useEffect(() => {
    const host = viewportRef.current
    if (!host) return

    const updateWidth = () => setAvailableWidth(host.clientWidth)
    updateWidth()
    const observer = new ResizeObserver(updateWidth)
    observer.observe(host)
    return () => observer.disconnect()
  }, [pdf])

  useEffect(() => {
    const url = downloadQuery.data?.url
    if (!url) return

    let cancelled = false
    const loadingTask = getDocument({ url, disableRange: true, disableStream: true })
    setPdf(undefined)
    setLoadError(undefined)

    void loadingTask.promise
      .then((document) => {
        if (cancelled) return
        setPdf(document)
        setPageNumber(1)
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setLoadError(caught instanceof Error ? caught.message : 'Could not load PDF document.')
        }
      })

    return () => {
      cancelled = true
      void loadingTask.destroy()
    }
  }, [downloadQuery.data?.url, reloadNonce])

  useEffect(() => {
    const marker = markers.find((candidate) => candidate.id === selectedMarkerId)
    if (
      marker &&
      marker.pageNumber <= (pdf?.numPages ?? Number.POSITIVE_INFINITY)
    ) {
      setPageNumber(marker.pageNumber)
    }
  }, [markers, pdf?.numPages, selectedMarkerId])

  useEffect(
    () => () => {
      searchRunRef.current += 1
    },
    [],
  )

  const markersByPage = useMemo(() => {
    const byPage = new Map<number, PdfMarker[]>()
    markers.forEach((marker) => {
      const pageMarkers = byPage.get(marker.pageNumber) ?? []
      pageMarkers.push(marker)
      byPage.set(marker.pageNumber, pageMarkers)
    })
    return byPage
  }, [markers])

  const submitSearch = async () => {
    if (!pdf) return

    const query = searchInput.trim().toLocaleLowerCase()
    const run = searchRunRef.current + 1
    searchRunRef.current = run
    setSearchQuery(query)
    setSearchResults([])
    setSearchIndex(0)
    setSearchError(undefined)

    if (!query) {
      setSearching(false)
      return
    }

    setSearching(true)
    const results: SearchResult[] = []

    try {
      for (let page = 1; page <= pdf.numPages; page += 1) {
        const pdfPage = await pdf.getPage(page)
        const textContent = await pdfPage.getTextContent()
        if (searchRunRef.current !== run) return

        const text = textContent.items
          .map((item) => ('str' in item ? item.str : ''))
          .join(' ')
          .toLocaleLowerCase()
        const count = countOccurrences(text, query)
        if (count > 0) results.push({ page, count })
      }

      if (searchRunRef.current !== run) return
      setSearchResults(results)
      if (results[0]) setPageNumber(results[0].page)
    } catch (caught: unknown) {
      if (searchRunRef.current === run) {
        setSearchError(caught instanceof Error ? caught.message : 'Could not search PDF text.')
      }
    } finally {
      if (searchRunRef.current === run) setSearching(false)
    }
  }

  const moveSearch = (delta: number) => {
    if (!searchResults.length) return
    const index = (searchIndex + delta + searchResults.length) % searchResults.length
    setSearchIndex(index)
    setPageNumber(searchResults[index].page)
  }

  const changeZoom = (delta: number) => {
    setFitWidth(false)
    setZoom(clampScale(effectiveScale + delta))
  }
  const pageResult = searchResults.find((result) => result.page === pageNumber)
  const totalMatches = searchResults.reduce((total, result) => total + result.count, 0)
  const downloadError = downloadQuery.error
    ? getErrorMessage(downloadQuery.error)
    : undefined

  if (downloadQuery.isPending || (!pdf && !loadError && !downloadError)) {
    return (
      <section className="grid min-h-[72vh] place-items-center rounded-xl border border-slate-200 bg-white">
        <div className="flex items-center text-sm font-medium text-slate-600">
          <LoaderCircle className="mr-2 h-5 w-5 animate-spin" />
          Loading PDF
        </div>
      </section>
    )
  }

  if (!pdf) {
    return (
      <section className="grid min-h-[72vh] place-items-center rounded-xl border border-rose-200 bg-rose-50 p-6">
        <div className="max-w-md text-center">
          <h2 className="font-semibold text-rose-900">PDF unavailable</h2>
          <p role="alert" className="mt-2 text-sm text-rose-700">
            {downloadError ?? loadError}
          </p>
          <Button
            className="mt-4"
            onClick={() => {
              void downloadQuery.refetch()
              setReloadNonce((value) => value + 1)
            }}
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            Retry PDF
          </Button>
        </div>
      </section>
    )
  }

  return (
    <section
      aria-label={ariaLabel}
      className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
    >
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-white p-2">
        <Button
          variant="outline"
          size="icon"
          aria-label="Previous PDF page"
          disabled={pageNumber <= 1}
          onClick={() => setPageNumber((page) => Math.max(1, page - 1))}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span className="min-w-24 text-center text-sm font-semibold text-slate-700">
          {pageNumber} / {pdf.numPages}
        </span>
        <Button
          variant="outline"
          size="icon"
          aria-label="Next PDF page"
          disabled={pageNumber >= pdf.numPages}
          onClick={() => setPageNumber((page) => Math.min(pdf.numPages, page + 1))}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>

        <div className="mx-1 h-7 w-px bg-slate-200" />
        <Button
          variant="outline"
          size="icon"
          aria-label="Zoom out"
          disabled={effectiveScale <= 0.25}
          onClick={() => changeZoom(-0.25)}
        >
          <Minus className="h-4 w-4" />
        </Button>
        <span className="min-w-12 text-center text-xs font-semibold text-slate-600">
          {Math.round(effectiveScale * 100)}%
        </span>
        <Button
          variant="outline"
          size="icon"
          aria-label="Zoom in"
          disabled={effectiveScale >= 4}
          onClick={() => changeZoom(0.25)}
        >
          <Plus className="h-4 w-4" />
        </Button>
        <Button
          variant={fitWidth ? 'default' : 'outline'}
          size="sm"
          onClick={() => setFitWidth(true)}
        >
          <Maximize2 className="mr-2 h-4 w-4" />
          Fit width
        </Button>

        <form
          role="search"
          className="ml-auto flex min-w-64 flex-1 items-center justify-end gap-1 lg:max-w-md"
          onSubmit={(event) => {
            event.preventDefault()
            void submitSearch()
          }}
        >
          <label htmlFor="pdf-search" className="sr-only">
            Search PDF text
          </label>
          <input
            id="pdf-search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="Search PDF"
            className="h-9 min-w-0 flex-1 rounded-lg border border-slate-300 px-3 text-sm outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-200"
          />
          <Button type="submit" variant="outline" size="icon" aria-label="Search PDF">
            {searching ? (
              <LoaderCircle className="h-4 w-4 animate-spin" />
            ) : (
              <Search className="h-4 w-4" />
            )}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label="Previous search result"
            disabled={!searchResults.length}
            onClick={() => moveSearch(-1)}
          >
            <ChevronUp className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label="Next search result"
            disabled={!searchResults.length}
            onClick={() => moveSearch(1)}
          >
            <ChevronDown className="h-4 w-4" />
          </Button>
        </form>
      </div>

      {!searching && (searchQuery || searchError) ? (
        <div
          className={`border-b px-3 py-1.5 text-xs ${
            searchError
              ? 'border-rose-200 bg-rose-50 text-rose-700'
              : 'border-slate-200 bg-sky-50 text-sky-800'
          }`}
        >
          {searchError ??
            (searchResults.length
              ? `${totalMatches} matches on ${searchResults.length} pages${pageResult ? `; ${pageResult.count} on this page` : ''}`
              : `No matches for “${searchQuery}”`)}
        </div>
      ) : null}

      <div className="grid min-h-[72vh] grid-cols-[128px_minmax(0,1fr)]">
        <aside
          aria-label="PDF page thumbnails"
          className="max-h-[72vh] space-y-3 overflow-y-auto border-r border-slate-200 bg-slate-50 p-2"
        >
          {Array.from({ length: pdf.numPages }, (_, index) => {
            const page = index + 1
            return (
              <PdfThumbnail
                key={page}
                pdf={pdf}
                pageNumber={page}
                selected={page === pageNumber}
                onSelect={() => setPageNumber(page)}
              />
            )
          })}
        </aside>

        <div ref={viewportRef} className="max-h-[72vh] overflow-auto bg-slate-200 p-4">
          {(markersByPage.get(pageNumber) ?? EMPTY_MARKERS).length > 0 && (
            <div
              role="toolbar"
              aria-label={`Evidence markers on page ${pageNumber}`}
              className="sticky top-0 z-20 mx-auto mb-3 flex max-w-fit flex-wrap items-center justify-center gap-1.5 rounded-lg border border-slate-300 bg-white/95 px-3 py-1.5 text-xs shadow-sm backdrop-blur"
            >
              <span className="text-[11px] font-semibold text-slate-500 mr-1">
                Page {pageNumber} markers ({(markersByPage.get(pageNumber) ?? EMPTY_MARKERS).length}):
              </span>
              {(markersByPage.get(pageNumber) ?? EMPTY_MARKERS).map((marker) => {
                const isSel = marker.id === selectedMarkerId
                const pres = marker.presentation
                return (
                  <button
                    key={marker.id}
                    type="button"
                    aria-pressed={isSel}
                    onClick={() => onSelectMarker?.(marker.id)}
                    className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold transition focus:outline-none focus:ring-2 focus:ring-sky-400 ${
                      isSel
                        ? 'bg-slate-900 text-white shadow-sm ring-2 ring-sky-400'
                        : pres?.chipClass ?? 'border border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100'
                    }`}
                  >
                    {pres?.symbol && <span aria-hidden="true">{pres.symbol}</span>}
                    <span>Evidence {marker.label}</span>
                    {marker.severity && (
                      <span className="text-[10px] opacity-75 font-mono uppercase">({marker.severity})</span>
                    )}
                  </button>
                )
              })}
            </div>
          )}

          <PdfPageSurface
            pdf={pdf}
            pageNumber={pageNumber}
            zoom={zoom}
            fitWidth={fitWidth}
            availableWidth={availableWidth}
            markers={markersByPage.get(pageNumber) ?? EMPTY_MARKERS}
            selectedMarkerId={selectedMarkerId}
            onSelectMarker={onSelectMarker}
            onScaleResolved={setEffectiveScale}
          />
        </div>
      </div>
    </section>
  )
}

export function PdfEvidenceViewer({
  documentVersionId,
  findings,
  selectedFindingId,
  onSelectFinding,
  focusTexts,
}: PdfEvidenceViewerProps) {
  const markers = useMemo(
    () =>
      findings.flatMap((finding, findingIndex) => {
        const presentation = getFindingPresentation(finding.id)
        const focusText = focusTexts?.[finding.id]
        return finding.evidence.map((evidence, evidenceIndex) => ({
          id: `${finding.id}:${evidence.document_ir_id}:${evidence.element_id}:${evidence.page_number}`,
          label: `${findingIndex + 1}.${evidenceIndex + 1}`,
          pageNumber: evidence.page_number,
          bbox: evidence.bbox,
          focusText,
          findingId: finding.id,
          presentation,
          findingTitle: finding.criterion_title,
          severity: finding.severity,
        }))
      }),
    [findings, focusTexts],
  )
  const [selectedMarkerId, setSelectedMarkerId] = useState<string>()

  useEffect(() => {
    if (!selectedFindingId) {
      setSelectedMarkerId(undefined)
      return
    }
    setSelectedMarkerId((current) =>
      current && markers.some(
        (marker) => marker.id === current && marker.findingId === selectedFindingId,
      )
        ? current
        : markers.find((marker) => marker.findingId === selectedFindingId)?.id,
    )
  }, [markers, selectedFindingId])

  return (
    <PdfMarkerViewer
      documentVersionId={documentVersionId}
      markers={markers}
      selectedMarkerId={selectedMarkerId}
      onSelectMarker={(markerId) => {
        setSelectedMarkerId(markerId)
        const findingId = markers.find((marker) => marker.id === markerId)?.findingId
        if (findingId) onSelectFinding(findingId)
      }}
    />
  )
}
