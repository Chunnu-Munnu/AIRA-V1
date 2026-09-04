import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { getSession, onSession } from "./lib/api";
import { LanguageProvider } from "./lib/lang";

import Login from "./pages/Login";
import Signup from "./pages/Signup";

import PatientShell from "./pages/patient/Shell";
import Dashboard from "./pages/patient/Dashboard";
import Report from "./pages/patient/Report";
import Timeline from "./pages/patient/Timeline";
import Access from "./pages/patient/Access";
import Screening from "./pages/patient/Screening";
import Ask from "./pages/patient/Ask";
import Reports from "./pages/patient/Reports";
import Notes from "./pages/patient/Notes";

import DoctorShell from "./pages/doctor/Shell";
import Queue from "./pages/doctor/Queue";
import PatientRecord from "./pages/doctor/PatientRecord";
import AddPatient from "./pages/doctor/AddPatient";

import AdminConsole from "./pages/admin/Console";

function useSession() {
  const [s, setS] = useState(getSession());
  useEffect(() => onSession(setS), []);
  return s;
}

function Guard({ role, children }) {
  const s = useSession();
  const loc = useLocation();
  if (!s) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  if (role && s.role !== role) return <Navigate to={home(s.role)} replace />;
  return children;
}

const home = (role) =>
  role === "DOCTOR" ? "/clinic" : role === "ADMIN" ? "/admin" : "/app";

export default function App() {
  const s = useSession();

  return (
    <Routes>
      <Route path="/login" element={s ? <Navigate to={home(s.role)} replace /> : <Login />} />
      <Route path="/signup" element={s ? <Navigate to={home(s.role)} replace /> : <Signup />} />

      <Route
        path="/app"
        element={
          <Guard role="PATIENT">
            <LanguageProvider>
              <PatientShell />
            </LanguageProvider>
          </Guard>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="ask" element={<Ask />} />
        <Route path="reports" element={<Reports />} />
        <Route path="notes" element={<Notes />} />
        <Route path="timeline" element={<Timeline />} />
        <Route path="card" element={<Report />} />
        {/* the old path, kept so a bookmarked link still lands somewhere */}
        <Route path="report" element={<Report />} />
        <Route path="screening" element={<Screening />} />
        <Route path="access" element={<Access />} />
      </Route>

      <Route
        path="/clinic"
        element={
          <Guard role="DOCTOR">
            <DoctorShell />
          </Guard>
        }
      >
        <Route index element={<Queue />} />
        <Route path="add" element={<AddPatient />} />
        <Route path="p/:id" element={<PatientRecord />} />
      </Route>

      <Route
        path="/admin"
        element={
          <Guard role="ADMIN">
            <AdminConsole />
          </Guard>
        }
      />

      <Route path="*" element={<Navigate to={s ? home(s.role) : "/login"} replace />} />
    </Routes>
  );
}
