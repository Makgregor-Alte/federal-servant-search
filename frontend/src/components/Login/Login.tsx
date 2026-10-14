import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";

import './Login.css'

export function Login() {
  const [email, setEmail] = useState('')
  const [senha, setSenha] = useState('')
  const [erro, setErro] = useState('')

  function handleSubmit(e: FormEvent) {
    e.preventDefault();

    if (!email.includes('@') || !senha) {
      setErro('Informe seu e-mail e senha.');
      return
    };

    /* Limpa os erros antigos */
    setErro('')
    console.log({ email, senha })
  }

  return (
    <div className="cadastro">
      <main className="card">
        <h1>Entrar</h1>
        <p className="subtitle">Entre para continuar</p>

        <form onSubmit={handleSubmit} noValidate>
          <div className="field">
            <input
              id="email"
              type="email"
              autoComplete="email"
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
              autoComplete="current-password"
              placeholder=" "
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
            Entrar
          </button>

        </form>

      </main>

      <p className="cadastrar">
        Não possui uma conta? <Link to="/cadastro">Cadastrar</Link>
      </p>

    </div>
  );

};
