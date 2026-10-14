import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";

import './Cadastro.css'

export function Cadastro() {
  const [nome, setNome] = useState('');
  const [email, setEmail] = useState('');
  const [senha, setSenha] = useState('');
  const [erro, setErro] = useState('');

  function handleSubmit(e: FormEvent) {
    e.preventDefault();

    if (!nome.trim() || !email.includes("@") || senha.length < 8) {
      setErro('Preencha o nome, um e-mail válido e uma senha com 8 caracteres ou mais.');
      return;
    }

    setErro('')
    console.log({ nome, email, senha })
  };

  return (
    <div className="cadastro">
      <main className="card">
        <h1>Criar conta</h1>
        <p className="subtitle">Crie sua conta para continuar</p>

        <form onSubmit={handleSubmit} noValidate>
          <div className="field">
            <input
              id="nome"
              placeholder=" "
              value={nome}
              onChange={(e) => setNome(e.target.value)}
            />
            <label htmlFor="nome">Nome</label>
          </div>

          <div className="field">
            <input
              id="email"
              type="email"
              placeholder=" "
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <label htmlFor="email">E-mail</label>
          </div>

          <div className="field">
            <input
              id="senha"
              type="password"
              placeholder=" "
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
            />
            <label htmlFor="senha">Senha</label>
          </div>

          {erro && (
            <p className="erro" role="alert">
              {erro}
            </p>
          )}

          <button type="submit" className="btn-primary">
            Criar conta
          </button>
        </form>
      </main>

      <p className="signin">
        Já tem uma conta? <Link to="/login">Entrar</Link>
      </p>
    </div>
  )
}