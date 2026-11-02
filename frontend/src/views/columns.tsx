import type { ExecYear } from '../api'
import { ROLE_LABEL, keur } from '../format'
import type { Column } from '../ui'

/** Pay table columns shared by the company, explorer and person views (amounts in k€). */
export const execColumns: Column<ExecYear>[] = [
  { key: 'name', label: 'Name', value: (e) => e.name, render: (e) => <a href={`#/people/${e.person_id}`}>{e.name}</a> },
  { key: 'role', label: 'Role', value: (e) => ROLE_LABEL[e.role] },
  { key: 'days', label: 'Days', numeric: true, value: (e) => e.days },
  { key: 'fixed', label: 'Fixed', numeric: true, value: (e) => e.fixed, render: (e) => keur(e.fixed) },
  { key: 'sti', label: 'Bonus', numeric: true, value: (e) => e.sti, render: (e) => keur(e.sti) },
  { key: 'mti', label: 'Multi-year', numeric: true, value: (e) => e.mti, render: (e) => keur(e.mti) },
  { key: 'lti', label: 'Share-based', numeric: true, value: (e) => e.lti, render: (e) => keur(e.lti) },
  { key: 'other', label: 'Other', numeric: true, value: (e) => e.other, render: (e) => keur(e.other) },
  { key: 'total', label: 'Total', numeric: true, value: (e) => e.total, render: (e) => <strong>{keur(e.total)}</strong> },
  { key: 'pension', label: 'Pension', numeric: true, value: (e) => e.pension, render: (e) => keur(e.pension) },
]
