import { useNavigate } from 'react-router-dom'
import { Play, Settings } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Thumbnail } from './Thumbnail'
import type { Camera } from '@/types'

interface CameraCardProps {
  camera: Camera
}

export function CameraCard({ camera }: CameraCardProps) {
  const navigate = useNavigate()

  return (
    <div
      className="card overflow-hidden cursor-pointer group transition-all hover:border-accent/50"
      onClick={() => navigate(`/cameras/${camera.id}`)}
      style={{ borderColor: camera.is_online ? undefined : 'var(--border)' }}
    >
      {/* Thumbnail */}
      <div className="relative aspect-video bg-black">
        <Thumbnail cameraId={camera.id} className="w-full h-full" />

        {/* Status dot */}
        <div
          className={`absolute top-2 right-2 w-2 h-2 rounded-full shadow-lg ${
            camera.is_online ? 'bg-green-500' : 'bg-red-500'
          }`}
        />

        {/* Hover overlay */}
        <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-3">
          <button
            className="w-9 h-9 rounded-full bg-white/10 backdrop-blur-sm flex items-center justify-center text-white hover:bg-white/20 transition"
            onClick={(e) => { e.stopPropagation(); navigate(`/cameras/${camera.id}`) }}
          >
            <Play size={16} />
          </button>
          <button
            className="w-9 h-9 rounded-full bg-white/10 backdrop-blur-sm flex items-center justify-center text-white hover:bg-white/20 transition"
            onClick={(e) => { e.stopPropagation(); navigate(`/cameras/${camera.id}/roi`) }}
          >
            <Settings size={16} />
          </button>
        </div>
      </div>

      {/* Info */}
      <div className="px-3 py-2.5">
        <p className="text-sm font-medium text-t1 truncate">{camera.name}</p>
        <p className="text-xs text-t3 truncate mt-0.5">{camera.location ?? '—'}</p>
        <div className="flex items-center gap-2 mt-2">
          <Badge variant={camera.is_online ? 'success' : 'danger'} dot>
            {camera.is_online ? 'Online' : 'Offline'}
          </Badge>
<span className="text-xs text-t3 ml-auto uppercase">{camera.stream_protocol.replace('_', ' ')}</span>
        </div>
      </div>
    </div>
  )
}
