import { io, Socket } from 'socket.io-client'

let _socket: Socket | null = null

export function getSocket(): Socket {
  if (!_socket) {
    _socket = io('http://localhost:5000', {
      transports: ['websocket', 'polling'],
      reconnectionDelay: 1000,
      reconnectionAttempts: Infinity,
    })
    _socket.on('connect', () => console.log('[socket] connected'))
    _socket.on('disconnect', (reason) => console.warn('[socket] disconnected:', reason))
    _socket.on('connect_error', (err) => console.warn('[socket] error:', err.message))
  }
  return _socket
}
