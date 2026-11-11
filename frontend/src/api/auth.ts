import { apiClient } from "./client"
import type { LoginRequest, RegisterRequest, Token, User } from "../types/api"

export async function login(payload: LoginRequest): Promise<Token> {
  const { data } = await apiClient.post<Token>("/auth/login", payload)
  return data
}

export async function register(payload: RegisterRequest): Promise<User> {
  const { data } = await apiClient.post<User>("/auth/register", payload)
  return data
}

export async function me(): Promise<User> {
  const { data } = await apiClient.get<User>("/auth/me")
  return data
}
