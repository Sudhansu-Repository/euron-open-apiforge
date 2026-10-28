import {
  FlaskConicalIcon,
  FolderKanbanIcon,
  KeyRoundIcon,
  LayoutDashboardIcon,
  ScrollTextIcon,
  SettingsIcon,
  UsersIcon,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Hidden from viewers when the API only serves admins and owners. */
  adminOnly?: boolean;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export const NAV: NavGroup[] = [
  {
    label: "Build",
    items: [
      { href: "/", label: "Overview", icon: LayoutDashboardIcon },
      { href: "/projects", label: "Projects", icon: FolderKanbanIcon },
      { href: "/playground", label: "Playground", icon: FlaskConicalIcon },
    ],
  },
  {
    label: "Organisation",
    items: [
      { href: "/keys", label: "API keys", icon: KeyRoundIcon, adminOnly: true },
      { href: "/users", label: "Users", icon: UsersIcon, adminOnly: true },
      { href: "/audit", label: "Audit log", icon: ScrollTextIcon, adminOnly: true },
      { href: "/settings", label: "Settings", icon: SettingsIcon },
    ],
  },
];

export const NAV_ITEMS: NavItem[] = NAV.flatMap((g) => g.items);

/** The nav item a path belongs to: exact match for "/", the longest prefix otherwise. */
export function activeNavItem(pathname: string): NavItem | undefined {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (path === "/") return NAV_ITEMS.find((i) => i.href === "/");
  return NAV_ITEMS.filter((i) => i.href !== "/" && (path === i.href || path.startsWith(`${i.href}/`))).sort(
    (a, b) => b.href.length - a.href.length,
  )[0];
}

export function isActive(item: NavItem, pathname: string): boolean {
  return activeNavItem(pathname)?.href === item.href;
}
