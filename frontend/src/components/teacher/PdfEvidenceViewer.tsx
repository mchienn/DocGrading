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

export type PdfMarker = {
  id: string
  label: string
  pageNumber: number
  bbox?: BBox
}

type SearchResult = {
  page: number
  count: number
}

const EMPTY_MARKERS: PdfMarker[] = []

type PageSurface = {
  width: number
  height: number
  markers: Array<
    PdfMarker & {
      left: number
      top: number
      width: number
      height: number
    }
  >
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
        const { task, viewport } = startPageRender(page, canvasRef.current, scale)
        renderTask = task
        await renderTask.promise
        if (cancelled) return

        const [xMin, , , yMax] = page.view
        setSurface({
          width: viewport.width,
          height: viewport.height,
          markers: markers.flatMap((marker) => {
            const bbox = marker.bbox
            if (!bbox) return []
            const first = viewport.convertToViewportPoint(xMin + bbox.x0, yMax - bbox.top)
            const second = viewport.convertToViewportPoint(xMin + bbox.x1, yMax - bbox.bottom)

            return [{
              ...marker,
              left: Math.min(first[0], second[0]),
              top: Math.min(first[1], second[1]),
              width: Math.abs(second[0] - first[0]),
              height: Math.abs(second[1] - first[1]),
            }]
          }),
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
        return (
          <button
            key={marker.id}
            ref={selected ? selectedMarkerRef : undefined}
            type="button"
            aria-label={`Open evidence ${marker.label} at page ${pageNumber}`}
            title={`Evidence ${marker.label}`}
            onClick={() => onSelectMarker?.(marker.id)}
            className={`absolute border-2 transition focus:outline-none focus:ring-4 focus:ring-sky-300 ${
              selected
                ? 'z-20 border-sky-600 bg-sky-300/35'
                : 'z-10 border-amber-500 bg-amber-300/25 hover:bg-amber-300/45'
            }`}
            style={{
              left: marker.left,
              top: marker.top,
              width: Math.max(marker.width, 8),
              height: Math.max(marker.height, 8),
            }}
          >
            <span className="absolute -left-2 -top-6 rounded-full bg-slate-950 px-1.5 py-0.5 text-[10px] font-bold text-white">
              {marker.label}
            </span>
          </button>
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
    staleTime: 240_000,
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
}: PdfEvidenceViewerProps) {
  const markers = useMemo(
    () =>
      findings.flatMap((finding, findingIndex) =>
        finding.evidence.map((evidence, evidenceIndex) => ({
          id: `${finding.id}-${evidence.document_ir_id}-${evidence.element_id}-${evidenceIndex}`,
          label: String(findingIndex + 1),
          pageNumber: evidence.page_number,
          bbox: evidence.bbox,
          findingId: finding.id,
        })),
      ),
    [findings],
  )
  const selectedMarkerId = markers.find(
    (marker) => marker.findingId === selectedFindingId,
  )?.id

  return (
    <PdfMarkerViewer
      documentVersionId={documentVersionId}
      markers={markers}
      selectedMarkerId={selectedMarkerId}
      onSelectMarker={(markerId) => {
        const findingId = markers.find((marker) => marker.id === markerId)?.findingId
        if (findingId) onSelectFinding(findingId)
      }}
    />
  )
}
