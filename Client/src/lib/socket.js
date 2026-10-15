import { io } from 'socket.io-client';
import { API_BASE_URL } from './api';

// A single Socket.IO connection is shared by the traveler and family views.
export const socket = io(import.meta.env.VITE_SOCKET_URL || API_BASE_URL, {
  autoConnect: false,
  reconnection: true,
  reconnectionAttempts: Infinity,
  reconnectionDelay: 800,
  reconnectionDelayMax: 5000,
  timeout: 12000,
  transports: ['websocket', 'polling'],
});
