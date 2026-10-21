import { Link } from 'react-router-dom'

import './Login.css'

export function Login() {
  return (
    <div className="cadastro">
      <main className="card">
        <h1>Consultar servidores</h1>
        <p className="subtitle">Acesso público, sem necessidade de entrar com uma conta.</p>
        <p className="aviso-acesso">
          Esta versão não possui autenticação. Para consultar registros públicos,
          acesse diretamente a pesquisa.
        </p>
        <Link to="/sistema" className="btn-primary">Ir para a consulta</Link>
      </main>
    </div>
  )
}
