import { createContext } from "react"
import type { User } from "../types/api"

export interface AuthState {
  user: User | null
  loading: boolean
  isAuthenticated: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

// createContext 实例独立存放，避免 react-refresh boundary 重新求值导致实例不一致
export const AuthContext = createContext<AuthState | undefined>(undefined)