import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";

import './Sistema.css'

interface Pessoa {
  nome: string;
  cpf: string;
  sexo:string;
  data_nascimento: string;
};

const porPagina = 10;

function mascararCpf(valor: string) {
  return valor
    .replace(/\D/g, '')
    .slice(0, 11)
    .replace(/^(\d{3})(\d)/, '$1.$2')
    .replace(/^(\d{3})\.(\d{3})(\d)/, '$1.$2.$3')
    .replace(/\.(\d{3})(\d)/, '.$1-$2');

} 

export function Sistema() {

  const [tipo, setTipo] = useState<"cpf" | "nome" | "similar">("cpf");
  const [busca, setBusca] = useState('');
  const [limite, setLimite] = useState('100');
  const [erro, setErro] = useState('');

  const [resultados, setResultados] = useState<Pessoa[]>([]);
  const [pagina, setPagina] = useState(1);
  const [selecionada, setSelecionada] = useState<Pessoa | null>(null);

  const totalPaginas = Math.ceil(resultados.length / porPagina);
  const visiveis = resultados.slice((pagina - 1) * porPagina, pagina * porPagina);

  const detalhe = selecionada ?? (resultados.length === 1 ? resultados[0] : null);

  function trocarTipo(novo: 'cpf' | 'nome' | 'similar') {
    setTipo(novo);
    setBusca('');
    setErro('')
    setResultados([])
    setSelecionada(null);
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();

    if (tipo === "cpf" && busca.replace(/\D/g, '').length !== 11) {
      setErro('Informe um CPF com 11 digitos');
      return;
    }

    if (tipo !== 'cpf') {
      const permitido = tipo === "nome" ? /^[\p{L}\s]+$/u : /^[\p{L}\s%]+$/u;

    if (!busca.trim()) {
      setErro('Informe o nome ou o padrão de busca.');
      return;
    }

    if (!permitido.test(busca.trim())) {
      setErro('Use apenas letras e espaços (e % na busca por similaridade).');
      return;
    }
    
    }

    if (tipo === 'similar' && (Number(limite) < 1 || Number(limite) > 1000)) {
      setErro('O limite deve estar entre 1 e 1000');
      return;
    }

    setErro('');
    setResultados([]);
    setPagina(1)
    setSelecionada(null)

    console.log({ tipo, busca, limite })

    /*       ##  TESTES DA PÁGINA  ##
    const dados: Pessoa[] = Array.from({ length: 25 }, (_, i) =>({
      nome: `Pessoa Teste ${i + 1}`,
      cpf: String(10000000000 + i),
      sexo: i % 2 === 0 ? "F" : "M",
      data_nascimento: "1990-05-17"
    }));

    if (busca.trim().toLowerCase() === "erro") {
      setErro('Nenhum registro encontrado para essa busca.');
      return;
    }

    setResultados(tipo === "cpf" ? dados.slice(0, 1) : dados.slice(0, Number(limite)));
    */
  };

  return (
    <div className="sistema">
      <main className="card">
        <h1> Consultar pessoas</h1>
        <p className="subtitle">Busque por CPF, nome ou parte do nome</p>

        <div className="abas" role="tablist">
          <button 
            type="button"
            role="tab"
            className={tipo === 'cpf' ? 'aba ativa' : 'aba'}
            onClick={() => trocarTipo('cpf')}
          >
            CPF
          </button>
          <button
            type="button"
            role="tab"
            className={tipo === 'nome' ? 'aba ativa' : 'aba'}
            onClick={() => trocarTipo('nome')}
          >
            Nome
          </button>
          <button
            type="button"
            role="tab"
            className={tipo === 'similar' ? 'aba ativa' : 'aba'}
            onClick={() => trocarTipo('similar')}
          >
            Similaridade
          </button>
        </div>

        <form onSubmit={handleSubmit} noValidate>
          <div className="field">
            <input 
              id="busca"
              placeholder=" "
              autoComplete="off"
              value={busca}
              onChange={(e) =>
                setBusca(tipo === 'cpf' ? mascararCpf(e.target.value) : e.target.value)
              }
            />
            <label htmlFor="busca">
              {tipo === 'cpf' && 'CPF'}
              {tipo === 'nome' && 'Nome completo'}
              {tipo === 'similar' && 'Padrão, ex.: %MARIA%SILVA%'}
            </label>
          </div>

          {tipo === 'similar' && (
            <div className="field">
              <input
                id="limite"
                type="number"
                placeholder=" "
                value={limite}
                onChange={(e) => setLimite(e.target.value)}
              />
              <label htmlFor="limite"> Limite de resultados</label>
            </div>
          )}

          {tipo === 'similar' && (
            <p className="dica">
              Use % no lugar de qualquer trecho. Ex.: %MARIA%SILVA%, MARIA SILVA% ou MARIA%SILVA.
            </p>
          )}

          {erro && (
            <p className="erro" role="alert">
              {erro}
            </p>
          )}

          <button type="submit" className="btn-primary">
            Buscar
          </button>
        </form>

        {detalhe && (
          <section className="detalhe">
            {resultados.length > 1 && (
              <button
                type="button"
                className="voltar"
                onClick={() => setSelecionada(null)}
              >
                Voltar para a lista
              </button>
            )}

            <h2>{detalhe.nome}</h2>

            <dl>
              <div>
                <dt>CPF</dt>
                <dd>{mascararCpf(detalhe.cpf)}</dd>
              </div>
              <div>
                <dt>Sexo</dt>
                <dd>{detalhe.sexo}</dd>
              </div>
              <div>
                <dt>Data de nascimento</dt>
                <dd>{detalhe.data_nascimento.split("-").reverse().join("/")}</dd>
              </div>
            </dl>
          </section>
        )}

        {!selecionada && resultados.length > 1 && (
          <section className="lista">
            <p className="contagem">{resultados.length} resultados encontrados</p>

            <ul>
              {visiveis.map((p) => (
                <li key={p.cpf}>
                  <button
                    type="button"
                    className="item"
                    onClick={() => setSelecionada(p)}
                  >
                    <span>{p.nome}</span>
                    <span className="cpf">{mascararCpf(p.cpf)}</span>
                  </button>
                </li>
              ))}
            </ul>

            <div className="paginacao">
              <button
                type="button"
                disabled={pagina === 1}
                onClick={() => setPagina(pagina - 1)}
              >
                Anterior
              </button>

              <span>
                Página {pagina} de {totalPaginas}
              </span>

              <button
                type="button"
                disabled={pagina === totalPaginas}
                onClick={() => setPagina(pagina + 1)}
              >
                Próxima
              </button>
            </div>
          </section>
        )}
      </main>

      <p className="sair">
        Quer trocar de conta? <Link to="/login">Sair</Link>
      </p>
    </div>
  );
}