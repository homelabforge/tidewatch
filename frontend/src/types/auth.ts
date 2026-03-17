/**
 * Authentication and OIDC type definitions for TideWatch
 *
 * Generated types (6): aliases from OpenAPI schema via api.generated.ts
 * Hand-maintained types (7): narrow unions, not in OpenAPI, or backend contract mismatch
 */

import type { components } from './api.generated';

// ============================================================================
// Generated: aliases from OpenAPI schema
// ============================================================================

export type SetupRequest = components['schemas']['SetupRequest'];
export type SetupResponse = components['schemas']['SetupResponse'];
export type LoginRequest = components['schemas']['LoginRequest'];
export type UpdateProfileRequest = components['schemas']['UpdateProfileRequest'];
export type ChangePasswordRequest = components['schemas']['ChangePasswordRequest'];
export type OIDCConfig = components['schemas']['OIDCConfig'];

// ============================================================================
// Hand-maintained: narrow union literals (generated would widen to string)
// ============================================================================

export interface AuthStatusResponse {
  setup_complete: boolean;
  auth_mode: 'none' | 'local' | 'oidc';
  oidc_enabled: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
  csrf_token?: string;
}

export interface UserProfile {
  id: string;
  username: string;
  email: string;
  full_name: string | null;
  auth_method: 'local' | 'oidc';
  oidc_provider: string | null;
  created_at: string | null;
  last_login: string | null;
}

// ============================================================================
// Hand-maintained: not in OpenAPI or backend contract mismatch
// ============================================================================

export interface MessageResponse {
  message: string;
}

export interface OIDCLinkRequest {
  token: string;
  password: string;
}

// OIDCTestResult stays hand-maintained: backend declares metadata as dict | None,
// but frontend uses OIDCProviderMetadata (structured OIDC discovery doc).
// Generating this would widen metadata to Record<string, unknown> | null.
// Long-term fix: add OIDCProviderMetadata Pydantic model to backend OIDCTestResult.
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
