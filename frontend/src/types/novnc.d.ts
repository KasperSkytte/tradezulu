/**
 * noVNC ships as plain ES modules with no types of its own.
 *
 * Only what the viewer touches is declared. A fuller definition would be a
 * copy of their API kept in step by hand, which is a worse bargain than
 * declaring the six things used here.
 */
declare module '@novnc/novnc' {
  export interface RFBOptions {
    shared?: boolean
    credentials?: { username?: string; password?: string; target?: string }
    repeaterID?: string
    wsProtocols?: string[]
  }

  export default class RFB extends EventTarget {
    constructor(target: HTMLElement, url: string, options?: RFBOptions)
    viewOnly: boolean
    scaleViewport: boolean
    clipViewport: boolean
    resizeSession: boolean
    background: string
    disconnect(): void
  }
}
