import type { Role } from "./api/types";

export const ROLES: readonly Role[] = ["owner", "admin", "viewer"] as const;

const ROLE_LABEL: Record<Role, string> = { owner: "Owner", admin: "Admin", viewer: "Viewer" };

const ROLE_DESCRIPTION: Record<Role, string> = {
  owner: "Full control, including users and roles.",
  admin: "Creates projects, uploads specs, runs generations and manages API keys.",
  viewer: "Read only: browses projects, lint reports and generated code, and downloads archives.",
};

export function isRole(value: unknown): value is Role {
  return typeof value === "string" && (ROLES as readonly string[]).includes(value);
}

export function roleLabel(role: string | null | undefined): string {
  return isRole(role) ? ROLE_LABEL[role] : "Unknown";
}

export function roleDescription(role: string | null | undefined): string {
  return isRole(role) ? ROLE_DESCRIPTION[role] : "";
}

/** Owners and admins create, upload, generate and delete; viewers only read. */
export function canWrite(role: string | null | undefined): boolean {
  return role === "owner" || role === "admin";
}

/** Only owners invite people, change roles or disable accounts. */
export function canManageUsers(role: string | null | undefined): boolean {
  return role === "owner";
}
