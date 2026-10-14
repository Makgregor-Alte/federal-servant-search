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
        {/* Toda rota dentro deste route ganha o header */}
        <Route element={<Layout />}>
          <Route path='/' element={<Navigate to='/cadastro' replace />} />
          <Route path='/cadastro' element={<Cadastro />} />
          <Route path='/login' element={<Login />} />
          <Route path='/sistema' element={<Sistema />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}


