import { createContext, useContext } from 'react'

export const AuthCtx = createContext(null)
export const useMe = () => useContext(AuthCtx).me
