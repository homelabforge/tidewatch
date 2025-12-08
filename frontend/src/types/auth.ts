/**
 * Authentication and OIDC type definitions for TideWatch
 *
 * These types match the backend schema definitions from:
 * - backend/app/schemas/auth.py
 * - backend/app/api/auth.py
 * - backend/app/api/oidc.py
 */

// ============================================================================
// Auth Status & Setup
// ============================================================================

export interface AuthStatusResponse {
  setup_complete: boolean;
  auth_mode: "none" | "local" | "oidc";
  oidc_enabled: boolean;
}

export interface SetupRequest {
  username: string;
  email: string;
  password: string;
  full_name?: string;
}

export interface SetupResponse {
  username: string;
  email: string;
  full_name: string | null;
  message: string;
}

// ============================================================================
// Local Authentication
// ============================================================================

export interface LoginRequest {
  username: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  csrf_token?: string;
}

export interface UserProfile {
  id: string;
  username: string;
  email: string;
  full_name: string | null;
  auth_method: "local" | "oidc";
  oidc_provider: string | null;
  created_at: string | null;
  last_login: string | null;
}

export interface UpdateProfileRequest {
  email?: string;
  full_name?: string;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

export interface MessageResponse {
  message: string;
}

// ============================================================================
// OIDC Authentication
// ============================================================================

export interface OIDCConfig {
  enabled: boolean;
  issuer_url: string;
  client_id: string;
  client_secret: string; // Masked in GET responses
  provider_name: string;
  scopes: string;
  redirect_uri: string;
  username_claim?: string;
  email_claim?: string;
  link_token_expire_minutes?: number;
  link_max_password_attempts?: number;
}

export interface OIDCLinkRequest {
  token: string;
  password: string;
}

export interface OIDCTestResult {
  success: boolean;
  provider_reachable: boolean;
  metadata_valid: boolean;
  endpoints_found: boolean;
  errors: string[];
  metadata?: OIDCProviderMetadata;
}

export interface OIDCProviderMetadata {
  issuer: string;
  authorization_endpoint: string;
  token_endpoint: string;
  userinfo_endpoint?: string;
  jwks_uri: string;
  scopes_supported?: string[];
  response_types_supported?: string[];
  subject_types_supported?: string[];
  id_token_signing_alg_values_supported?: string[];
}
