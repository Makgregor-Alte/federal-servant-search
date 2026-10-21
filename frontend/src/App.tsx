import './styles/themes.css'
import './styles/global.css'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { Cadastro } from './components/Cadastro/Cadastro'
import { Layout } from './components/Layout/Layout'
import { Login } from './components/Login/Login'
import { Sistema } from './components/Sistema/Sistema'

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path='/' element={<Navigate to='/sistema' replace />} />
          <Route path='/cadastro' element={<Cadastro />} />
          <Route path='/login' element={<Login />} />
          <Route path='/sistema' element={<Sistema />} />
          <Route path='*' element={<Navigate to='/sistema' replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
