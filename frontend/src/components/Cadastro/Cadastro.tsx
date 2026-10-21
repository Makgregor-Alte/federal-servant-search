import { Link } from 'react-router-dom'

import './Cadastro.css'

export function Cadastro() {
  return (
    <div className="cadastro">
      <main className="card">
        <h1>Consulta pública</h1>
        <p className="subtitle">Não é necessário criar uma conta.</p>
        <p className="aviso-acesso">
          O sistema permite pesquisar os registros disponíveis sem cadastro
          de usuários. Nenhum dado de conta será solicitado.
        </p>
        <Link to="/sistema" className="btn-primary">Ir para a consulta</Link>
      </main>
    </div>
  )
}
