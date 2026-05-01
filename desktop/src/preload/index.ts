import { contextBridge, ipcRenderer } from 'electron'

export type SidecarInfo = {
  port: number | null
  token: string | null
  ready: boolean
}

const api = {
  getSidecarInfo: (): Promise<SidecarInfo> => ipcRenderer.invoke('sidecar:info'),
}

contextBridge.exposeInMainWorld('api', api)

export type Api = typeof api
