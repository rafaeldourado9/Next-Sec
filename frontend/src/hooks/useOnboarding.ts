import { useState } from 'react'

const STORAGE_KEY = 'vms_onboarding_complete'

export function useOnboarding() {
  const [complete, setComplete] = useState(() => localStorage.getItem(STORAGE_KEY) === '1')

  function markComplete() {
    localStorage.setItem(STORAGE_KEY, '1')
    setComplete(true)
  }

  function reset() {
    localStorage.removeItem(STORAGE_KEY)
    setComplete(false)
  }

  return { complete, markComplete, reset }
}
