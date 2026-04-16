/// <reference types="vite/client" />
/**
 * Backend API Base URL.
 *
 * - Local Dev: Leave empty, handled by Vite proxy to http://localhost:7860
 * - Docker Prod: Leave empty, handled by nginx proxy to backend:7860
 * - Vercel / Standalone Frontend: Set VITE_API_BASE_URL=https://your-backend.example.com
 */
export const API_BASE: string = (import.meta.env.VITE_API_BASE_URL as string) ?? ''
