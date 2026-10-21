import { Link } from "react-router-dom";
import './Header.css'

export function Header() {
  return (
    <header className="site-header">
      <Link to="/sistema" className="logo" aria-label="Ir para a consulta de servidores">
        Consulta de <strong>Servidores</strong>
      </Link>
    </header>
  );
};