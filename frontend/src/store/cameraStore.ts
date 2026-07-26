import { create } from 'zustand'

interface CameraStatus {
  online: boolean
}

interface CameraStoreState {
  cameras: Record<string, CameraStatus>
  setOnline: (camera_id: string) => void
  setOffline: (camera_id: string) => void
  reset: () => void
}

export const useCameraStore = create<CameraStoreState>((set) => ({
  cameras: {},

  setOnline: (camera_id) =>
    set((s) => ({
      cameras: { ...s.cameras, [camera_id]: { online: true } },
    })),

  setOffline: (camera_id) =>
    set((s) => ({
      cameras: { ...s.cameras, [camera_id]: { online: false } },
    })),

  reset: () => set({ cameras: {} }),
}))
