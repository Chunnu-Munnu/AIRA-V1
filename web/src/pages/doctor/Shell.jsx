import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { getSession, logout } from "../../lib/api";
import Logo from "../../components/Logo";

/**
 * The clinician surface is deliberately a different product from the patient
 * app. Dark, dense, tabular, no reassurance. A medical officer at a CHC sees
 * sixty patients before lunch; the job of this screen is to let them find the
 * two who are stuck, in under ten seconds, and then get out of the way.
 */
export default function DoctorShell() {
  const nav = useNavigate();
  const s = getSession();

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-white/10 bg-slate-900/70 backdrop-blur sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-6 h-14 flex items-center justify-between gap-6">
          <div className="flex items-center gap-7">
            <Logo tone="light" size={24} />
            <nav className="flex items-center gap-1">
              {[
                ["/clinic", "Queue", true],
                ["/clinic/add", "Add patient", false],
              ].map(([to, label, end]) => (
                <NavLink
                  key={to}
                  to={to}
                  end={end}
                  className={({ isActive }) =>
                    `rounded-md px-3 py-1.5 text-[13px] font-semibold transition ${
                      isActive
                        ? "bg-white/10 text-white"
                        : "text-slate-400 hover:text-white"
                    }`
                  }
                >
                  {label}
                </NavLink>
              ))}
            </nav>
          </div>

          <div className="flex items-center gap-4 text-[13px]">
            <span className="text-slate-400">{s?.display_name}</span>
            <button
              onClick={async () => {
                await logout();
                nav("/login");
              }}
              className="font-semibold text-slate-400 hover:text-white"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-6">
        <Outlet />
      </main>
    </div>
  );
}
