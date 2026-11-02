import { useState } from 'react'

import type { Loadable } from './api'

/** Keeps the last result on screen while a changed request loads, so a control inside the page does not
 *  collapse it to a skeleton and reset its state. `stale` is true while the old result stands in. */
export function usePrevious<T>(state: Loadable<T>): Loadable<T> & { stale: boolean } {
  const [kept, setKept] = useState<T>()
  if (state.data !== undefined && state.data !== kept) setKept(state.data)
  const stale = state.data === undefined && !state.error && kept !== undefined
  return { ...state, data: stale ? kept : state.data, stale }
}
