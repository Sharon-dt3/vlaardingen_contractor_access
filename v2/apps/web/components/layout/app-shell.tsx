"use client";

import {
  Building2,
  ChevronRight,
  ClipboardList,
  FileClock,
  LayoutDashboard,
  LogOut,
  MailPlus,
  Menu,
  ScanLine,
  Settings,
  ShieldCheck,
  UsersRound,
  X
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { PageSkeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status-badge";
import { roleLabel } from "@/lib/domain";
import { cn } from "@/lib/utils";

type NavigationItem = {
  label: string;
  href: string;
  icon: typeof LayoutDashboard;
  permission?: string;
};

const navigation: NavigationItem[] = [
  { label: "Overview", href: "/", icon: LayoutDashboard },
  {
    label: "Invitations",
    href: "/invitations",
    icon: MailPlus,
    permission: "invitations:read"
  },
  { label: "People", href: "/people", icon: UsersRound, permission: "people:read" },
  {
    label: "Companies",
    href: "/companies",
    icon: Building2,
    permission: "companies:read"
  },
  { label: "Visits", href: "/visits", icon: ClipboardList, permission: "visits:read" },
  {
    label: "Gate kiosk",
    href: "/gate",
    icon: ScanLine,
    permission: "gate:evaluate"
  },
  { label: "Audit trail", href: "/audit", icon: FileClock, permission: "audit:read" },
  { label: "Settings", href: "/settings", icon: Settings, permission: "*" }
];

function Brand() {
  return (
    <Link aria-label="Renewi Access home" className="flex items-center gap-3 rounded-lg" href="/">
      <span className="grid h-10 w-10 place-items-center rounded-xl bg-emerald-500 text-white shadow-sm">
        <ShieldCheck aria-hidden="true" className="h-5 w-5" strokeWidth={2.4} />
      </span>
      <span>
        <span className="block text-sm font-bold tracking-tight text-white">Renewi Access</span>
        <span className="block text-xs text-slate-400">Site assurance demo</span>
      </span>
    </Link>
  );
}

type NavigationProps = {
  onNavigate?: () => void;
};

function Navigation({ onNavigate }: NavigationProps) {
  const pathname = usePathname();
  const { hasPermission, user } = useAuth();
  const visibleItems = navigation.filter(
    (item) =>
      user?.role !== "participant" &&
      (!item.permission || hasPermission(item.permission)) ||
      item.href === "/"
  );

  return (
    <nav aria-label="Primary navigation" className="mt-8">
      <p className="px-3 text-[0.6875rem] font-semibold uppercase tracking-[0.16em] text-slate-500">
        Authorized workspace
      </p>
      <ul className="mt-3 space-y-1">
        {visibleItems.map((item) => {
          const Icon = item.icon;
          const isActive =
            pathname === item.href ||
            (item.href !== "/" && pathname.startsWith(`${item.href}/`));

          return (
            <li key={item.href}>
              <Link
                aria-current={isActive ? "page" : undefined}
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition",
                  isActive
                    ? "bg-emerald-500/15 text-emerald-300"
                    : "text-slate-300 hover:bg-white/5 hover:text-white"
                )}
                href={item.href}
                onClick={onNavigate}
              >
                <Icon aria-hidden="true" className="h-[1.125rem] w-[1.125rem]" />
                <span>{item.label}</span>
                <ChevronRight aria-hidden="true" className="ml-auto h-4 w-4 opacity-50" />
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

type SidebarProps = {
  onNavigate?: () => void;
  onLogout: () => void;
};

function Sidebar({ onNavigate, onLogout }: SidebarProps) {
  const { user } = useAuth();

  return (
    <div className="flex h-full flex-col bg-slate-950 px-4 py-5">
      <Brand />
      <Navigation onNavigate={onNavigate} />
      <div className="mt-auto space-y-3">
        {user ? (
          <div className="rounded-xl border border-white/10 bg-white/[0.04] p-3.5">
            <p className="truncate text-sm font-semibold text-white">{user.display_name}</p>
            <p className="mt-1 text-xs text-slate-400">{roleLabel(user.role)}</p>
            <button
              className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-xs font-semibold text-slate-200 transition hover:bg-white/10"
              onClick={onLogout}
              type="button"
            >
              <LogOut aria-hidden="true" className="h-4 w-4" />
              Sign out
            </button>
          </div>
        ) : null}
        <div className="rounded-xl border border-emerald-400/20 bg-emerald-400/[0.06] p-3.5">
          <div className="flex items-center gap-2 text-xs font-semibold text-emerald-300">
            <span aria-hidden="true" className="h-2 w-2 rounded-full bg-emerald-400" />
            Deterministic demo
          </div>
          <p className="mt-2 text-xs leading-5 text-slate-400">
            API roles remain authoritative even when modules are hidden here.
          </p>
        </div>
      </div>
    </div>
  );
}

type AppShellProps = {
  children: ReactNode;
};

// PUBLIC_INTERFACE
/**
 * Wraps authenticated routes in role-aware responsive navigation and session controls.
 */
export function AppShell({ children }: AppShellProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, isLoading, logout } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);
  const mobileMenuButtonRef = useRef<HTMLButtonElement>(null);
  const mobileNavigationCloseRef = useRef<HTMLButtonElement>(null);
  const isLoginRoute = pathname === "/login";
  const isInviteeRoute = pathname === "/register";

  useEffect(() => {
    document.body.style.overflow = mobileOpen ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [mobileOpen]);

  useLayoutEffect(() => {
    if (!mobileOpen) {
      return;
    }

    mobileNavigationCloseRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMobileOpen(false);
        requestAnimationFrame(() => mobileMenuButtonRef.current?.focus());
      }
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [mobileOpen]);

  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!isLoading && !user && !isLoginRoute && !isInviteeRoute) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [isLoading, isLoginRoute, isInviteeRoute, pathname, router, user]);

  async function handleLogout() {
    await logout();
    router.replace("/login");
  }

  function closeMobileNavigation() {
    setMobileOpen(false);
    requestAnimationFrame(() => mobileMenuButtonRef.current?.focus());
  }

  if (isLoginRoute || isInviteeRoute) {
    return isInviteeRoute ? (
      <main className="mx-auto min-h-screen max-w-3xl px-4 py-8 sm:px-6" id="main-content">
        {children}
      </main>
    ) : <>{children}</>;
  }

  if (isLoading || !user) {
    return (
      <main className="mx-auto min-h-screen max-w-5xl px-4 py-10 sm:px-6">
        <PageSkeleton />
      </main>
    );
  }

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[17rem_minmax(0,1fr)]">
      <a
        className="fixed left-3 top-3 z-[60] -translate-y-20 rounded-lg bg-white px-4 py-2 text-sm font-semibold text-slate-950 shadow-lg transition focus:translate-y-0"
        href="#main-content"
      >
        Skip to main content
      </a>

      <aside className="fixed inset-y-0 left-0 z-40 hidden w-[17rem] lg:block">
        <Sidebar onLogout={() => void handleLogout()} />
      </aside>

      {mobileOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            aria-label="Close navigation"
            className="absolute inset-0 bg-slate-950/55 backdrop-blur-sm"
            onClick={closeMobileNavigation}
            type="button"
          />
          <aside
            aria-label="Primary navigation"
            aria-modal="true"
            className="relative h-full w-[min(19rem,86vw)] shadow-2xl"
            id="mobile-navigation"
            role="dialog"
          >
            <Sidebar
              onLogout={() => void handleLogout()}
              onNavigate={closeMobileNavigation}
            />
            <button
              aria-label="Close navigation"
              className="absolute right-3 top-4 grid h-9 w-9 place-items-center rounded-lg text-slate-300 hover:bg-white/10 hover:text-white"
              onClick={closeMobileNavigation}
              ref={mobileNavigationCloseRef}
              type="button"
            >
              <X aria-hidden="true" className="h-5 w-5" />
            </button>
          </aside>
        </div>
      ) : null}

      <div className="min-w-0 lg:col-start-2">
        <header className="sticky top-0 z-30 border-b bg-white/90 backdrop-blur-xl">
          <div className="flex h-16 items-center gap-3 px-4 sm:px-6 lg:px-8">
            <button
              aria-controls="mobile-navigation"
              aria-expanded={mobileOpen}
              aria-label="Open navigation"
              className="grid h-10 w-10 place-items-center rounded-lg border bg-white text-slate-700 hover:bg-slate-50 lg:hidden"
              onClick={() => setMobileOpen(true)}
              ref={mobileMenuButtonRef}
              type="button"
            >
              <Menu aria-hidden="true" className="h-5 w-5" />
            </button>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-slate-950">Vlaardingen</p>
              <p className="hidden text-xs text-muted-foreground sm:block">
                Contractor & visitor access
              </p>
            </div>
            <div className="ml-auto flex items-center gap-2 sm:gap-4">
              <StatusBadge className="hidden sm:inline-flex" tone="demo">
                Demo mode
              </StatusBadge>
              <div className="text-right">
                <p className="max-w-40 truncate text-xs font-semibold text-slate-950">
                  {user.display_name}
                </p>
                <p className="hidden text-[0.6875rem] text-muted-foreground sm:block">
                  {roleLabel(user.role)}
                </p>
              </div>
            </div>
          </div>
        </header>

        <main
          className="mx-auto w-full max-w-[100rem] px-4 py-7 sm:px-6 sm:py-9 lg:px-8"
          id="main-content"
        >
          {children}
        </main>
      </div>
    </div>
  );
}
