import { useState } from "react";
import { FormEvent } from "react";

import './Sistema.css'

export function Sistema() {

  function handleSubmit(e: FormEvent) {
    e.preventDefault()

  }

  return (
    <div className="sistema">
      <main className="sistema-card">

        <h1>Consultar pessoas</h1>
        <p className="subtitle">Busque por CPF, nome ou parte do nome</p>

        <div className="abas" role="tablist" aria-label="Tipo de busca">

        </div>

        <form onSubmit={handleSubmit} noValidate className="form-busca">
          <div className="field">
            <input
              id="valor"
              type="text"
              /* Terminar amanhã depois do serviço */
            />
          </div>
        </form>

      </main>
    </div>
  );
}