import axios from 'axios';

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
export const api = axios.create({ baseURL: API_BASE_URL, timeout: 45000, headers: { Accept: 'application/json' } });

export function getApiError(error, fallback = 'Something went wrong. Please try again.') {
  const data = error?.response?.data;
  if (typeof data?.detail === 'string') return data.detail;
  if (typeof data?.msg === 'string') return data.msg;
  if (typeof data?.error === 'string') return data.error;
  if (error?.code === 'ECONNABORTED') return 'The request took too long. Please retry.';
  if (error?.message === 'Network Error') return `Cannot reach the backend at ${API_BASE_URL}. Start the FastAPI server and check VITE_API_BASE_URL.`;
  return error?.message || fallback;
}
