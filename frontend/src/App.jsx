import { Routes, Route, Navigate } from 'react-router-dom'
import { AppShell } from './components/AppShell.jsx'
import { Overview } from './pages/Overview.jsx'
import { LiveStream } from './pages/LiveStream.jsx'
import { LiveCheck } from './pages/LiveCheck.jsx'
import { Policy } from './pages/Policy.jsx'
import { Customer } from './pages/Customer.jsx'
import { InvestigationIndex } from './pages/InvestigationIndex.jsx'
import { Investigation } from './pages/Investigation.jsx'

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/stream" element={<LiveStream />} />
        <Route path="/check" element={<LiveCheck />} />
        <Route path="/policy" element={<Policy />} />
        <Route path="/customers/:id" element={<Customer />} />
        <Route path="/investigation" element={<InvestigationIndex />} />
        <Route path="/investigation/:id" element={<Investigation />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  )
}
